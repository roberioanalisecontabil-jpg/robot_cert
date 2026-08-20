"""
Recuperação de senha por código de 6 dígitos (A8 da auditoria de UI/UX).

Seis dígitos são 1 milhão de combinações, e o hash em repouso protege pouco —
quem tivesse leitura da tabela reverteria um sha256 de 6 dígitos em segundos.
**A segurança é a soma dos limites**, e é isso que este arquivo guarda:
validade curta, 3 tentativas com queima, teto de 3 pedidos por hora, e pedido
novo invalidando os anteriores.

Cada um desses testes existe porque afrouxar o limite correspondente não
produz sintoma nenhum — o fluxo continua funcionando, só que adivinhável.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

import app.senha_reset as sr
from app import auth

EMAIL = "ana@x.com"
SENHA_NOVA = "senha-nova-123"
TABELA = "password_reset_codigo"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], nome: str) -> None:
        self._l, self._n = linhas, nome
        self._f: List = []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def insert(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "insert", p
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "eq", v))
        return self

    def is_(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "is", v))
        return self

    def gt(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "gt", v))
        return self

    def lt(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "lt", v))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        for c, op, v in self._f:
            a = r.get(c)
            if op == "eq" and a != v:
                return False
            if op == "is" and not (v == "null" and a is None):
                return False
            if op == "gt" and not (a is not None and str(a) > str(v)):
                return False
            if op == "lt" and not (a is not None and str(a) < str(v)):
                return False
        return True

    def execute(self) -> _Res:
        if self._op == "insert":
            linha = dict(self._p)
            linha.setdefault("id", f"id-{len(self._l) + 1}")
            linha.setdefault("tentativas", 0)
            linha.setdefault("consumed_at", None)
            self._l.append(linha)
            return _Res([dict(linha)])
        if self._op == "update":
            alt = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._p)
                    alt.append(dict(r))
            return _Res(alt)
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Res(fora)
        return _Res([dict(r) for r in self._l if self._casa(r)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.enviados: List[Dict[str, Any]] = []

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), nome)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-ana", "email": EMAIL, "full_name": "Ana", "role": "user",
             "ativo": True, "password_hash": auth.get_password_hash("antiga-123")},
            {"id": "u-saiu", "email": "saiu@x.com", "full_name": "Saiu",
             "role": "user", "ativo": False,
             "password_hash": auth.get_password_hash("antiga-123")},
        ],
        TABELA: [],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)

    # O envio real exigiria SMTP configurado. O duplo guarda o código para os
    # testes poderem usá-lo — é o que o e-mail entregaria à pessoa.
    import app.main as m

    def _fake_envio(conta: Dict[str, Any], codigo: str) -> None:
        fake.enviados.append({"para": conta["email"], "codigo": codigo})

    monkeypatch.setattr(m, "_enviar_codigo_por_email", _fake_envio)
    return fake


def _pedir(client: TestClient, email: str = EMAIL):
    return client.post("/api/senha/codigo", json={"email": email})


def _codigo_enviado(banco: _Fake) -> str:
    return banco.enviados[-1]["codigo"]


# ──────────────────────────────────────────────────────────────────────────
# 1. O caminho feliz
# ──────────────────────────────────────────────────────────────────────────

def test_fluxo_completo(client: TestClient, banco: _Fake) -> None:
    assert _pedir(client).status_code == 200
    codigo = _codigo_enviado(banco)
    assert len(codigo) == 6 and codigo.isdigit()

    r = client.post("/api/senha/verificar", json={"email": EMAIL, "codigo": codigo})
    assert r.status_code == 200

    r = client.post("/api/senha/redefinir",
                    json={"email": EMAIL, "codigo": codigo, "password": SENHA_NOVA})
    assert r.status_code == 200, r.text

    linha = banco.tabelas["users"][0]
    assert auth.verify_password(SENHA_NOVA, linha["password_hash"])
    assert linha.get("senha_alterada_em"), "não carimbou a troca"


def test_codigo_nao_e_guardado_em_claro(client: TestClient, banco: _Fake) -> None:
    """
    O hash protege pouco com 6 dígitos, mas guardar em claro não protegeria
    nada: qualquer leitura da tabela — Studio, backup, integração — entregaria
    códigos ativos prontos para uso.
    """
    _pedir(client)
    linha = banco.tabelas[TABELA][0]
    assert "codigo" not in linha
    assert linha["codigo_hash"] != _codigo_enviado(banco)
    assert len(linha["codigo_hash"]) == 64


# ──────────────────────────────────────────────────────────────────────────
# 2. Não virar detector de contas
# ──────────────────────────────────────────────────────────────────────────

def test_email_inexistente_responde_igual(client: TestClient, banco: _Fake) -> None:
    a = _pedir(client, "ninguem@x.com")
    b = _pedir(client, EMAIL)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json(), "a diferença de resposta enumera contas"


def test_conta_desativada_responde_igual_mas_nao_recebe(
    client: TestClient, banco: _Fake
) -> None:
    """
    Redefinir senha não pode ser caminho de volta para quem foi desativado. De
    fora não dá para distinguir; por dentro, nenhum código é criado.
    """
    r = _pedir(client, "saiu@x.com")
    assert r.status_code == 200
    assert r.json()["message"] == _pedir(client, EMAIL).json()["message"]
    assert not any(e["para"] == "saiu@x.com" for e in banco.enviados)


def test_teto_de_pedidos_responde_igual(client: TestClient, banco: _Fake) -> None:
    """
    Dizer "você pediu demais" confirmaria que a conta existe — exatamente o que
    o genérico esconde.
    """
    for _ in range(sr.MAX_PEDIDOS_HORA):
        _pedir(client)
    r = _pedir(client)
    assert r.status_code == 200
    assert r.json()["message"] == _pedir(client, "ninguem@x.com").json()["message"]


# ──────────────────────────────────────────────────────────────────────────
# 3. Os limites — onde mora a segurança inteira
# ──────────────────────────────────────────────────────────────────────────

def test_teto_de_pedidos_para_de_gerar(client: TestClient, banco: _Fake) -> None:
    """
    O limite que sustenta todos os outros. Sem ele, 3 tentativas por código não
    valem nada: bastaria pedir mil códigos para ter três mil chances.
    """
    for _ in range(sr.MAX_PEDIDOS_HORA + 5):
        _pedir(client)
    assert len(banco.enviados) == sr.MAX_PEDIDOS_HORA


def test_queima_no_terceiro_erro(client: TestClient, banco: _Fake) -> None:
    """
    Errar 3 vezes mata o código. Sem a queima, o atacante que errou 3 vezes
    pediria outro e o anterior continuaria adivinhável — as tentativas se
    somariam entre códigos.
    """
    _pedir(client)
    certo = _codigo_enviado(banco)
    errado = "000000" if certo != "000000" else "111111"

    for _ in range(sr.MAX_TENTATIVAS):
        r = client.post("/api/senha/verificar", json={"email": EMAIL, "codigo": errado})
        assert r.status_code == 400

    r = client.post("/api/senha/verificar", json={"email": EMAIL, "codigo": certo})
    assert r.status_code == 400, "o código certo funcionou depois de queimado"


def test_pedido_novo_invalida_o_anterior(client: TestClient, banco: _Fake) -> None:
    _pedir(client)
    primeiro = _codigo_enviado(banco)
    _pedir(client)
    segundo = _codigo_enviado(banco)
    assert primeiro != segundo

    r = client.post("/api/senha/verificar", json={"email": EMAIL, "codigo": primeiro})
    assert r.status_code == 400, "o código antigo continuou valendo"

    r = client.post("/api/senha/verificar", json={"email": EMAIL, "codigo": segundo})
    assert r.status_code == 200


def test_codigo_e_de_uso_unico(client: TestClient, banco: _Fake) -> None:
    _pedir(client)
    codigo = _codigo_enviado(banco)

    r1 = client.post("/api/senha/redefinir",
                     json={"email": EMAIL, "codigo": codigo, "password": SENHA_NOVA})
    assert r1.status_code == 200

    r2 = client.post("/api/senha/redefinir",
                     json={"email": EMAIL, "codigo": codigo, "password": "outra-senha-9"})
    assert r2.status_code == 400, "o mesmo código redefiniu duas vezes"


def test_codigo_expirado_nao_serve(client: TestClient, banco: _Fake) -> None:
    _pedir(client)
    codigo = _codigo_enviado(banco)
    passado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    banco.tabelas[TABELA][0]["expires_at"] = passado

    r = client.post("/api/senha/verificar", json={"email": EMAIL, "codigo": codigo})
    assert r.status_code == 400


def test_codigo_de_outra_pessoa_nao_serve(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Seis dígitos colidem entre pessoas, então a busca é escopada por conta. Se
    fosse só pelo código, digitar um número qualquer cairia na conta alheia —
    e com 1 milhão de combinações e muitos códigos vigentes isso deixa de ser
    hipotético.
    """
    banco.tabelas["users"].append(
        {"id": "u-bru", "email": "bruno@x.com", "full_name": "Bruno", "role": "user",
         "ativo": True, "password_hash": auth.get_password_hash("antiga-123")}
    )
    _pedir(client, EMAIL)
    codigo_da_ana = _codigo_enviado(banco)

    r = client.post("/api/senha/verificar",
                    json={"email": "bruno@x.com", "codigo": codigo_da_ana})
    assert r.status_code == 400


