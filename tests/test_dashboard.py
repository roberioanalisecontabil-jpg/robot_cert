"""Agregações do Dashboard.

Dois assuntos, e o primeiro é o que mais importa.

**1. Truncamento silencioso.** O PostgREST devolve no máximo 1.000 linhas por
requisição e **não avisa** que cortou: a resposta chega bem-formada, só que
incompleta. Descoberto quando a curva de vencimento reportou 1.000 arquivos de
uma tabela com 1.029 — 29 certificados sumindo sem erro nenhum, e o desvio
crescendo junto com o acervo. Os números publicados antes disso estavam errados:
"77 ilegíveis" era na verdade 83.

É a mesma família das outras falhas deste projeto: nada quebra, o número só fica
errado. `test_paginacao_*` é o que guarda isso.

**2. Custo, decidido por medição.** Varrer os 317 snapshots com `items` daria
~160 MB numa função serverless. Só renovações precisa dos itens, e só de dois
snapshots — daí a divisão em dois endpoints. `test_renovacoes_le_apenas_dois_
snapshots` é o teste que impede alguém de "simplificar" isso de volta.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.dashboard as dash


AGORA = datetime.now(timezone.utc)


class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._l, self._b, self._n = linhas, banco, nome
        self._filtros: List[tuple] = []
        self._range: Optional[tuple] = None
        self._limite: Optional[int] = None
        self._ordem: Optional[tuple] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._filtros.append(("eq", c, v))
        return self

    def gte(self, c: str, v: Any) -> "_Query":
        self._filtros.append(("gte", c, v))
        return self

    def lte(self, c: str, v: Any) -> "_Query":
        self._filtros.append(("lte", c, v))
        return self

    def order(self, c: str, desc: bool = False) -> "_Query":
        self._ordem = (c, desc)
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def range(self, i: int, f: int) -> "_Query":
        self._range = (i, f)
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        for op, c, v in self._filtros:
            atual = r.get(c)
            if op == "eq" and atual != v:
                return False
            if op == "gte" and not (atual and str(atual) >= str(v)):
                return False
            if op == "lte" and not (atual and str(atual) <= str(v)):
                return False
        return True

    def execute(self) -> _Resultado:
        self._b.leituras.append(self._n)
        if self._b.quebrado.get(self._n):
            raise RuntimeError(f"banco fora do ar ao ler {self._n}")

        linhas = [dict(r) for r in self._l if self._casa(r)]
        if self._ordem:
            col, desc = self._ordem
            linhas.sort(key=lambda r: r.get(col) or "", reverse=desc)

        # O TETO É O PONTO: o fake corta em 1.000 como o PostgREST corta, e sem
        # avisar. Um fake que devolvesse tudo esconderia exatamente o defeito
        # que estes testes existem para pegar.
        if self._range:
            i, f = self._range
            linhas = linhas[i : min(f + 1, i + dash.LOTE_POSTGREST)]
        elif self._limite is not None:
            linhas = linhas[: min(self._limite, dash.LOTE_POSTGREST)]
        else:
            linhas = linhas[: dash.LOTE_POSTGREST]
        return _Resultado(linhas)


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: Dict[str, bool] = {}
        self.leituras: List[str] = []

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


def _cert(dias_para_vencer: Optional[int], status: str = "ok") -> dict:
    venc = (AGORA + timedelta(days=dias_para_vencer)).isoformat() if dias_para_vencer is not None else None
    return {"vencimento_certificado": venc, "status_ultimo": status}


def _item(doc: str, not_after: str) -> dict:
    return {"documento_numero": doc, "not_after": not_after, "status": "ok",
            "fingerprint_sha256": doc.ljust(64, "0")}


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "cert_history": [
            _cert(-10), _cert(3), _cert(20), _cert(45), _cert(80), _cert(200),
            _cert(None), _cert(5, "erro"), _cert(5, "fora_do_padrao"),
        ],
        "cert_pfx_store": [{"fingerprint": f"f{i}", "machine_id": "SRV"} for i in range(4)],
        "cert_snapshots": [
            {"machine_id": "SRV", "scanned_at": (AGORA - timedelta(hours=2)).isoformat(),
             "items": [_item("111", "2027-01-01"), _item("222", "2026-12-01"), _item("333", "2026-11-01")]},
            {"machine_id": "SRV", "scanned_at": (AGORA - timedelta(days=45)).isoformat(),
             "items": [_item("111", "2026-06-01"), _item("222", "2026-12-01"), _item("444", "2026-10-01")]},
        ],
        "sent_alerts": [
            {"tipo_alerta": "expiring:30", "sent_at": AGORA.isoformat(), "destinatario": "a@x.com"},
            {"tipo_alerta": "expiring:30", "sent_at": AGORA.isoformat(), "destinatario": "b@x.com"},
        ],
        "users": [
            {"role": "admin", "ativo": True}, {"role": "user", "ativo": True},
            {"role": "user", "ativo": True}, {"role": "user", "ativo": False},
        ],
        "carteira": [{"user_id": "u-1"}],
        "install_log": [],
    })
    monkeypatch.setattr(dash, "_supabase", lambda: fake)
    import app.cert_installer as ci
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    return fake


def _admin() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'a@x.com', 'role': 'admin'})}"}


# ──────────────────────────────────────────────────────────────────────────
# 1. Truncamento silencioso — o defeito que a medição achou
# ──────────────────────────────────────────────────────────────────────────

def test_paginacao_le_alem_do_teto_do_postgrest(banco: _Fake) -> None:
    """
    1.500 linhas têm de virar 1.500, não 1.000.

    Sem paginação a resposta chega bem-formada e incompleta: nenhum erro, só um
    número menor. Foi assim que a curva de vencimento perdeu 29 dos 1.029
    arquivos — e o desvio cresce junto com o acervo.
    """
    banco.tabelas["cert_history"] = [_cert(50) for _ in range(1500)]
    assert dash.painel_acervo()["total"] == 1500


def test_paginacao_para_no_fim_e_nao_repete(banco: _Fake) -> None:
    """Exatamente 1.000 é o caso de borda: a página cheia sugere que há mais."""
    banco.tabelas["cert_history"] = [_cert(50) for _ in range(1000)]
    assert dash.painel_acervo()["total"] == 1000


def test_paginacao_alcanca_o_cofre_tambem(banco: _Fake) -> None:
    """O cofre passou de 33 para 489 numa tarde; passar de mil é questão de tempo."""
    banco.tabelas["cert_pfx_store"] = [
        {"fingerprint": f"f{i}", "machine_id": "SRV"} for i in range(1200)
    ]
    assert dash.painel_cofre()["guardados"] == 1200


# ──────────────────────────────────────────────────────────────────────────
# 2. Custo: renovações não pode voltar a varrer tudo
# ──────────────────────────────────────────────────────────────────────────

def test_renovacoes_le_apenas_dois_snapshots(banco: _Fake) -> None:
    """
    O teste que impede a "simplificação" cara.

    Varrer os 317 snapshots com `items` daria ~160 MB numa função serverless.
    Renovação é a diferença entre dois inventários, e só precisa de dois.
    """
    banco.leituras.clear()
    dash.painel_renovacoes(dias=30, machine_id="SRV")
    assert banco.leituras.count("cert_snapshots") == 2


def test_visao_geral_nao_toca_em_renovacoes(banco: _Fake) -> None:
    """
    Os painéis baratos não podem ficar reféns do caro.

    Se `visao_geral` chamasse renovações, a tela inteira passaria a esperar o
    painel menos urgente — que é exatamente o que a divisão evita.
    """
    v = dash.visao_geral(30)
    assert "renovacoes" not in v


# ──────────────────────────────────────────────────────────────────────────
# 3. Renovações: o que a comparação diz
# ──────────────────────────────────────────────────────────────────────────

def test_renovado_e_documento_com_validade_que_avancou(banco: _Fake) -> None:
    """`111` foi de 2026-06 para 2027-01. `222` não mudou."""
    r = dash.painel_renovacoes(dias=30, machine_id="SRV")
    assert r["renovados"] == 1
    assert r["amostra_renovados"] == ["111"]


def test_novos_e_saidas_sao_contados_separadamente(banco: _Fake) -> None:
    """
    `333` apareceu, `444` saiu. Saída é fluxo normal — o agente move vencidos
    para a pasta de expirados —, então somá-la às renovações mentiria.
    """
    r = dash.painel_renovacoes(dias=30, machine_id="SRV")
    assert r["novos"] == 1
    assert r["sairam"] == 1


def test_referencia_real_vai_na_resposta(banco: _Fake) -> None:
    """
    As varreduras têm lacunas: pedir 30 dias pode comparar com uma de 45 dias
    atrás. Apresentar isso como "últimos 30 dias" seria mentira, então a data
    usada acompanha o número.
    """
    r = dash.painel_renovacoes(dias=30, machine_id="SRV")
    assert r["dias_pedidos"] == 30
    assert r["referencia"] == banco.tabelas["cert_snapshots"][1]["scanned_at"]


def test_sem_snapshot_anterior_diz_isso_em_vez_de_zerar(banco: _Fake) -> None:
    """
    Zero renovações e "não há com o que comparar" são coisas diferentes.
    Devolver 0 faria alguém concluir que ninguém renovou nada.
    """
    r = dash.painel_renovacoes(dias=365, machine_id="SRV")
    assert r.get("sem_referencia") is True
    assert "renovados" not in r


# ──────────────────────────────────────────────────────────────────────────
# 4. Painéis
# ──────────────────────────────────────────────────────────────────────────

def test_curva_de_vencimento_separa_as_faixas(banco: _Fake) -> None:
    v = dash.painel_acervo()["vencimento"]
    assert v["vencido"] == 1
    assert v["ate_7_dias"] == 3      # 3 dias + os dois com status ruim (5 dias)
    assert v["ate_30_dias"] == 1
    assert v["ate_60_dias"] == 1
    assert v["ate_90_dias"] == 1
    assert v["acima_de_90"] == 1


def test_ilegiveis_sao_somados(banco: _Fake) -> None:
    """
    Separados, "erro" e "fora do padrão" parecem ruído; juntos, são arquivos
    que ninguém consegue instalar pelo portal.
    """
    a = dash.painel_acervo()
    assert a["ilegiveis"] == 2
    assert a["sem_data_de_vencimento"] == 1


def test_cobertura_do_cofre(banco: _Fake) -> None:
    c = dash.painel_cofre()
    assert c["guardados"] == 4
    assert c["inventario"] == 3
    assert c["por_maquina"] == {"SRV": 4}


def test_agente_atrasado_e_sinalizado(banco: _Fake) -> None:
    """O agente roda a cada 24h; passar de 36h não é atraso de relógio."""
    a = dash.painel_agente(90)
    por_maq = {m["machine_id"]: m for m in a["maquinas"]}
    assert por_maq["SRV"]["atrasado"] is False

    banco.tabelas["cert_snapshots"][0]["scanned_at"] = (AGORA - timedelta(hours=50)).isoformat()
    a = dash.painel_agente(90)
    assert {m["machine_id"]: m for m in a["maquinas"]}["SRV"]["atrasado"] is True


def test_acesso_conta_operador_sem_carteira(banco: _Fake) -> None:
    """
    Operador sem carteira não instala nada — correto, mas é o que trava a
    primeira pessoa que abre a tela. Melhor ver o número que receber o chamado.
    """
    a = dash.painel_acesso()
    assert a["usuarios_ativos"] == 3, "o desativado não conta"
    assert a["operadores"] == 2
    assert a["operadores_com_carteira"] == 1


# ──────────────────────────────────────────────────────────────────────────
# 5. Isolamento de falhas
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tabela,painel", [
    ("cert_history", "acervo"),
    ("cert_pfx_store", "cofre"),
    ("sent_alerts", "alertas"),
    ("users", "acesso"),
])
def test_painel_quebrado_nao_derruba_os_outros(banco: _Fake, tabela: str, painel: str) -> None:
    """
    Dashboard que some inteiro por causa de uma tabela instável é pior que
    dashboard com um buraco declarado.
    """
    banco.quebrado[tabela] = True
    v = dash.visao_geral(30)
    assert "erro" in v[painel]
    outros = [k for k in ("acervo", "cofre", "alertas", "acesso", "agente") if k != painel]
    assert any("erro" not in v[o] for o in outros), "os demais painéis têm de sobreviver"


# ──────────────────────────────────────────────────────────────────────────
# 6. Rotas
# ──────────────────────────────────────────────────────────────────────────

def test_rotas_do_dashboard_sao_de_admin(client: TestClient, banco: _Fake) -> None:
    """Expõe cobertura do cofre, saúde do agente e quem tem acesso a quê."""
    for papel in ("user", "gestor"):
        h = {"Authorization": f"Bearer {auth.create_access_token({'sub': 'x@x.com', 'role': papel})}"}
        assert client.get("/api/dashboard", headers=h).status_code == 403
        assert client.get("/api/dashboard/renovacoes", headers=h).status_code == 403


def test_rota_visao_geral(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/dashboard?dias=30", headers=_admin())
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"instalacao", "cofre", "agente", "acervo", "alertas", "acesso"}


def test_rota_renovacoes(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/dashboard/renovacoes?dias=30&machine_id=SRV", headers=_admin())
    assert r.status_code == 200, r.text
    assert r.json()["renovados"] == 1


def test_pagina_do_dashboard_responde(client: TestClient) -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "painelRenovacoes" in r.text
