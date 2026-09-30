"""
Alcance de leitura do GESTOR — decisão de produto de 30/09/2026.

O lote 4 da auditoria deu ao gestor a própria carteira mais as carteiras do
setor que lidera. Ao usar o portal, o usuário decidiu o oposto como padrão:

  * administrador: tudo;
  * gestor: tudo POR PADRÃO — e só um administrador pode limitá-lo, ligando
    `users.acesso_restrito`; limitado, ele volta ao alcance do lote 4
    (carteira própria + carteiras do setor que lidera);
  * operador: só o que gestor ou administrador liberar (a carteira), como já era.

A flag mora na conta e só o administrador a escreve: um gestor não pode
limitar nem liberar a si mesmo ou a outro gestor.

Escritos antes da correção; falhavam em 351a0a4.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote4 import (  # noqa: F401 — `banco` é fixture; o resto, helpers
    ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL_OP, GESTOR, _docs, _h, banco,
)
from tests.test_seguranca_lote1 import _Fake

RAIZ = Path(__file__).resolve().parents[1]
CERTS = "/api/certificados?fonte=remoto&todas_filtradas=true"


def _gestor(banco: _Fake) -> dict:
    return next(u for u in banco.tabelas["users"] if u["id"] == "u-lf")


# ── Leitura ────────────────────────────────────────────────────────────────

def test_gestor_sem_restricao_ve_tudo(client: TestClient, banco: _Fake) -> None:
    _gestor(banco)["acesso_restrito"] = False
    r = client.get(CERTS, headers=_h(*GESTOR))
    assert r.status_code == 200, r.text
    assert _docs(r.json()["itens"]) == {DOC_A, DOC_B, DOC_C, DOC_L, ""}, "gestor sem restrição = alcance de admin"


def test_gestor_sem_a_coluna_tambem_ve_tudo(client: TestClient, banco: _Fake) -> None:
    """Banco anterior à migration (a chave nem existe na linha): o padrão é
    o alcance total, não o recorte — é o que o usuário pediu como padrão."""
    _gestor(banco).pop("acesso_restrito", None)
    r = client.get(CERTS, headers=_h(*GESTOR))
    assert _docs(r.json()["itens"]) == {DOC_A, DOC_B, DOC_C, DOC_L, ""}


def test_gestor_restrito_volta_ao_alcance_do_setor(client: TestClient, banco: _Fake) -> None:
    _gestor(banco)["acesso_restrito"] = True
    r = client.get(CERTS, headers=_h(*GESTOR))
    assert _docs(r.json()["itens"]) == {DOC_A, DOC_L}


def test_operador_continua_so_com_a_propria_carteira(client: TestClient, banco: _Fake) -> None:
    """A flag é do gestor. Num operador ela não abre nada."""
    op = next(u for u in banco.tabelas["users"] if u["id"] == "u-fis")
    op["acesso_restrito"] = False
    r = client.get(CERTS, headers=_h(*FISCAL_OP))
    assert _docs(r.json()["itens"]) == {DOC_A}


def test_gestor_restrito_vale_nas_outras_leituras(client: TestClient, banco: _Fake) -> None:
    """O recorte é um só (`_recortar_pela_carteira`); vencidos e histórico
    seguem a mesma flag."""
    _gestor(banco)["acesso_restrito"] = True
    r = client.get("/api/certificados/vencidos?todas_filtradas=true", headers=_h(*GESTOR))
    assert r.status_code == 200, r.text
    assert _docs(r.json()["itens"]) <= {DOC_A, DOC_L}
    _gestor(banco)["acesso_restrito"] = False
    r = client.get("/api/certificados/vencidos?todas_filtradas=true", headers=_h(*GESTOR))
    assert DOC_L in _docs(r.json()["itens"])


# ── Quem liga a flag ───────────────────────────────────────────────────────

def _corpo_edicao(u: dict, **extra) -> dict:
    return {"email": u["email"], "full_name": u["full_name"], "role": u["role"], **extra}


def test_admin_limita_e_libera_um_gestor(client: TestClient, banco: _Fake) -> None:
    g = _gestor(banco)
    r = client.put("/api/users/u-lf", json=_corpo_edicao(g, acesso_restrito=True), headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert g["acesso_restrito"] is True
    r = client.put("/api/users/u-lf", json=_corpo_edicao(g, acesso_restrito=False), headers=_h(*ADMIN))
    assert r.status_code == 200 and g["acesso_restrito"] is False


@pytest.fixture
def gestor_edita_usuarios(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tela de permissões pode dar `usuarios: editar` a gestor; é esse o
    caso em que a guarda da flag importa (sem a permissão, o 403 vem antes)."""
    from app import permissoes

    matriz = {p: {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS} for p in ("gestor", "user")}
    matriz["gestor"]["usuarios"] = permissoes.NIVEL_EDITAR
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)


