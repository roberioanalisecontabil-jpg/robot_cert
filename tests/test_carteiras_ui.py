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

import io
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

    Em 18/08 a revelação saiu das telas para initSidebarPorPapel (ui-common.js):
    era copiada por template e as cópias divergiram — 8 telas não conheciam
    nav-dashboard/nav-carteiras, então o admin fora destas páginas não as via.
    O invariante segue o mesmo; o lugar dele mudou.

    Em 20/08 mudou de novo: o menu passou a ler a MATRIZ DE PERMISSÕES em vez de
    um literal no JS. O invariante segue o mesmo pela terceira vez, e agora ele
    é verificado onde a decisão realmente mora — se `carteiras` virar `nenhum`
    para gestor, o item some do menu E as rotas recusam, junto.
    """
    from app import permissoes

    assert 'id="nav-carteiras"' in html

    # 1. O gestor alcança Carteiras por padrão.
    assert permissoes.PADRAO["gestor"]["carteiras"] != permissoes.NIVEL_NENHUM

    # 2. E o menu sabe qual item corresponde a esse módulo.
    js = (Path(__file__).resolve().parent.parent / "static" / "ui-common.js").read_text(
        encoding="utf-8"
    )
    assert re.search(r'carteiras:\s*"nav-carteiras"', js), (
        "o mapa de módulo para item de menu perdeu Carteiras"
    )


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


# ──────────────────────────────────────────────────────────────────────────
# 6. Os dois painéis (19/08)
# ──────────────────────────────────────────────────────────────────────────

def test_tela_mostra_os_clientes_sem_exigir_busca(html: str) -> None:
    """
    O campo antigo só revelava algo com 2+ caracteres digitados: para achar um
    cliente era preciso já saber o nome dele, e não havia como ver o que
    existe. Agora os dois lados nascem povoados e a busca é filtro opcional.
    """
    assert 'id="listaDisponiveis"' in html
    assert 'id="listaCarteira"' in html
    assert "digite ao menos 2 caracteres" not in html
    # A lista inteira vem de uma vez (491 clientes = 33 KB medidos).
    assert "/api/carteira/documentos?limite=2000" in html


def test_botao_de_lote_esconde_de_verdade(html: str) -> None:
    """
    `.btn` declara `display`, e display explícito vence o `display:none` que o
    atributo `hidden` traz da folha do navegador. Sem a regra, o botão ficava
    visível oferecendo "liberar os 491 filtrados" sem filtro nenhum — um
    clique de consequência enorme onde não devia haver botão.
    """
    assert re.search(r"\.transfer__acao-lote\[hidden\]\s*\{[^}]*display:\s*none", html)


def test_lote_em_massa_nao_e_um_clique(html: str) -> None:
    """
    Sem guarda, "liberar todos" seria conceder o acervo inteiro num clique.

    Até 19/08/2026 a guarda era **esconder** o botão até haver filtro ativo. O
    cliente pediu os botões de lote permanentes (setas de incluir/remover
    todos), e a proteção migrou de esconder para *dizer e confirmar*. Este
    teste trava as três afirmações que substituem a antiga:

      1. `atribuir` confirma quando move mais de um documento — conceder acesso
         em massa não pode ser um clique distraído;
      2. `removerVarios` continua confirmando — revogar já pedia confirmação, e
         seria incoerente tirar acesso com pergunta e dar sem nenhuma;
      3. cada botão de lote imprime a contagem do que vai mover, então a
         magnitude é legível ANTES do clique.

    Trocar o mecanismo é permitido; ficar sem nenhum dos três não é.
    """
    assert re.search(r"documentos\.length\s*>\s*1\s*&&\s*!confirm\(", html),         "liberar em lote deixou de confirmar"
    assert re.search(r"async function removerVarios[\s\S]{0,500}?!confirm\(", html),         "remover em lote deixou de confirmar"
    assert re.search(r'querySelector\("\[data-conta\]"\)\.textContent', html),         "os botões de lote deixaram de imprimir a contagem do que movem"


# ──────────────────────────────────────────────────────────────────────────
# 7. Importação por planilha (19/08)
# ──────────────────────────────────────────────────────────────────────────

def _csv(linhas: str) -> dict:
    return {"file": ("carteiras.csv", linhas.encode("utf-8"), "text/csv")}


def _xlsx(linhas: List[tuple]) -> dict:
    from openpyxl import Workbook

    wb = Workbook()
    for linha in linhas:
        wb.active.append(linha)
    buf = io.BytesIO()
    wb.save(buf)
    return {"file": ("carteiras.xlsx", buf.getvalue(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def test_importa_csv_e_grava(client: TestClient, banco: _Fake) -> None:
    r = client.post(
        "/api/carteira/importar",
        files=_csv(f"email;cnpj\nbruno@x.com;{DOC_BOI}\n"),
        headers=_h("admin"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["atribuidos"] == 1
    assert not r.json()["erros"]
    assert any(
        l["user_id"] == "u-op2" and l["documento"] == DOC_BOI
        for l in banco.tabelas["carteira"]
    )


def test_importa_xlsx(client: TestClient, banco: _Fake) -> None:
    """
    O .xlsx é o que sai do Excel sem passo extra. O import de USUÁRIOS recusa
    qualquer arquivo que comece com `PK` como "binário disfarçado" — e todo
    .xlsx começa com PK, porque é um zip. Aqui a checagem é por extensão
    declarada, senão a planilha legítima seria recusada como ameaça.
    """
    r = client.post(
        "/api/carteira/importar",
        files=_xlsx([("email", "cnpj"), ("bruno@x.com", DOC_BOI)]),
        headers=_h("admin"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["atribuidos"] == 1


def test_linha_ruim_nao_derruba_o_arquivo(client: TestClient, banco: _Fake) -> None:
    """
    Recusar o arquivo inteiro por causa de uma linha faria o gestor perder o
    trabalho já correto — e ele reenviaria tudo, sem saber qual linha corrigir.
    """
    r = client.post(
        "/api/carteira/importar",
        files=_csv(
            "email;cnpj\n"
            f"bruno@x.com;{DOC_BOI}\n"
            f"naoexiste@x.com;{DOC_BOI}\n"
            "bruno@x.com;99999999999999\n"
            "bruno@x.com;\n"
        ),
        headers=_h("admin"),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["atribuidos"] == 1
    motivos = " ".join(e["motivo"] for e in d["erros"])
    assert len(d["erros"]) == 3
    assert "naoexiste@x.com" in motivos          # e-mail sem conta
    assert "99999999999999" in motivos           # documento fora do inventário
    assert "Falta o e-mail ou o CNPJ/CPF" in motivos
    # Cada erro aponta a LINHA da planilha (1 é o cabeçalho).
    assert [e["linha"] for e in d["erros"]] == [3, 4, 5]


def test_gestor_nao_importa_para_fora_do_seu_setor(
    client: TestClient, banco: _Fake
) -> None:
    """
    A barreira por pessoa vale na importação exatamente como na tela — senão
    a planilha viraria a porta dos fundos para atribuir a qualquer um.
    """
    banco.tabelas["users"].append({
        "id": "u-outro", "email": "outro@x.com", "full_name": "De Outro Setor",
        "role": "user", "ativo": True, "departamento_id": "dep-9",
    })
    r = client.post(
        "/api/carteira/importar",
        files=_csv(f"email;cnpj\nana@x.com;{DOC_BOI}\noutro@x.com;{DOC_BOI}\n"),
        headers=_h("gestor"),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["atribuidos"] == 1                      # a do próprio setor entrou
    assert len(d["erros"]) == 1
    assert "não está em um departamento que você lidera" in d["erros"][0]["motivo"]
    assert not any(l["user_id"] == "u-outro" for l in banco.tabelas["carteira"])


def test_planilha_sem_as_colunas_certas_e_recusada(client: TestClient, banco: _Fake) -> None:
    r = client.post(
        "/api/carteira/importar",
        files=_csv("nome;telefone\nAna;9999\n"),
        headers=_h("admin"),
    )
    assert r.status_code == 422
    assert "e-mail do colaborador" in r.json()["detail"]


def test_operador_nao_importa(client: TestClient, banco: _Fake) -> None:
    """A rota concede acesso — quem não monta carteira não pode chamá-la."""
    r = client.post(
        "/api/carteira/importar",
        files=_csv(f"email;cnpj\nana@x.com;{DOC_BOI}\n"),
        headers=_h("user"),
    )
    assert r.status_code == 403


def test_documento_fora_do_inventario_continua_removivel(html: str) -> None:
    """
    Documento atribuído que saiu do inventário não está no universo. Se o
    painel fosse montado só a partir do universo, ele sumiria da tela — e
    ninguém conseguiria tirar um acesso que continua valendo.
    """
    assert "for (const doc of _carteiraAtual)" in html
