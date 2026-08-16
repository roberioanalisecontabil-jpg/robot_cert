"""Carteira: quais clientes cada operador pode instalar.

É a outra metade do modelo de 15/08, e o inverso da custódia. A custódia ABRE
por padrão (todo certificado válido vai ao cofre, o admin desativa); o acesso
FECHA por padrão (operador sem atribuição não instala nada). Os dois defaults
são opostos de propósito: guardar a mais é desperdício, liberar a mais é
vazamento.

O teste mais importante deste arquivo não exercita comportamento nenhum — é o
`test_toda_rota_que_cria_token_passa_pela_carteira`, que lê o código. A razão
está em `docs/PLANO_reorganizacao_portal.md` §6.4: a aplicação fala com o
Supabase pelo service_role, que ignora RLS, então **não há rede de proteção no
banco**. Toda rota que emite token de instalação precisa lembrar de checar a
carteira, e uma que esqueça entrega chave privada a quem não devia — sem erro,
sem log, e passando por toda a suíte funcional.
"""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci
import app.main as m


# ──────────────────────────────────────────────────────────────────────────
# Fake Supabase
# ──────────────────────────────────────────────────────────────────────────

class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, tabela: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._t, self._b, self._n = tabela, banco, nome
        self._filtros: List[tuple] = []
        self._em: Optional[tuple] = None
        self._op = "select"
        self._payload: Any = None

    def select(self, *_c: str) -> "_Query":
        self._op = "select"
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

    def in_(self, c: str, vs: List[Any]) -> "_Query":
        self._em = (c, list(vs))
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        if self._em and r.get(self._em[0]) not in self._em[1]:
            return False
        return all(r.get(c) == v for c, v in self._filtros)

    def execute(self) -> _Resultado:
        if self._b.quebrado.get(self._n):
            raise RuntimeError(f"banco fora do ar ao ler {self._n}")
        if self._op == "select":
            return _Resultado([dict(r) for r in self._t if self._casa(r)])
        if self._op == "upsert":
            linhas = self._payload if isinstance(self._payload, list) else [self._payload]
            for nova in linhas:
                self._t.append(dict(nova))
            return _Resultado([dict(x) for x in linhas])
        if self._op == "delete":
            fora = [r for r in self._t if self._casa(r)]
            self._t[:] = [r for r in self._t if not self._casa(r)]
            return _Resultado(fora)
        raise AssertionError(self._op)


class _Fake:
    def __init__(self) -> None:
        self.tabelas: Dict[str, List[Dict[str, Any]]] = {}
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        self.tabelas.setdefault(nome, [])
        return _Query(self.tabelas[nome], self, nome)


DOC_MEU = "33706943000193"
DOC_ALHEIO = "55993256000139"
CERT_MEU = "id-cert-meu"
CERT_ALHEIO = "id-cert-alheio"
CERT_SEM_DOC = "id-cert-sem-doc"

# Sobrou uma rota emissora depois que /prepare (instalação via agente numa
# estação) foi removida em 16/08 — o cliente não usa esse caminho. A lista
# continua sendo lista de propósito: se outra rota emissora nascer, ela entra
# aqui, e `test_toda_rota_que_cria_token_passa_pela_carteira` cobra isso.
ROTAS = [
    ("/api/cert-installer/preparar-download", {"nome": "ACME"}),
]


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake()
    fake.tabelas["cert_pfx_store"] = [
        {"id": CERT_MEU, "documento": DOC_MEU},
        {"id": CERT_ALHEIO, "documento": DOC_ALHEIO},
        {"id": CERT_SEM_DOC, "documento": None},
    ]
    fake.tabelas["carteira"] = [
        {"user_id": "u-operador", "documento": DOC_MEU,
         "atribuido_por": "u-gestor", "atribuido_por_email": "gestor@x.com"},
    ]
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    monkeypatch.setattr(m, "_resolve_user_id", lambda email: "u-" + email.split("@")[0])
    # O que viria depois da barreira não interessa aqui; o que interessa é se
    # chegou a ser chamado.
    monkeypatch.setattr(ci, "create_install_token",
                        lambda **kw: ("tok", "tid", __import__("datetime").datetime.now(
                            __import__("datetime").timezone.utc)))
    monkeypatch.setattr(ci, "log_event", lambda **kw: None)
    return fake


