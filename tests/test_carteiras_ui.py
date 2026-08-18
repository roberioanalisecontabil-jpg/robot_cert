"""A tela do gestor: montar carteira e ver o que a pessoa fez.

Etapa 5. O modelo já existia desde a 2c — o que faltava era interface: até aqui
só dava para atribuir carteira por chamada de API, e os 7 operadores do portal
estavam com carteira vazia, ou seja, sem conseguir instalar nada.

Dois testes daqui valem mais que os outros:

- `test_rotas_fixas_vem_antes_do_path_param` guarda uma armadilha de roteamento:
  `/api/carteira/operadores` e `/api/carteira/{user_id}` competem pelo mesmo
  caminho. Se a ordem inverter, "operadores" vira um `user_id` — a rota
  responde 200 com carteira vazia, **sem erro nenhum**, e a tela mostra uma
  lista em branco que parece "não há operadores".

- `test_operadores_nao_vaza_hash_de_senha`: a rota existe justamente para o
  gestor **não** usar `/api/users`, que é de admin e devolve a linha inteira.
  Uma rota nova que devolva `select("*")` por conveniência desfaz isso.
"""

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
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._l, self._b, self._n = linhas, banco, nome
        self._filtros: List[tuple] = []
        self._payload: Any = None
        self._op = "select"
        self._limite: Optional[int] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def upsert(self, rows: Any, on_conflict: Optional[str] = None) -> "_Query":
        self._op, self._payload = "upsert", rows
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._filtros.append((c, v))
        return self

    def order(self, _c: str, desc: bool = False) -> "_Query":
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._filtros)

    def execute(self) -> _Resultado:
        if self._b.quebrado.get(self._n):
            raise RuntimeError("banco fora do ar")
        if self._op == "upsert":
            linhas = self._payload if isinstance(self._payload, list) else [self._payload]
            self._l.extend(dict(x) for x in linhas)
            return _Resultado([dict(x) for x in linhas])
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Resultado(fora)
        out = [dict(r) for r in self._l if self._casa(r)]
        if self._limite is not None:
            out = out[: self._limite]
        return _Resultado(out)


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


DOC_ACME = "33706943000193"
DOC_BOI = "55993256000139"
DOC_SUMIU = "11111111111111"


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-op1", "email": "ana@x.com", "full_name": "Ana Silva", "role": "user",
             "ativo": True, "gestor_id": "u-gest", "departamento_id": "dep-1", "password_hash": "NAO PODE VAZAR"},
            {"id": "u-op2", "email": "bruno@x.com", "full_name": "Bruno", "role": "user",
             "ativo": True, "gestor_id": None, "departamento_id": "dep-1", "password_hash": "NAO PODE VAZAR"},
            {"id": "u-gest", "email": "gestor@x.com", "full_name": "Gestor", "role": "gestor",
             "ativo": True, "gestor_id": None, "departamento_id": "dep-1", "password_hash": "NAO PODE VAZAR"},
            # As contas que `_h("admin")` e `_h("user")` apresentam. Desde 16/08
            # o `require_auth` relê a conta a cada requisição, então um token
            # cujo `sub` não existe no banco é 401 — sessão de conta excluída.
            # Sem estas linhas, `test_operadores_e_de_admin_ou_gestor` mediria a
            # recusa errada: 401 por identidade desconhecida em vez do 403 por
            # papel insuficiente, que é o que ele existe para provar.
            {"id": "u-adm", "email": "admin@x.com", "full_name": "Admin", "role": "admin",
             "ativo": True, "gestor_id": None, "password_hash": "NAO PODE VAZAR"},
            {"id": "u-op3", "email": "user@x.com", "full_name": "Operador", "role": "user",
             "ativo": True, "gestor_id": None, "departamento_id": "dep-1", "password_hash": "NAO PODE VAZAR"},
        ],
        # Desde 18/08 o alcance vem da liderança, não do papel: o gestor só
        # enxerga e mexe em quem está num setor que ele lidera. Sem estas duas
        # tabelas ele não alcança ninguém, e estes testes mediriam "gestor sem
        # setor" em vez da tela.
        "departamento": [{"id": "dep-1", "nome": "Fiscal"}],
        "departamento_lider": [{"departamento_id": "dep-1", "user_id": "u-gest"}],
        "carteira": [
            {"user_id": "u-op1", "documento": DOC_ACME,
             "atribuido_por_email": "gestor@x.com", "atribuido_em": "2026-08-15T10:00:00Z"},
            {"user_id": "u-op1", "documento": DOC_SUMIU,
             "atribuido_por_email": "chefe@x.com", "atribuido_em": "2026-07-01T10:00:00Z"},
        ],
        "cert_snapshots": [
            {"machine_id": "SRV", "scanned_at": "2026-08-15T14:00:00Z", "items": [
                {"documento_numero": DOC_ACME, "nome": "ACME ASSESSORIA CONTABIL LTDA"},
                {"documento_numero": DOC_BOI, "nome": "BOI PRIME DUVALE LTDA"},
                {"documento_numero": DOC_ACME, "nome": "ACME"},   # nome curto, deve perder
            ]},
        ],
    })
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    monkeypatch.setattr(m, "_resolve_user_id", lambda email: "u-" + email.split("@")[0])
    return fake


