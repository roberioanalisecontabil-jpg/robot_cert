"""Seleção de certificados no Início e o estado que a sustenta.

A tela lista o inventário do agente — 560 itens no ANALISESRV — e só parte dele
é instalável por quem está olhando. Uma seleção ingênua deixaria marcar tudo e
falhar no download, **na máquina do usuário**, longe da causa.

`/api/cert-installer/instalabilidade` resolve isso numa chamada, cruzando as
quatro fontes: inventário, bloqueios, cofre e carteira. Não é barreira — a
barreira é `_validar_pedido_de_instalacao`, na emissão do token. Isto existe
para a tela não convidar o usuário a um erro que o servidor vai recusar.

O motivo importa tanto quanto o estado. Checkbox desabilitado sem explicação
parece defeito da tela; com o motivo, o usuário sabe se espera (o agente ainda
não enviou) ou se pede acesso (fora da carteira).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci
import app.main as m


class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, tabela: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._t, self._b, self._n = tabela, banco, nome
        self._filtros: List[tuple] = []
        self._ordem: Optional[tuple] = None
        self._limite: Optional[int] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._filtros.append((c, v))
        return self

    def in_(self, c: str, vs: List[Any]) -> "_Query":
        self._filtros.append((c, vs))
        return self

    def order(self, c: str, desc: bool = False) -> "_Query":
        self._ordem = (c, desc)
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def execute(self) -> _Resultado:
        if self._b.quebrado.get(self._n):
            raise RuntimeError(f"banco fora do ar ao ler {self._n}")
        linhas = [
            dict(r)
            for r in self._t
            if all(
                (r.get(c) in v if isinstance(v, list) else r.get(c) == v)
                for c, v in self._filtros
            )
        ]
        if self._ordem:
            col, desc = self._ordem
            linhas.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limite is not None:
            linhas = linhas[: self._limite]
        return _Resultado(linhas)


class _Fake:
    def __init__(self) -> None:
        self.tabelas: Dict[str, List[Dict[str, Any]]] = {}
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        self.tabelas.setdefault(nome, [])
        return _Query(self.tabelas[nome], self, nome)


MAQUINA = "ANALISESRV"
DOC_MEU, DOC_ALHEIO = "33706943000193", "55993256000139"

FP_OK = "a" * 64            # na carteira, no cofre
FP_ALHEIO = "b" * 64        # no cofre, fora da carteira
FP_BLOQUEADO = "c" * 64     # custódia desativada pelo admin
FP_VENCIDO = "d" * 64
FP_ILEGIVEL = "e" * 64
FP_NAO_ENVIADO = "f" * 64   # permitido, mas o agente ainda não subiu


def _item(fp: str, doc: Optional[str], status: str = "ok") -> dict:
    return {"fingerprint_sha256": fp, "documento_numero": doc, "status": status}


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake()
    fake.tabelas["cert_snapshots"] = [
        {
            "machine_id": MAQUINA,
            "scanned_at": "2026-08-15T14:00:00Z",
            "items": [
                _item(FP_OK, DOC_MEU),
                _item(FP_ALHEIO, DOC_ALHEIO),
                _item(FP_BLOQUEADO, DOC_MEU),
                _item(FP_VENCIDO, DOC_MEU, "expirado"),
                _item(FP_ILEGIVEL, None, "erro"),
                _item(FP_NAO_ENVIADO, DOC_MEU),
            ],
        }
    ]
    fake.tabelas["cert_vault_bloqueio"] = [
        {"machine_id": MAQUINA, "fingerprint": FP_BLOQUEADO}
    ]
    fake.tabelas["cert_pfx_store"] = [
        {"id": "id-ok", "fingerprint": FP_OK, "machine_id": MAQUINA, "documento": DOC_MEU,
         "uploaded_at": "2026-08-15T14:05:00Z"},
        {"id": "id-alheio", "fingerprint": FP_ALHEIO, "machine_id": MAQUINA, "documento": DOC_ALHEIO,
         "uploaded_at": "2026-08-15T14:05:00Z"},
        {"id": "id-bloq", "fingerprint": FP_BLOQUEADO, "machine_id": MAQUINA, "documento": DOC_MEU,
         "uploaded_at": "2026-08-15T14:05:00Z"},
    ]
    fake.tabelas["carteira"] = [
        {"user_id": "u-operador", "documento": DOC_MEU},
    ]
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    monkeypatch.setattr(m, "_resolve_user_id", lambda email: "u-" + email.split("@")[0])
    return fake


def _h(papel: str, email: Optional[str] = None) -> dict:
    email = email or f"{papel}@x.com"
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': email, 'role': papel})}"}


def _estados(client: TestClient, headers: dict) -> Dict[str, str]:
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQUINA}", headers=headers)
    assert r.status_code == 200, r.text
    return {fp: v["estado"] for fp, v in r.json()["itens"].items()}


# ──────────────────────────────────────────────────────────────────────────
# 1. Cada "não" tem o motivo certo
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fp,esperado", [
    (FP_OK, "ok"),
    (FP_ALHEIO, "fora_da_carteira"),
    (FP_BLOQUEADO, "bloqueado"),
    (FP_VENCIDO, "vencido"),
    (FP_ILEGIVEL, "ilegivel"),
    (FP_NAO_ENVIADO, "nao_enviado"),
])
def test_estado_por_certificado_para_o_operador(
    client: TestClient, banco: _Fake, fp: str, esperado: str
) -> None:
    assert _estados(client, _h("user", "operador@x.com"))[fp] == esperado


def test_vencido_ganha_do_motivo_da_carteira(client: TestClient, banco: _Fake) -> None:
    """
    A ordem de avaliação importa: o motivo mostrado tem de ser o mais
    fundamental. Dizer "fora da sua carteira" sobre um certificado vencido faria
    o operador pedir um acesso que não resolveria nada.
    """
    banco.tabelas["carteira"] = []   # nada na carteira: tudo estaria "fora"
    estados = _estados(client, _h("user", "operador@x.com"))
    assert estados[FP_VENCIDO] == "vencido"
    assert estados[FP_ILEGIVEL] == "ilegivel"
    assert estados[FP_ALHEIO] == "fora_da_carteira"


def test_nao_enviado_e_distinto_de_bloqueado(client: TestClient, banco: _Fake) -> None:
    """
    Um é transitório (some no próximo ciclo do agente), o outro é decisão do
    admin. Colapsar os dois num "indisponível" faria o usuário esperar por algo
    que não vai chegar, ou pedir liberação do que já está liberado.
    """
    estados = _estados(client, _h("user", "operador@x.com"))
    assert estados[FP_NAO_ENVIADO] != estados[FP_BLOQUEADO]


def test_id_do_cofre_acompanha_o_estado_ok(client: TestClient, banco: _Fake) -> None:
    """Sem o id, a tela não teria o que mandar para `/prepare`."""
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQUINA}",
                   headers=_h("user", "operador@x.com"))
    itens = r.json()["itens"]
    assert itens[FP_OK]["id"] == "id-ok"
    assert itens[FP_NAO_ENVIADO]["id"] is None


# ──────────────────────────────────────────────────────────────────────────
# 2. Alcance total
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("papel", ["admin", "gestor"])
def test_admin_e_gestor_nao_veem_fora_da_carteira(
    client: TestClient, banco: _Fake, papel: str
) -> None:
    """
    **Só o admin, desde 18/08/2026** — quando o departamento passou a recortar
    o alcance do gestor.

    O gestor perdeu o alcance total e passou a ver "fora da carteira" como
    qualquer operador. É a contrapartida honesta do recorte: se ele atribui só
    dentro do setor mas continua instalando tudo, o recorte não vale nada.
    """
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQUINA}", headers=_h(papel))
    corpo = r.json()
    estados = {fp: v["estado"] for fp, v in corpo["itens"].items()}

    if papel == "admin":
        assert corpo["alcance_total"] is True
        assert "fora_da_carteira" not in estados.values()
        assert estados[FP_ALHEIO] == "ok"
    else:
        assert corpo["alcance_total"] is False, "gestor voltou a ter alcance total"
        assert estados[FP_ALHEIO] == "fora_da_carteira"


def test_operador_nao_tem_alcance_total(client: TestClient, banco: _Fake) -> None:
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQUINA}",
                   headers=_h("user", "operador@x.com"))
    assert r.json()["alcance_total"] is False


# ──────────────────────────────────────────────────────────────────────────
# 3. Falha fechada — a tela não pode liberar quando não sabe
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tabela", ["cert_snapshots", "cert_vault_bloqueio", "carteira"])
def test_falha_de_banco_devolve_503(client: TestClient, banco: _Fake, tabela: str) -> None:
    """
    Uma tela que, na dúvida, marca tudo como instalável convida ao erro que o
    servidor vai recusar depois — e o usuário só descobre no download.
    """
    banco.quebrado[tabela] = True
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQUINA}",
                   headers=_h("user", "operador@x.com"))
    assert r.status_code == 503, r.text


def test_machine_id_e_obrigatorio(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/cert-installer/instalabilidade", headers=_h("admin"))
    assert r.status_code == 422


def test_maquina_sem_varredura_devolve_vazio_e_nao_erro(
    client: TestClient, banco: _Fake
) -> None:
    r = client.get("/api/cert-installer/instalabilidade?machine_id=NAO-EXISTE",
                   headers=_h("admin"))
    assert r.status_code == 200, r.text
    assert r.json()["itens"] == {}


# ──────────────────────────────────────────────────────────────────────────
# 4. A tela
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def html_inicio() -> str:
    from fastapi.testclient import TestClient as TC
    import app.config as cfg
    cfg.API_KEY = ""
    from app.main import app
    return TC(app).get("/").text


def test_teto_da_tela_vem_do_servidor(html_inicio: str) -> None:
    """
    O número existe num lugar só.

    Repetido na tela, ele divergiria da rota na primeira vez que alguém mudasse
    o limite — e o sintoma seria o pior possível: a tela deixa marcar 60, o
    usuário monta a seleção, e o download falha com 422 no fim.
    """
    from app.main import MAX_CERTIFICADOS_POR_TOKEN

    assert f"const MAX_CERTIFICADOS = {MAX_CERTIFICADOS_POR_TOKEN};" in html_inicio


def test_selecao_nao_vive_no_dom(html_inicio: str) -> None:
    """
    A tabela pagina no servidor e o tbody é reconstruído a cada página. Se a
    seleção fossem os próprios checkboxes, marcar três na página 1 e ir para a 2
    apagaria tudo — sem aviso, e o usuário só notaria pelo instalador incompleto.
    """
    assert "const _selecao = new Map();" in html_inicio
    assert "sincronizarCheckboxesDaPagina" in html_inicio


def test_tela_explica_cada_indisponibilidade(html_inicio: str) -> None:
    """Checkbox desabilitado sem motivo parece defeito da tela."""
    for estado in ("vencido", "ilegivel", "bloqueado", "fora_da_carteira", "nao_enviado"):
        assert f"{estado}:" in html_inicio, f"sem mensagem para {estado}"


def test_barra_de_selecao_nao_e_fixa_na_janela(html_inicio: str) -> None:
    """
    `position: fixed` taparia a paginação no celular — justamente o controle
    necessário para continuar escolhendo. A barra é sticky dentro do fluxo.

    Em 18/08 a regra migrou do <style> do Início para o style.css, porque a
    aba Seleção do Acompanhamento passou a usar a mesma barra — o invariante
    é o mesmo, o endereço mudou.
    """
    css = (Path(__file__).resolve().parent.parent / "static" / "style.css").read_text(
        encoding="utf-8"
    )
    m = re.search(r"\.barra-selecao\s*\{([^}]*)\}", css)
    assert m, ".barra-selecao não encontrada no style.css"
    assert "position: sticky;" in m.group(1)
    assert "position: fixed" not in m.group(1)
    assert "id=\"barraSelecao\"" in html_inicio


def test_selecionar_todos_alcanca_so_a_pagina_visivel(html_inicio: str) -> None:
    """
    Marcar 489 de uma vez com teto de 50 seria armadilha, não atalho: o usuário
    clicaria uma vez e receberia um erro de limite sem entender o que fez.
    """
    assert '#tbody .chk-cert:not([disabled])' in html_inicio