def _h(papel: str, email: Optional[str] = None) -> dict:
    email = email or f"{papel}@x.com"
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': email, 'role': papel})}"}


def _pedir(client: TestClient, rota: str, extra: dict, ids: List[str], headers: dict):
    return client.post(rota, json={"certificate_ids": ids, **extra}, headers=headers)


# ──────────────────────────────────────────────────────────────────────────
# 1. A barreira existe em toda rota que emite token
#
# Eram duas até 16/08; sobrou a do instalador avulso. O parametrize continua
# porque o número volta a crescer no dia em que outro caminho de instalação
# existir — e é aí que esquecer a barreira fica fácil.
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rota,extra", ROTAS)
def test_operador_instala_o_que_esta_na_carteira(
    client: TestClient, banco: _Fake, rota: str, extra: dict
) -> None:
    r = _pedir(client, rota, extra, [CERT_MEU], _h("user", "operador@x.com"))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("rota,extra", ROTAS)
def test_operador_nao_instala_fora_da_carteira(
    client: TestClient, banco: _Fake, rota: str, extra: dict
) -> None:
    r = _pedir(client, rota, extra, [CERT_ALHEIO], _h("user", "operador@x.com"))
    assert r.status_code == 403, r.text
    assert DOC_ALHEIO in r.json()["detail"], "a mensagem diz qual cliente foi negado"


@pytest.mark.parametrize("rota,extra", ROTAS)
def test_um_certificado_fora_reprova_o_pedido_inteiro(
    client: TestClient, banco: _Fake, rota: str, extra: dict
) -> None:
    """
    Nada de atender pela metade.

    Emitir token só para o que é permitido pareceria prestativo, mas o usuário
    receberia um instalador silenciosamente incompleto e descobriria na máquina
    dele. Recusar dizendo o que falta é mais rápido de resolver.
    """
    chamou = []
    with patch.object(ci, "create_install_token", lambda **kw: chamou.append(kw) or ("t", "i", None)):
        r = _pedir(client, rota, extra, [CERT_MEU, CERT_ALHEIO], _h("user", "operador@x.com"))
    assert r.status_code == 403, r.text
    assert not chamou, "nenhum token pode ter sido emitido"


@pytest.mark.parametrize("rota,extra", ROTAS)
def test_certificado_sem_documento_e_negado_ao_operador(
    client: TestClient, banco: _Fake, rota: str, extra: dict
) -> None:
    """
    Sem documento não há como saber de quem é — logo não há carteira que o
    contenha. São 52 no acervo do ANALISESRV, e ficam restritos a admin.
    """
    r = _pedir(client, rota, extra, [CERT_SEM_DOC], _h("user", "operador@x.com"))
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("papel", ["admin", "gestor"])
@pytest.mark.parametrize("rota,extra", ROTAS)
def test_admin_e_gestor_tem_alcance_total(
    client: TestClient, banco: _Fake, papel: str, rota: str, extra: dict
) -> None:
    """
    Para o gestor isto é consequência da decisão de 15/08: quem pode atribuir
    qualquer cliente a qualquer operador pode atribuir a si mesmo. Limitá-lo
    seria teatro, e teatro de segurança confunde quem lê o código depois.
    """
    r = _pedir(client, rota, extra, [CERT_ALHEIO, CERT_SEM_DOC], _h(papel))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("rota,extra", ROTAS)