def _h(papel: str) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': f'{papel}@x.com', 'role': papel})}"}


# ──────────────────────────────────────────────────────────────────────────
# 1. A armadilha de roteamento
# ──────────────────────────────────────────────────────────────────────────

def test_rotas_fixas_vem_antes_do_path_param() -> None:
    """
    `/api/carteira/operadores` compete com `/api/carteira/{user_id}`.

    Se a ordem inverter, "operadores" passa a ser lido como um `user_id`: a
    rota responde **200 com carteira vazia**, sem erro nenhum, e a tela mostra
    uma lista em branco que parece "não há operadores cadastrados". É falha
    silenciosa da mesma família das outras deste projeto.
    """
    from app.main import app

    caminhos = [r.path for r in app.routes if getattr(r, "path", "").startswith("/api/carteira")]
    assert caminhos.index("/api/carteira/operadores") < caminhos.index("/api/carteira/{user_id}")
    assert caminhos.index("/api/carteira/documentos") < caminhos.index("/api/carteira/{user_id}")


def test_rotas_fixas_respondem_o_que_devem(client: TestClient, banco: _Fake) -> None:
    """Contraprova em runtime da ordem verificada acima."""
    r = client.get("/api/carteira/operadores", headers=_h("gestor"))
    assert r.status_code == 200
    assert "operadores" in r.json(), "caiu no handler do path param"

    r = client.get("/api/carteira/documentos", headers=_h("gestor"))
    assert "documentos" in r.json() and "total" in r.json()


# ──────────────────────────────────────────────────────────────────────────
# 2. A rota de operadores existe para o gestor NÃO usar /api/users
# ──────────────────────────────────────────────────────────────────────────

def test_operadores_nao_vaza_hash_de_senha(client: TestClient, banco: _Fake) -> None:
    """
    O gestor monta carteira sem administrar contas, e não tem por que ver o
    hash de senha de ninguém. `/api/users` devolve a linha inteira e é de
    admin; esta rota existe justamente para não precisar dela.

    **O que segura é a resposta montada campo a campo**, não o `select` — este
    é defesa em profundidade, e o teste de mutação mostrou isso: trocar por
    `select("*")` não vaza nada, mas devolver as linhas cruas vaza tudo. A
    regressão a temer é alguém "simplificar" o `return` para `us`.
    """
    r = client.get("/api/carteira/operadores", headers=_h("gestor"))
    assert "NAO PODE VAZAR" not in r.text
    assert "password_hash" not in r.text


def test_operadores_traz_a_contagem_de_carteira(client: TestClient, banco: _Fake) -> None:
    """
    A contagem é o que responde "quem ainda não pode instalar nada" sem exigir
    um clique por pessoa.
    """
    ops = {o["email"]: o for o in client.get("/api/carteira/operadores", headers=_h("gestor")).json()["operadores"]}
    assert ops["ana@x.com"]["documentos"] == 2
    assert ops["bruno@x.com"]["documentos"] == 0