def test_verificar_nao_consome(client: TestClient, banco: _Fake) -> None:
    """
    `/verificar` é conveniência de tela. Se consumisse, a pessoa passaria pelo
    passo do código e o `redefinir` seguinte falharia — com o código correto na
    mão e nenhuma explicação.
    """
    _pedir(client)
    codigo = _codigo_enviado(banco)
    for _ in range(3):
        assert client.post("/api/senha/verificar",
                           json={"email": EMAIL, "codigo": codigo}).status_code == 200
    assert client.post("/api/senha/redefinir",
                       json={"email": EMAIL, "codigo": codigo,
                             "password": SENHA_NOVA}).status_code == 200


def test_senha_curta_recusada_sem_gastar_o_codigo(
    client: TestClient, banco: _Fake
) -> None:
    """
    A validação de tamanho vem ANTES do consumo. Invertido, quem digitasse uma
    senha curta perderia o código e teria de pedir outro — gastando o teto de 3
    por hora por causa de um erro de digitação.
    """
    _pedir(client)
    codigo = _codigo_enviado(banco)

    r = client.post("/api/senha/redefinir",
                    json={"email": EMAIL, "codigo": codigo, "password": "123"})
    assert r.status_code == 422

    r = client.post("/api/senha/redefinir",
                    json={"email": EMAIL, "codigo": codigo, "password": SENHA_NOVA})
    assert r.status_code == 200, "o código foi gasto pela senha curta"


