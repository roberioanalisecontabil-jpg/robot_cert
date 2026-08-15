"""Trilha de instalação agrupada por token.

A lista plana mostrava eventos soltos em ordem cronológica. O que importa é
**onde a cadeia quebrou**, e os números reais de produção explicam por quê:

    SOLICITADO 9  →  REDIMIDO 8  →  CONCLUIDO 2
                                    ERRO      6

Lidos em fila são 25 linhas sem forma. Agrupados, são dez tentativas das quais
seis morreram no mesmo ponto (`REDIMIDO`) e pela mesma causa — que foi como se
descobriu que a senha estava ausente no cofre. E, depois que o cofre foi
repovoado em 15/08, as três tentativas seguintes concluíram.

O teste `test_causa_unica_aparece_no_resumo` é o que guarda esse valor: contar
motivos é o que transforma "seis falhas" em "um problema".
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci


class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake") -> None:
        self._l, self._b = linhas, banco
        self._desde: Optional[str] = None
        self._limite: Optional[int] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def gte(self, coluna: str, valor: str) -> "_Query":
        assert coluna == "created_at"
        self._desde = valor
        return self

    def order(self, _c: str, desc: bool = False) -> "_Query":
        self._desc = desc
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def execute(self) -> _Resultado:
        if self._b.quebrado:
            raise RuntimeError("banco fora do ar")
        linhas = [r for r in self._l if not self._desde or r["created_at"] >= self._desde]
        linhas.sort(key=lambda r: r["created_at"], reverse=True)
        if self._limite:
            linhas = linhas[: self._limite]
        return _Resultado([dict(r) for r in linhas])


class _Fake:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self.linhas = linhas
        self.quebrado = False

    def table(self, nome: str) -> _Query:
        assert nome == "install_log"
        return _Query(self.linhas, self)


AGORA = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)


def _ev(token: str, evento: str, minutos_atras: int, *, status=None, detail=None,
        email="roberio@x.com", maquina="download-avulso", cert="c1") -> dict:
    return {
        "id": f"{token}-{evento}",
        "token_id": token,
        "event": evento,
        "status": status,
        "detail": detail,
        "user_email": email,
        "target_machine": maquina,
        "client_ip": "10.0.0.1",
        "certificate_id": cert,
        "created_at": (AGORA - timedelta(minutes=minutos_atras)).isoformat(),
    }


SENHA_AUSENTE = "Senha ausente no cofre; reenvie o certificado pelo agente."


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    """Reproduz a forma dos dados reais: falhas antigas, sucessos recentes."""
    linhas = []
    # Três tentativas que falharam no mesmo ponto, pela mesma causa.
    for i, tok in enumerate(["t-falha-1", "t-falha-2", "t-falha-3"]):
        base = 2000 + i * 100
        linhas += [
            _ev(tok, "SOLICITADO", base),
            _ev(tok, "REDIMIDO", base - 1),
            _ev(tok, "ERRO", base - 2, status="FALHA", detail=SENHA_AUSENTE),
        ]
    # Uma concluída.
    linhas += [
        _ev("t-ok", "SOLICITADO", 60),
        _ev("t-ok", "REDIMIDO", 59),
        _ev("t-ok", "CONCLUIDO", 58, status="OK"),
    ]
    # Uma que parou no pedido — nem falhou, nem concluiu.
    linhas += [_ev("t-parada", "SOLICITADO", 30, email="outro@x.com")]

    fake = _Fake(linhas)
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    return fake


def _admin() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'admin@x.com', 'role': 'admin'})}"}


# ──────────────────────────────────────────────────────────────────────────
# 1. Agrupar por tentativa, não por evento
# ──────────────────────────────────────────────────────────────────────────

def test_uma_linha_por_tentativa(banco: _Fake) -> None:
    """Treze eventos soltos viram cinco tentativas legíveis."""
    cadeias = ci.cadeias_de_instalacao()
    assert len(banco.linhas) == 13
    assert len(cadeias) == 5


def test_desfecho_de_cada_cadeia(banco: _Fake) -> None:
    por_token = {c["token_id"]: c for c in ci.cadeias_de_instalacao()}
    assert por_token["t-ok"]["desfecho"] == "concluido"
    assert por_token["t-falha-1"]["desfecho"] == "falhou"
    assert por_token["t-parada"]["desfecho"] == "incompleto"


def test_diz_onde_a_cadeia_parou(banco: _Fake) -> None:
    """
    É a informação que a lista plana não dava. Saber que parou em REDIMIDO
    aponta para o resgate do token, não para o pedido nem para a instalação.
    """
    por_token = {c["token_id"]: c for c in ci.cadeias_de_instalacao()}
    assert por_token["t-falha-1"]["parou_em"] == "REDIMIDO"
    assert por_token["t-parada"]["parou_em"] == "SOLICITADO"
    assert por_token["t-ok"]["parou_em"] is None, "quem concluiu não parou em lugar nenhum"


def test_eventos_ficam_em_ordem_cronologica(banco: _Fake) -> None:
    """A consulta vem decrescente; a cadeia só faz sentido lida do começo."""
    cadeia = next(c for c in ci.cadeias_de_instalacao() if c["token_id"] == "t-ok")
    assert [e["event"] for e in cadeia["eventos"]] == ["SOLICITADO", "REDIMIDO", "CONCLUIDO"]


def test_eventos_sem_token_nao_somem_nem_se_fundem(banco: _Fake) -> None:
    """
    Falha antes de o token nascer é rara, mas some numa agregação ingênua — e é
    exatamente o tipo de evento que interessa numa investigação.

    E cada um vira uma cadeia própria. Agrupá-los juntos só porque nenhum tem
    token inventaria uma tentativa que nunca existiu: dois erros de dias
    diferentes apareceriam como uma cadeia só, com dois motivos, sugerindo uma
    sequência que não houve.
    """
    for i, quando in enumerate((10, 500)):
        orfao = _ev(f"x{i}", "ERRO", quando, status="FALHA", detail=f"explodiu antes do token {i}")
        orfao["token_id"] = None
        orfao["id"] = f"orfao-{i}"
        banco.linhas.append(orfao)

    orfas = [c for c in ci.cadeias_de_instalacao() if c["token_id"] is None]
    assert len(orfas) == 2, "órfãos distintos não podem virar uma cadeia só"
    assert all(len(c["eventos"]) == 1 for c in orfas)


# ──────────────────────────────────────────────────────────────────────────
# 2. O resumo — contar motivos é o que transforma falhas em problema
# ──────────────────────────────────────────────────────────────────────────

def test_funil_e_taxa_de_conclusao(banco: _Fake) -> None:
    r = ci.resumo_das_cadeias(ci.cadeias_de_instalacao())
    assert r["total"] == 5
    assert r["concluidas"] == 1
    assert r["falhadas"] == 3
    assert r["incompletas"] == 1
    assert r["taxa_conclusao"] == 20


def test_causa_unica_aparece_no_resumo(banco: _Fake) -> None:
    """
    O teste que guarda o valor da etapa.

    Em produção, as seis falhas registradas tinham a MESMA causa. Em lista
    plana isso é invisível; contando os motivos, vira uma linha que aponta
    direto para o conserto.
    """
    r = ci.resumo_das_cadeias(ci.cadeias_de_instalacao())
    assert r["causas"] == {SENHA_AUSENTE: 3}


def test_resumo_de_periodo_vazio_nao_quebra() -> None:
    assert ci.resumo_das_cadeias([])["taxa_conclusao"] is None


# ──────────────────────────────────────────────────────────────────────────
# 3. Filtros
# ──────────────────────────────────────────────────────────────────────────

def test_filtro_de_periodo_corta_no_banco(banco: _Fake) -> None:
    recentes = ci.cadeias_de_instalacao(desde=(AGORA - timedelta(hours=2)).isoformat())
    assert {c["token_id"] for c in recentes} == {"t-ok", "t-parada"}


def test_filtro_por_usuario(banco: _Fake) -> None:
    r = ci.cadeias_de_instalacao(user_email="outro@x.com")
    assert [c["token_id"] for c in r] == ["t-parada"]


def test_filtro_so_falhas(banco: _Fake) -> None:
    r = ci.cadeias_de_instalacao(apenas_com_falha=True)
    assert {c["desfecho"] for c in r} == {"falhou"}
    assert len(r) == 3


def test_falha_de_banco_devolve_vazio_em_vez_de_levantar(banco: _Fake) -> None:
    """
    A trilha é diagnóstico: ela cair leva junto a única visão do problema que
    se está investigando.
    """
    banco.quebrado = True
    assert ci.cadeias_de_instalacao() == []


# ──────────────────────────────────────────────────────────────────────────
# 4. Rota
# ──────────────────────────────────────────────────────────────────────────

def test_rota_devolve_resumo_e_cadeias(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/cert-installer/trilha?dias=365", headers=_admin())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["resumo"]["total"] == 5
    assert len(d["cadeias"]) == 5


def test_trilha_e_de_admin(client: TestClient, banco: _Fake) -> None:
    """Expõe e-mail, IP e máquina de quem instalou."""
    for papel in ("user", "gestor"):
        h = {"Authorization": f"Bearer {auth.create_access_token({'sub': 'x@x.com', 'role': papel})}"}
        assert client.get("/api/cert-installer/trilha", headers=h).status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 5. A operação saiu do instalador e tem destino no Início
# ──────────────────────────────────────────────────────────────────────────

def _html(rota: str) -> str:
    from fastapi.testclient import TestClient as TC
    import app.config as cfg
    cfg.API_KEY = ""
    from app.main import app
    return TC(app).get(rota).text


def test_instalador_nao_instala_mais() -> None:
    """
    A página virou configuração e diagnóstico. Deixar a tabela de operação lá
    daria dois lugares para fazer a mesma coisa, com regras diferentes — e só
    o Início conhece carteira.
    """
    html = _html("/instalador")
    assert "tblAvailableCerts" not in html
    assert "btnPrepareInstall" not in html
    assert "Para instalar, use o Início" in html


def test_enviar_para_estacao_tem_destino_no_inicio() -> None:
    """
    A capacidade não foi descartada junto com a tela: `prepare` continua
    existindo, agora acionado da seleção do Início.
    """
    html = _html("/")
    assert "btnEnviarEstacao" in html
    assert "/api/cert-installer/prepare" in html


def test_envio_para_estacao_nasce_escondido_e_so_admin_revela() -> None:
    """
    O padrão seguro é não aparecer.

    O alvo é uma máquina que já roda o agente — para o operador, o caminho é
    baixar e executar. Um botão visível que devolve 403 é pior que botão
    nenhum: parece defeito do portal, não falta de permissão.

    Este teste lê o template, então garante a forma, não o comportamento no
    navegador. O que segura de verdade é a barreira de carteira em `prepare`.
    """
    import re

    html = _html("/")
    m = re.search(r'<span id="grupoEstacao"[^>]*style="([^"]*)"', html)
    assert m, "grupo de envio para estação não encontrado"
    assert "display: none" in m.group(1), "tem de nascer oculto"
    assert 'role === "admin" || role === "gestor"' in html, "só esses dois revelam"
    assert 'getElementById("grupoEstacao").style.display = "inline-flex"' in html, (
        "a condição existe mas nada revela o grupo — o botão ficaria oculto "
        "também para admin"
    )


def test_maquina_da_custodia_fica_no_cabecalho() -> None:
    """
    Desde a chave composta, desativar custódia vale para UMA estação. Quem vai
    clicar precisa ver qual ANTES de agir — no rodapé, lia-se depois.
    """
    html = _html("/instalador")
    assert 'id="badgeMaquina"' in html
    assert "valem só para a máquina indicada" in html