def test_operadores_e_de_admin_ou_gestor(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/carteira/operadores", headers=_h("user"))
    assert r.status_code == 403
    assert client.get("/api/carteira/operadores", headers=_h("admin")).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 3. Busca de documentos
# ──────────────────────────────────────────────────────────────────────────

def test_busca_por_nome(client: TestClient, banco: _Fake) -> None:
    d = client.get("/api/carteira/documentos?q=boi", headers=_h("gestor")).json()
    assert [x["documento"] for x in d["documentos"]] == [DOC_BOI]


def test_busca_por_numero_ignora_pontuacao(client: TestClient, banco: _Fake) -> None:
    """
    Ninguém digita CNPJ sem pontuação. Exigir dígitos puros faria a busca
    parecer quebrada para quem copia e cola do sistema contábil.
    """
    d = client.get("/api/carteira/documentos?q=33.706.943", headers=_h("gestor")).json()
    assert [x["documento"] for x in d["documentos"]] == [DOC_ACME]


def test_universo_traz_o_nome_mais_completo(banco: _Fake) -> None:
    """
    O mesmo documento aparece com nomes diferentes no inventário. Fica o mais
    longo, que costuma ser a razão social — é o que a pessoa reconhece.
    """
    por_doc = {d["documento"]: d["nome"] for d in ci.universo_de_documentos()}
    assert por_doc[DOC_ACME] == "ACME ASSESSORIA CONTABIL LTDA"


def test_busca_diz_quantos_ficaram_de_fora(client: TestClient, banco: _Fake) -> None:
    """
    Sem o total, uma lista cortada parece a lista inteira — e o gestor conclui
    que o cliente não existe quando ele só não coube.
    """
    d = client.get("/api/carteira/documentos?limite=1", headers=_h("gestor")).json()
    assert d["total"] == 2
    assert len(d["documentos"]) == 1


# ──────────────────────────────────────────────────────────────────────────
# 4. A carteira com trilha
# ──────────────────────────────────────────────────────────────────────────

def test_carteira_mostra_quem_liberou_e_quando(client: TestClient, banco: _Fake) -> None:
    """
    Com o gestor podendo atribuir qualquer cliente do acervo, quem concedeu o
    quê é a única forma de reconstruir o que houve se uma conta for
    comprometida. Guardar sem mostrar tornaria a trilha decorativa.
    """
    itens = {i["documento"]: i for i in client.get(
        f"/api/carteira/u-op1", headers=_h("gestor")).json()["itens"]}
    assert itens[DOC_ACME]["atribuido_por"] == "gestor@x.com"
    assert itens[DOC_ACME]["atribuido_em"].startswith("2026-08-15")


def test_documento_fora_do_inventario_continua_na_carteira(
    client: TestClient, banco: _Fake
) -> None:
    """
    A atribuição é uma decisão. Sumir com ela quando o certificado sai do
    inventário esconderia que a pessoa volta a ter acesso se ele reaparecer —
    e o certificado reaparece: o agente move vencidos e pode movê-los de volta.
    """
    itens = {i["documento"]: i for i in client.get(
        f"/api/carteira/u-op1", headers=_h("gestor")).json()["itens"]}
    assert DOC_SUMIU in itens
    assert itens[DOC_SUMIU]["no_inventario"] is False
    assert itens[DOC_ACME]["no_inventario"] is True


def test_carteira_ordena_do_mais_recente(client: TestClient, banco: _Fake) -> None:
    itens = client.get(f"/api/carteira/u-op1", headers=_h("gestor")).json()["itens"]
    assert [i["documento"] for i in itens] == [DOC_ACME, DOC_SUMIU]


# ──────────────────────────────────────────────────────────────────────────
# 5. A tela
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def html() -> str:
    from fastapi.testclient import TestClient as TC
    import app.config as cfg
    cfg.API_KEY = ""
    from app.main import app
    return TC(app).get("/carteiras").text


def test_pagina_responde(html: str) -> None:
    assert "listaOperadores" in html
    assert "buscaDoc" in html


def test_menu_revela_carteiras_para_gestor(html: str) -> None:
    """
    Montar carteira é a função do gestor. Se só admin revelasse o item, o
    gestor teria a permissão e nenhum caminho até ela.
    """
    assert 'id="nav-carteiras"' in html
    assert '_papel === "gestor"' in html


def test_estado_vazio_diz_a_consequencia(html: str) -> None:
    """
    Carteira vazia é o comportamento correto — o acesso fecha por padrão —, mas
    é também o que trava a pessoa sem que ninguém saiba por quê. A tela precisa
    dizer isso, não só mostrar uma lista em branco.
    """
    assert "não consegue instalar nenhum certificado" in html


def test_remover_pede_confirmacao(html: str) -> None:
    """Tirar acesso de alguém no meio de uma instalação merece confirmação."""
    assert "Remover este cliente da carteira?" in html
