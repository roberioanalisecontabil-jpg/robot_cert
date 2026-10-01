"""
Carteira por Papel — ADR 0001 (01/10/2026).

Terceira regra em dois dias, e a que ficou. As duas anteriores (flag
`acesso_restrito`; carteira cheia na promoção com origem "regra:gestor") estão
em `docs/adr/0001-carteira-por-papel.md`, com o motivo de cada descarte.

  * Operador: carteira de ATRIBUIÇÕES. Nasce vazia; só alcança o que o Gestor
    do seu departamento ou o administrador atribuiu.
  * Gestor: carteira de EXCEÇÕES. Alcança todo o inventário — inclusive o que
    entrar depois (regra viva) — menos o que o administrador retirou. Só o
    administrador registra Exceções; um Gestor não limita outro.
  * Gestor DERIVA da liderança: entrar na lista de gestores de um departamento
    promove; sair da última rebaixa. Admin pode liderar sem deixar de ser admin.
  * Toda troca de papel esvazia a carteira e derruba as sessões. Desativar
    também esvazia.
  * Departamento é obrigatório no cadastro. Gestor não se escolhe no cadastro.
  * Gestor só atribui o que está no próprio alcance.

Vocabulário em GLOSSARY.md. Escritos antes da implementação; falhavam em b5630bf.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
from tests.test_seguranca_lote1 import _Fake, _usuario
from tests.test_seguranca_lote4 import (  # noqa: F401 — `banco_base` é fixture
    ADMIN, DOC_A, DOC_B, DOC_C, DOC_L, FISCAL, FISCAL_OP, GESTOR, _docs, _h, _item,
)
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
CERTS = "/api/certificados?fonte=remoto&todas_filtradas=true"
TODOS = {DOC_A, DOC_B, DOC_C, DOC_L}
DOC_NOVO = "55555555000195"
CONTABIL = "dep-contabil"


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    """O cenário do lote 4 — u-lf é gestor e lidera FISCAL; u-fis é operador
    do FISCAL com DOC_A; u-sol é operador sem setor — mais o que o modelo novo
    precisa: a tabela de departamentos (cadastro exige) e um segundo gestor,
    para provar que Gestor não limita Gestor."""
    banco_base.tabelas["departamento"] = [{"id": FISCAL, "nome": "Fiscal"}, {"id": CONTABIL, "nome": "Contábil"}]
    banco_base.tabelas["users"].append(_usuario("u-lc", "lider.contabil@x.com", "gestor", departamento_id=CONTABIL))
    banco_base.tabelas["departamento_lider"].append({"departamento_id": CONTABIL, "user_id": "u-lc"})
    banco_base.tabelas["carteira_excecao"] = []
    return banco_base


def _u(banco: _Fake, uid: str) -> dict:
    return next(u for u in banco.tabelas["users"] if u["id"] == uid)


def _atribuicoes(banco: _Fake, uid: str) -> set:
    return {r["documento"] for r in banco.tabelas["carteira"] if r["user_id"] == uid}


def _excecoes(banco: _Fake, uid: str) -> set:
    return {r["documento"] for r in banco.tabelas["carteira_excecao"] if r["user_id"] == uid}


def _ve(client: TestClient, quem, sv: int = 0) -> set:
    """`sv` é a versão de sessão no token: quem acabou de mudar de papel teve
    a sessão derrubada (sessao_versao subiu para 1) e precisa de token novo."""
    from app import auth
    h = {"Authorization": "Bearer " + auth.create_access_token({"sub": quem[0], "role": quem[1], "sv": sv})}
    r = client.get(CERTS, headers=h)
    assert r.status_code == 200, r.text
    return _docs(r.json()["itens"])


# ── 1. A carteira do Gestor é de Exceções ─────────────────────────────────

def test_gestor_ve_tudo_sem_depender_de_carteira(client: TestClient, banco: _Fake) -> None:
    """u-lf tem só DOC_L atribuído à mão (resto do modelo antigo) e lidera um
    setor onde só existe DOC_A. Vê os quatro mesmo assim."""
    assert _ve(client, GESTOR) == TODOS


def test_admin_registra_excecao_e_o_gestor_deixa_de_ver_e_instalar(client: TestClient, banco: _Fake) -> None:
    r = client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "excecoes"
    assert _excecoes(banco, "u-lf") == {DOC_B}
    assert _ve(client, GESTOR) == TODOS - {DOC_B}
    # Instalar é o mesmo direito que ver.
    with pytest.raises(ci.ForaDaCarteira):
        ci.assegurar_carteira("u-lf", "gestor", ["pfx-b"])
    ci.assegurar_carteira("u-lf", "gestor", ["pfx-a"])


def test_cliente_novo_no_inventario_aparece_sozinho_para_o_gestor(client: TestClient, banco: _Fake) -> None:
    """Regra viva: a alternativa descartada (foto na promoção) deixava o
    cliente novo invisível até alguém reaplicar a regra."""
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    banco.tabelas["cert_snapshots"][0]["items"].append(_item(DOC_NOVO, "e" * 64, nome="NOVA"))
    assert _ve(client, GESTOR) == TODOS - {DOC_B} | {DOC_NOVO}
    assert _ve(client, FISCAL_OP) == {DOC_A}, "o operador não ganha nada com isso"


def test_devolver_o_cliente_tira_a_excecao(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    r = client.post("/api/carteira", json={"user_id": "u-lf", "documentos": [DOC_B]}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "excecoes"
    assert _excecoes(banco, "u-lf") == set()
    assert _ve(client, GESTOR) == TODOS


def test_a_tela_mostra_a_carteira_do_gestor_como_inventario_menos_excecoes(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    r = client.get("/api/carteira/u-lf", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tipo"] == "excecoes"
    assert set(d["documentos"]) == TODOS - {DOC_B}
    assert all(i["origem"] == "papel" for i in d["itens"])
    assert [e["documento"] for e in d["excecoes"]] == [DOC_B]
    assert d["excecoes"][0]["registrado_por"] == "admin@x.com"


def test_gestor_nao_registra_excecao_em_gestor_nem_em_si(client: TestClient, banco: _Fake) -> None:
    assert client.delete(f"/api/carteira/u-lc/{DOC_B}", headers=_h(*GESTOR)).status_code == 403
    assert client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*GESTOR)).status_code == 403
    assert client.post("/api/carteira", json={"user_id": "u-lf", "documentos": [DOC_B]}, headers=_h(*GESTOR)).status_code == 403
    assert client.get("/api/carteira/u-lc", headers=_h(*GESTOR)).status_code == 403
    assert _excecoes(banco, "u-lc") == set() and _excecoes(banco, "u-lf") == set()


# ── 2. Gestor só atribui o que alcança ────────────────────────────────────

def test_gestor_so_atribui_o_que_esta_no_proprio_alcance(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    r = client.post("/api/carteira", json={"user_id": "u-fis", "documentos": [DOC_B]}, headers=_h(*GESTOR))
    assert r.status_code == 403, r.text
    assert DOC_B in r.json()["detail"]
    assert _atribuicoes(banco, "u-fis") == {DOC_A}
    assert client.post("/api/carteira", json={"user_id": "u-fis", "documentos": [DOC_C]}, headers=_h(*GESTOR)).status_code == 200
    # O administrador libera o que quiser.
    assert client.post("/api/carteira", json={"user_id": "u-fis", "documentos": [DOC_B]}, headers=_h(*ADMIN)).status_code == 200
    assert _atribuicoes(banco, "u-fis") == {DOC_A, DOC_B, DOC_C}


def test_planilha_do_gestor_respeita_o_alcance_e_so_atribui_a_operador(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    csv = f"email;cnpj\nfis@x.com;{DOC_B}\nfis@x.com;{DOC_C}\nlider.contabil@x.com;{DOC_C}\n"
    r = client.post("/api/carteira/importar", headers=_h(*GESTOR),
                    files={"file": ("c.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["atribuidos"] == 1
    motivos = " ".join(e["motivo"] for e in d["erros"])
    assert "fora do seu alcance" in motivos
    assert "não é Operador" in motivos
    assert _atribuicoes(banco, "u-fis") == {DOC_A, DOC_C}


# ── 3. Gestor deriva da liderança ─────────────────────────────────────────

def test_nomear_gestor_promove_e_esvazia_as_atribuicoes(client: TestClient, banco: _Fake) -> None:
    """u-fis é operador com DOC_A. Entrou na lista de gestores do Fiscal: vira
    gestor, a carteira de Atribuições some (a nova é de Exceções, sem
    nenhuma) e as sessões caem."""
    r = client.put(f"/api/departamentos/{FISCAL}/lideres", json={"lideres": ["u-lf", "u-fis"]}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-fis")["role"] == "gestor"
    assert _atribuicoes(banco, "u-fis") == set()
    assert _u(banco, "u-fis").get("sessao_versao") == 1
    mud = {m["id"]: m for m in r.json()["papeis"]}
    assert mud["u-fis"]["de"] == "user" and mud["u-fis"]["para"] == "gestor"
    assert mud["u-fis"]["atribuicoes"] == 1
    assert "u-lf" not in mud, "quem já era gestor não muda"
    # O token antigo morreu com a troca de papel (401); com o novo, vê tudo.
    assert client.get(CERTS, headers=_h("fis@x.com", "gestor")).status_code == 401
    assert _ve(client, ("fis@x.com", "gestor"), sv=1) == TODOS


def test_tirar_a_ultima_lideranca_rebaixa_e_esvazia(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    r = client.put(f"/api/departamentos/{FISCAL}/lideres", json={"lideres": []}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-lf")["role"] == "user"
    assert _excecoes(banco, "u-lf") == set() and _atribuicoes(banco, "u-lf") == set(), "nada dormente"
    mud = {m["id"]: m for m in r.json()["papeis"]}
    assert mud["u-lf"]["de"] == "gestor" and mud["u-lf"]["para"] == "user"
    assert _ve(client, ("lider@x.com", "user"), sv=1) == set(), "operador sem atribuição não vê nada"


def test_liderar_outro_departamento_mantem_gestor(client: TestClient, banco: _Fake) -> None:
    client.put(f"/api/departamentos/{CONTABIL}/lideres", json={"lideres": ["u-lc", "u-lf"]}, headers=_h(*ADMIN))
    r = client.put(f"/api/departamentos/{FISCAL}/lideres", json={"lideres": []}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-lf")["role"] == "gestor"
    assert r.json()["papeis"] == []


def test_admin_pode_liderar_sem_deixar_de_ser_admin(client: TestClient, banco: _Fake) -> None:
    r = client.put(f"/api/departamentos/{FISCAL}/lideres", json={"lideres": ["u-lf", "u-adm"]}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-adm")["role"] == "admin"
    assert r.json()["papeis"] == []
    assert _ve(client, ADMIN) >= TODOS


def test_apagar_o_departamento_rebaixa_quem_so_liderava_ele(client: TestClient, banco: _Fake) -> None:
    r = client.delete(f"/api/departamentos/{FISCAL}", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-lf")["role"] == "user"
    assert not any(l["departamento_id"] == FISCAL for l in banco.tabelas["departamento_lider"])
    assert {m["id"] for m in r.json()["papeis"]} == {"u-lf"}


# ── 4. Cadastro e edição de usuário ───────────────────────────────────────

def test_cadastro_nao_aceita_gestor_e_exige_departamento(client: TestClient, banco: _Fake) -> None:
    base = {"email": "novo@x.com", "password": "senha-forte-123456", "full_name": "Novo"}
    r = client.post("/api/users", json={**base, "role": "gestor", "departamento_id": FISCAL}, headers=_h(*ADMIN))
    assert r.status_code == 422 and "Departamentos" in r.json()["detail"], r.text
    r = client.post("/api/users", json={**base, "role": "user"}, headers=_h(*ADMIN))
    assert r.status_code == 422 and "departamento" in r.json()["detail"].lower(), r.text
    r = client.post("/api/users", json={**base, "role": "user", "departamento_id": "dep-fantasma"}, headers=_h(*ADMIN))
    assert r.status_code == 422, r.text
    r = client.post("/api/users", json={**base, "role": "user", "departamento_id": FISCAL}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    novo = next(u for u in banco.tabelas["users"] if u["email"] == "novo@x.com")
    assert novo["role"] == "user" and novo["departamento_id"] == FISCAL
    assert _atribuicoes(banco, novo["id"]) == set(), "operador nasce sem nada"


def test_pedir_operador_para_quem_lidera_mantem_gestor_e_nao_mexe_na_carteira(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    lf = _u(banco, "u-lf")
    r = client.put("/api/users/u-lf", json={"email": lf["email"], "full_name": "Renomeado", "role": "user"}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-lf")["role"] == "gestor"
    assert _excecoes(banco, "u-lf") == {DOC_B}, "renomear não apaga a exceção"
    assert "papel" not in r.json()
    r = client.put("/api/users/u-lf", json={"email": lf["email"], "full_name": "X", "role": "gestor"}, headers=_h(*ADMIN))
    assert r.status_code == 422, "gestor não se pede pelo cadastro"


def test_virar_admin_esvazia_a_carteira_e_derruba_a_sessao(client: TestClient, banco: _Fake) -> None:
    fis = _u(banco, "u-fis")
    r = client.put("/api/users/u-fis", json={"email": fis["email"], "full_name": fis["full_name"], "role": "admin"}, headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert _u(banco, "u-fis")["role"] == "admin"
    assert _atribuicoes(banco, "u-fis") == set()
    assert r.json()["papel"]["atribuicoes"] == 1 and r.json()["papel"]["sessoes_derrubadas"] is True
    assert _u(banco, "u-fis")["sessao_versao"] == 1


def test_desativar_apaga_tambem_as_excecoes(client: TestClient, banco: _Fake) -> None:
    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    r = client.post("/api/users/u-lf/deactivate", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["excecoes"] == 1 and r.json()["atribuicoes"] == 1
    assert _excecoes(banco, "u-lf") == set() and _atribuicoes(banco, "u-lf") == set()


# ── 5. A tela de Carteiras ────────────────────────────────────────────────

def test_lista_de_operadores_distingue_os_dois_tipos_de_carteira(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/carteira/operadores", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    por_id = {o["id"]: o for o in r.json()["operadores"]}
    g, op = por_id["u-lf"], por_id["u-fis"]
    assert g["tipo_carteira"] == "excecoes" and g["depende_de_carteira"] is False and g["sem_carteira"] is False
    assert g["documentos"] == 4 and g["textos"]["clientes"] == "todos os clientes"
    assert op["tipo_carteira"] == "atribuicoes" and op["documentos"] == 1
    assert r.json()["resumo"]["operadores"] == 2, "gestores não contam como operador"

    client.delete(f"/api/carteira/u-lf/{DOC_B}", headers=_h(*ADMIN))
    g = {o["id"]: o for o in client.get("/api/carteira/operadores", headers=_h(*ADMIN)).json()["operadores"]}["u-lf"]
    assert g["documentos"] == 3 and g["excecoes"] == 1 and g["textos"]["clientes"] == "todos menos 1 exceção"


def test_gestor_lista_so_os_operadores_dos_seus_departamentos(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/carteira/operadores", headers=_h(*GESTOR))
    assert r.status_code == 200, r.text
    assert {o["id"] for o in r.json()["operadores"]} == {"u-fis"}, "nem ele mesmo, nem outro gestor, nem o solto"


def test_a_rota_da_regra_antiga_sumiu(client: TestClient, banco: _Fake) -> None:
    assert client.post("/api/carteira/regra-gestor/aplicar", headers=_h(*ADMIN)).status_code in (404, 405)
    assert not hasattr(ci, "aplicar_regra_gestor") and not hasattr(ci, "ORIGEM_REGRA_GESTOR")


def test_telas_falam_o_vocabulario_do_glossario() -> None:
    usuarios = (RAIZ / "templates" / "usuarios.html").read_text(encoding="utf-8")
    assert '<option value="gestor" disabled>' in usuarios, "gestor não se escolhe no cadastro"
    assert "Sem departamento" not in usuarios, "departamento é obrigatório"
    assert "Líderes" not in usuarios and ">Gestores<" in usuarios
    assert "departamento%0A" in usuarios, "o modelo da planilha traz a coluna departamento"
    carteiras = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "regra-gestor" not in carteiras and "regra de gestor" not in carteiras.lower()
    assert "Exceções" in carteiras and "pelo papel de gestor" in carteiras


def test_migration_glossario_e_adr_existem() -> None:
    sqls = list((RAIZ / "supabase" / "migrations").glob("*carteira_por_papel*.sql"))
    assert sqls, "falta a migration que cria carteira_excecao e faz a transição"
    sql = sqls[0].read_text(encoding="utf-8")
    assert "carteira_excecao" in sql and "regra:gestor" in sql
    assert (RAIZ / "GLOSSARY.md").exists()
    assert (RAIZ / "docs" / "adr" / "0001-carteira-por-papel.md").exists()