def test_teto_de_certificados_por_token(
    client: TestClient, banco: _Fake, rota: str, extra: dict
) -> None:
    """
    O array `certificate_ids` é livre; sem teto, o bundle fica imprevisível.

    A tela também impede, mas a tela não é barreira: quem chama a rota direto
    passaria por cima. E o limite tem de valer para admin também — não é
    permissão, é tamanho de arquivo.
    """
    from app.main import MAX_CERTIFICADOS_POR_TOKEN

    demais = [CERT_MEU] * (MAX_CERTIFICADOS_POR_TOKEN + 1)
    r = _pedir(client, rota, extra, demais, _h("admin"))
    assert r.status_code == 422, r.text
    assert str(MAX_CERTIFICADOS_POR_TOKEN) in r.json()["detail"], "a mensagem diz o limite"

    no_limite = [CERT_MEU] * MAX_CERTIFICADOS_POR_TOKEN
    r = _pedir(client, rota, extra, no_limite, _h("admin"))
    assert r.status_code == 200, "exatamente no limite tem de passar"


# ──────────────────────────────────────────────────────────────────────────
# 2. Falha fechada, e com o status que manda a pessoa ao lugar certo
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tabela", ["carteira", "cert_pfx_store"])
def test_falha_de_banco_recusa_com_503_e_nao_403(
    client: TestClient, banco: _Fake, tabela: str
) -> None:
    """
    Negar é o resultado seguro nos dois casos, mas o código importa.

    Um 403 mandaria o operador procurar o gestor para pedir acesso que ele já
    tem; 503 diz "tente de novo". Confundir os dois transforma uma queda de
    banco de dez minutos numa conversa desnecessária.
    """
    banco.quebrado[tabela] = True
    chamou = []
    with patch.object(ci, "create_install_token", lambda **kw: chamou.append(kw) or ("t", "i", None)):
        r = _pedir(client, "/api/cert-installer/preparar-download", {"nome": "ACME"},
                   [CERT_MEU], _h("user", "operador@x.com"))
    assert r.status_code == 503, r.text
    assert not chamou


def test_listar_carteira_levanta_em_vez_de_devolver_vazio() -> None:
    class _Quebrado:
        def table(self, _n):
            raise RuntimeError("banco fora do ar")

    with patch.object(ci, "_supabase", lambda: _Quebrado()):
        with pytest.raises(ci.CarteiraIndisponivel):
            ci.listar_carteira("u-1")


# ──────────────────────────────────────────────────────────────────────────
# 3. Normalização do documento
# ──────────────────────────────────────────────────────────────────────────

def test_documento_formatado_na_carteira_ainda_casa(
    client: TestClient, banco: _Fake
) -> None:
    """
    A carteira gravada com pontuação tem de casar com o cofre, que só guarda
    dígitos. Formatos divergentes não dariam erro — o operador simplesmente
    nunca conseguiria instalar, e ninguém saberia por quê.
    """
    banco.tabelas["carteira"] = [
        {"user_id": "u-operador", "documento": "33.706.943/0001-93",
         "atribuido_por": None, "atribuido_por_email": "x@x.com"},
    ]
    r = _pedir(client, "/api/cert-installer/preparar-download", {"nome": "ACME"},
               [CERT_MEU], _h("user", "operador@x.com"))
    assert r.status_code == 200, r.text