# ──────────────────────────────────────────────────────────────────────────
# 4. Trocar a senha derruba a sessão aberta
# ──────────────────────────────────────────────────────────────────────────

def test_troca_de_senha_invalida_o_token_ja_emitido(
    client: TestClient, banco: _Fake
) -> None:
    """
    O ponto de `senha_alterada_em`. Quem redefine a senha normalmente o faz por
    suspeitar que alguém entrou — e sem isto esse alguém continuaria dentro por
    até 24h, exatamente enquanto o dono acredita ter resolvido.
    """
    h = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": EMAIL, "role": "user"})}
    # `/api/settings` continua sendo a sonda de "esta sessao ainda vale?", mas
    # desde 20/08 o modulo `configuracao` entrou na matriz de permissoes e um
    # papel `user` deixou de alcancar as pastas e o host de SMTP — corretamente.
    #
    # A conta do teste passa a ser admin: o que esta em jogo aqui e a troca de
    # senha derrubar a sessao, e o papel e incidental. Note que o papel vem da
    # LINHA DO BANCO e nao do token (`main.py`, `role=conta.get("role")`), entao
    # mudar so o JWT nao teria efeito.
    banco.tabelas["users"][0]["role"] = "admin"
    assert client.get("/api/settings", headers=h).status_code == 200

    _pedir(client)
    client.post("/api/senha/redefinir",
                json={"email": EMAIL, "codigo": _codigo_enviado(banco),
                      "password": SENHA_NOVA})
    # O carimbo é gravado "agora"; o token nasceu antes. A margem de 5s do
    # comparador exige empurrar a marca para frente para o teste ser estável.
    banco.tabelas["users"][0]["senha_alterada_em"] = (
        datetime.now(timezone.utc) + timedelta(minutes=1)
    ).isoformat()

    assert client.get("/api/settings", headers=h).status_code == 401