def test_gestor_nao_mexe_na_propria_restricao_nem_na_de_outro_gestor(
    client: TestClient, banco: _Fake, gestor_edita_usuarios: None
) -> None:
    g = _gestor(banco)
    g["acesso_restrito"] = True
    r = client.put("/api/users/u-lf", json=_corpo_edicao(g, acesso_restrito=False), headers=_h(*GESTOR))
    assert r.status_code == 403, r.text
    assert "administrador" in r.json()["detail"].lower()
    assert g["acesso_restrito"] is True, "a flag não pode ter mudado"
    # Sem mandar a flag, a edição normal do gestor sobre si continua valendo.
    r = client.put("/api/users/u-lf", json=_corpo_edicao(g, full_name="Lider Renomeado"), headers=_h(*GESTOR))
    assert r.status_code == 200, r.text
    assert g["acesso_restrito"] is True


def test_listagem_de_usuarios_traz_a_flag(client: TestClient, banco: _Fake) -> None:
    _gestor(banco)["acesso_restrito"] = True
    r = client.get("/api/users", headers=_h(*ADMIN))
    assert r.status_code == 200
    por_id = {u["id"]: u for u in r.json()}
    assert por_id["u-lf"]["acesso_restrito"] is True
    assert por_id["u-fis"].get("acesso_restrito") in (False, None)


def test_tela_de_usuarios_tem_o_controle_e_a_senha_minima_certa() -> None:
    html = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert 'id="ed-acesso-restrito"' in html
    assert "acesso_restrito" in html
    # Lote 9 subiu o mínimo para 12; a tela ainda dizia 6 e deixava o
    # servidor recusar com 422 depois de a pessoa preencher tudo.
    assert 'minlength="6"' not in html and "mínimo 6" not in html and "< 6" not in html


def test_migration_da_flag_existe() -> None:
    sqls = list((RAIZ / "supabase" / "migrations").glob("*acesso_restrito*.sql"))
    assert sqls and "IF NOT EXISTS" in sqls[0].read_text(encoding="utf-8")


# ── Instalar segue o mesmo alcance da leitura ──────────────────────────────
#
# Antes o gestor lia a carteira do setor (ou tudo) mas instalava só a PRÓPRIA
# carteira: no ANALISESRV um gestor via o acervo e não conseguia instalar.

from tests.test_inicio_selecao import FP_ALHEIO, FP_OK, MAQUINA  # noqa: E402
from tests.test_inicio_selecao import _h as _h_inicio  # noqa: E402
from tests.test_inicio_selecao import banco as banco_inicio  # noqa: E402,F401


def _instalabilidade(client: TestClient, papel: str) -> dict:
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQUINA}", headers=_h_inicio(papel))
    assert r.status_code == 200, r.text
    return r.json()


def test_gestor_limitado_ve_fora_da_carteira_na_instalabilidade(client: TestClient, banco_inicio) -> None:
    users = banco_inicio.tabelas.setdefault("users", [])
    linha = next((u for u in users if u.get("id") == "u-gestor"), None)
    if linha is None:
        linha = {"id": "u-gestor", "email": "gestor@x.com", "role": "gestor", "ativo": True}
        users.append(linha)
    linha["acesso_restrito"] = True
    corpo = _instalabilidade(client, "gestor")
    assert corpo["alcance_total"] is False
    assert FP_ALHEIO not in {fp for fp in corpo["itens"]}, "fora do alcance nem sai (auditoria #30)"
    linha["acesso_restrito"] = False
    corpo = _instalabilidade(client, "gestor")
    assert corpo["alcance_total"] is True
    assert corpo["itens"][FP_ALHEIO]["estado"] == "ok"


# ── Carteiras: o administrador monta a carteira de gestores ─────────────────
#
# A tela escondia todo mundo que não fosse operador; com o gestor limitável,
# o administrador precisa ver os gestores para montar a carteira que vale
# quando ele os limita. "Sem carteira" só é pendência em quem depende dela.

from tests.test_carteiras_ui import _h as _h_cart  # noqa: E402
from tests.test_carteiras_ui import banco as banco_cart  # noqa: E402,F401


def test_lista_de_operadores_traz_gestores_com_a_flag_e_sem_alarme_falso(client: TestClient, banco_cart) -> None:
    r = client.get("/api/carteira/operadores", headers=_h_cart("admin"))
    assert r.status_code == 200, r.text
    por_id = {o["id"]: o for o in r.json()["operadores"]}
    g = por_id["u-gest"]
    assert g["role"] == "gestor" and g["acesso_restrito"] is False
    assert g["depende_de_carteira"] is False and g["sem_carteira"] is False, "gestor sem limitação vê tudo: não é pendência"
    assert por_id["u-op2"]["sem_carteira"] is True, "operador sem carteira continua pendência"

    next(u for u in banco_cart.tabelas["users"] if u["id"] == "u-gest")["acesso_restrito"] = True
    g = {o["id"]: o for o in client.get("/api/carteira/operadores", headers=_h_cart("admin")).json()["operadores"]}["u-gest"]
    assert g["acesso_restrito"] is True and g["depende_de_carteira"] is True and g["sem_carteira"] is True


def test_tela_de_carteiras_mostra_gestores_ao_administrador() -> None:
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert 'if (o.role !== "user") return false;' not in html
    assert 'if (o.role === "admin") return false;' in html
    assert "souAdmin" in html and "Vê tudo" in html