def test_atribuicao_normaliza_antes_de_gravar(client: TestClient, banco: _Fake) -> None:
    r = client.post(
        "/api/carteira",
        json={"user_id": "u-novo", "documentos": ["33.706.943/0001-93", "  ", "025.096.424-48"]},
        headers=_h("gestor"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["gravados"] == 2, "entrada vazia não vira linha"
    gravados = [l for l in banco.tabelas["carteira"] if l["user_id"] == "u-novo"]
    assert {l["documento"] for l in gravados} == {"33706943000193", "02509642448"}


# ──────────────────────────────────────────────────────────────────────────
# 4. Quem pode montar carteira, e a trilha
# ──────────────────────────────────────────────────────────────────────────

def test_operador_nao_monta_a_propria_carteira(client: TestClient, banco: _Fake) -> None:
    """Senão a barreira inteira é decorativa."""
    r = client.post(
        "/api/carteira",
        json={"user_id": "u-operador", "documentos": [DOC_ALHEIO]},
        headers=_h("user", "operador@x.com"),
    )
    assert r.status_code == 403, r.text


def test_atribuicao_registra_quem_deu_o_acesso(client: TestClient, banco: _Fake) -> None:
    """
    Com o gestor podendo atribuir qualquer cliente do acervo, a trilha é a
    única forma de reconstruir o estrago se a conta dele for comprometida. O
    e-mail vai junto do UUID de propósito: apagar a conta zeraria o UUID e
    deixaria a trilha sem responsável, justo quando ela mais importa.
    """
    client.post(
        "/api/carteira",
        json={"user_id": "u-novo", "documentos": [DOC_ALHEIO]},
        headers=_h("gestor", "chefe@x.com"),
    )
    linha = [l for l in banco.tabelas["carteira"] if l["user_id"] == "u-novo"][0]
    assert linha["atribuido_por_email"] == "chefe@x.com"
    assert linha["atribuido_por"] == "u-chefe"


def test_remover_da_carteira_tira_o_acesso(client: TestClient, banco: _Fake) -> None:
    r = client.delete(f"/api/carteira/u-operador/{DOC_MEU}", headers=_h("gestor"))
    assert r.status_code == 200, r.text

    r = _pedir(client, "/api/cert-installer/preparar-download", {"nome": "ACME"},
               [CERT_MEU], _h("user", "operador@x.com"))
    assert r.status_code == 403, "o acesso tinha de cair junto"


# ──────────────────────────────────────────────────────────────────────────
# 5. O teste estrutural — rota nova não escapa da barreira
# ──────────────────────────────────────────────────────────────────────────

def test_toda_rota_que_cria_token_passa_pela_carteira() -> None:
    """
    Lê `app/main.py` e exige que quem emite token confira a carteira.

    Não há RLS que segure isto: a aplicação usa o service_role, que ignora
    políticas. A barreira mora inteiramente no código da rota, e uma rota nova
    que esqueça de chamá-la passa por toda a suíte funcional — os testes acima
    só cobrem as rotas que alguém lembrou de listar.

    `create_install_token` é o gargalo certo para vigiar: um token de instalação
    É a entrega da chave privada. Sem token não há bundle.
    """
    fonte = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    def nomes_chamados(no: ast.AST) -> set:
        out = set()
        for filho in ast.walk(no):
            if isinstance(filho, ast.Call):
                f = filho.func
                if isinstance(f, ast.Name):
                    out.add(f.id)
                elif isinstance(f, ast.Attribute):
                    out.add(f.attr)
        return out

    faltando = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        chamados = nomes_chamados(no)
        if "create_install_token" not in chamados:
            continue
        if "_validar_pedido_de_instalacao" not in chamados:
            faltando.append(f"{no.name} (linha {no.lineno})")

    assert not faltando, (
        "rota(s) emitindo token de instalação sem checar a carteira: "
        f"{faltando} — chame _validar_pedido_de_instalacao antes de create_install_token"
    )


def test_o_teste_estrutural_realmente_encontra_as_rotas() -> None:
    """
    Contraprova do anterior: se o padrão de busca parasse de casar com o
    código, o teste acima passaria por vácuo e não protegeria nada.
    """
    fonte = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    emissoras = [
        no.name
        for no in ast.walk(arvore)
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "create_install_token"
            for c in ast.walk(no)
        )
    ]
    # Era 2 até 16/08; /prepare foi removida. O mínimo é 1: com zero, o teste
    # acima passaria por vácuo e não protegeria nada — que é o ponto desta
    # contraprova.
    assert len(emissoras) >= 1, f"nenhuma rota emissora encontrada: {emissoras}"