def test_sem_a_coluna_ninguem_e_deslogado(client: TestClient, banco: _Fake) -> None:
    """
    Coluna nula significa "nunca trocou a senha", que é verdade para toda conta
    antiga. Tratar ausência como invalidação deslogaria o portal inteiro no
    deploy da migration.
    """
    banco.tabelas["users"][0].pop("senha_alterada_em", None)
    banco.tabelas["users"][0]["role"] = "admin"  # ver o teste acima
    h = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": EMAIL, "role": "user"})}
    assert client.get("/api/settings", headers=h).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 5. O sorteio
# ──────────────────────────────────────────────────────────────────────────

def test_sessao_le_a_coluna_da_troca_de_senha() -> None:
    """
    Teste estrutural, e não funcional, porque o funcional NÃO pega isto.

    `_conta_da_sessao` monta um `select` com a lista de colunas. Se
    `senha_alterada_em` sair dessa lista, o PostgREST devolve a linha sem a
    chave, `_senha_trocada_depois_do_token` lê como "nunca trocou" e a
    invalidação de sessão deixa de existir — em silêncio.

    Os fakes destes testes ignoram a lista de colunas e devolvem a linha
    inteira, então `test_troca_de_senha_invalida_o_token_ja_emitido` passa
    mesmo com a coluna fora do select. Foi exatamente o que aconteceu ao
    escrever isto: o teste verde, e a produção sem a funcionalidade.
    """
    import re
    from pathlib import Path

    fonte = (
        Path(__file__).resolve().parent.parent / "app" / "main.py"
    ).read_text(encoding="utf-8")
    trecho = fonte.split("def _conta_da_sessao")[1].split("\ndef ")[0]

    # O ARGUMENTO do select, e não o corpo da função: a primeira versão deste
    # teste procurava o nome da coluna no trecho inteiro e passava por causa do
    # COMENTÁRIO logo acima do select, que também menciona a coluna. Verde,
    # medindo o comentário. Só apareceu ao rodar o mutante.
    selects = re.findall(r'\.select\(\s*"([^"]*)"', trecho)
    assert selects, "não achei nenhum select em _conta_da_sessao"
    colunas = {c.strip() for c in selects[0].split(",")}
    assert "senha_alterada_em" in colunas, (
        "_conta_da_sessao parou de pedir senha_alterada_em; a troca de senha "
        f"deixou de derrubar sessão aberta. Colunas pedidas: {sorted(colunas)}"
    )


def test_codigo_preserva_zeros_a_esquerda() -> None:
    """
    Formatar com `str(n)` em vez de zero-padding produziria códigos de 4 ou 5
    dígitos vez ou outra — e um campo com `maxlength=6` e `pattern=[0-9]{6}`
    recusaria justamente esses, sem ninguém entender por quê.
    """
    assert all(len(sr.gerar_codigo()) == 6 for _ in range(200))


def test_codigos_nao_se_repetem_na_pratica() -> None:
    """Contraprova rasteira contra um gerador constante ou de espaço mínimo."""
    assert len({sr.gerar_codigo() for _ in range(200)}) > 150
