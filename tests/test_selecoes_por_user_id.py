"""
Fase 2 do rechaveamento: a seleção pertence à identidade, não ao endereço.

`colaborador_cert_selecoes` ainda tem `user_email` como chave primária, mas
desde a fase 1 existe `user_id` com FK para `users`. Aqui o código passa a
**ler pela identidade** e a **gravar nas duas colunas**.

O que isto compra, e que o remendo de 16/08 (`_mover_selecoes_de_email`) não
comprava: aquilo consertava o CHAMADOR — um UPDATE direto no banco, uma rota
nova ou uma importação voltavam a desprender a linha. Agora a linha não fala
mais de endereço, então não há o que desprender.

Cobre também a transição, que é onde mora o risco real: linha criada pelo
código anterior tem `user_id` nulo, e ler só pela identidade faria a pessoa
abrir Acompanhamento e ver a seleção vazia.
"""

from typing import Any, Dict, List, Optional

import pytest

import app.alert_state as als
import app.settings_state as st

DOCS = ["27049257000194", "37894958000183"]
SELECOES = "colaborador_cert_selecoes"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], nome: str) -> None:
        self._l, self._n, self._f = linhas, nome, []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def upsert(self, p: Dict[str, Any], **_k: Any) -> "_Query":
        self._op, self._p = "upsert", p
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._f.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._f)

    def execute(self) -> _Res:
        if self._op == "upsert":
            for r in self._l:
                if r.get("user_email") == self._p.get("user_email"):
                    r.update(self._p)
                    return _Res([dict(r)])
            self._l.append(dict(self._p))
            return _Res([dict(self._p)])
        return _Res([dict(r) for r in self._l if self._casa(r)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), nome)


USERS = [
    {"id": "u-ana", "email": "ana@x.com", "role": "user", "ativo": True},
    {"id": "u-bru", "email": "bruno@x.com", "role": "user", "ativo": True},
    {"id": "u-saiu", "email": "saiu@x.com", "role": "user", "ativo": False},
]


def _banco(monkeypatch: pytest.MonkeyPatch, selecoes: List[Dict[str, Any]]) -> _Fake:
    fake = _Fake({"users": [dict(u) for u in USERS], SELECOES: selecoes})
    monkeypatch.setattr(st, "_supabase", lambda: fake)
    monkeypatch.setattr(als, "_supabase", lambda: fake)
    return fake


# ──────────────────────────────────────────────────────────────────────────
# 1. Leitura pela identidade
# ──────────────────────────────────────────────────────────────────────────

def test_le_pela_identidade_mesmo_com_o_email_desatualizado(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O caso que o rechaveamento existe para resolver. A linha guarda um endereço
    antigo; a conta hoje é outra. Antes isto devolvia vazio — a seleção da
    pessoa simplesmente sumia da tela.
    """
    _banco(monkeypatch, [
        {"user_id": "u-ana", "user_email": "ana.antiga@x.com", "documentos": list(DOCS)},
    ])
    assert st.load_colaborador_selecao("ana@x.com", "u-ana") == DOCS


def test_linha_sem_user_id_ainda_e_encontrada(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A transição. Entre a fase 1 e este deploy, o código anterior podia criar
    linha sem `user_id`. Sem esta queda para o e-mail, essa pessoa abriria
    Acompanhamento e veria a seleção vazia — e concluiria que perdeu o
    trabalho dela.
    """
    _banco(monkeypatch, [{"user_email": "ana@x.com", "documentos": list(DOCS)}])
    assert st.load_colaborador_selecao("ana@x.com", "u-ana") == DOCS


def test_identidade_tem_precedencia_sobre_o_endereco(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Com as duas linhas presentes, vale a da identidade. Cenário possível na
    transição: uma linha órfã com o endereço, e a linha boa já ligada.
    """
    _banco(monkeypatch, [
        {"user_email": "ana@x.com", "documentos": ["11111111111111"]},
        {"user_id": "u-ana", "user_email": "ana.nova@x.com", "documentos": list(DOCS)},
    ])
    assert st.load_colaborador_selecao("ana@x.com", "u-ana") == DOCS


def test_sem_identidade_cai_no_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chamador que não tem o `user_id` em mãos continua funcionando."""
    _banco(monkeypatch, [{"user_email": "ana@x.com", "documentos": list(DOCS)}])
    assert st.load_colaborador_selecao("ana@x.com") == DOCS


# ──────────────────────────────────────────────────────────────────────────
# 2. Gravação nas duas colunas
# ──────────────────────────────────────────────────────────────────────────

def test_grava_as_duas_colunas(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    `user_email` continua obrigatório porque ainda é a chave primária — é ela
    que o `on_conflict` usa. `user_id` entra junto e é o que sobra na fase 4.
    """
    banco = _banco(monkeypatch, [])
    st.save_colaborador_selecao("ana@x.com", DOCS, "u-ana")

    linha = banco.tabelas[SELECOES][0]
    assert linha["user_email"] == "ana@x.com"
    assert linha["user_id"] == "u-ana"
    assert linha["documentos"] == DOCS


def test_gravar_cura_a_linha_da_transicao(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Linha antiga, sem `user_id`. Um save qualquer a liga à identidade — a
    transição se resolve sozinha conforme as pessoas usam a tela, sem
    backfill manual.
    """
    banco = _banco(monkeypatch, [{"user_email": "ana@x.com", "documentos": ["11111111111111"]}])
    st.save_colaborador_selecao("ana@x.com", DOCS, "u-ana")

    assert len(banco.tabelas[SELECOES]) == 1, "criou linha nova em vez de atualizar"
    assert banco.tabelas[SELECOES][0]["user_id"] == "u-ana"


def test_sem_identidade_nao_inventa_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Gravar `user_id` vazio ou "None" violaria a FK, e a gravação inteira
    falharia — a pessoa perderia a seleção que acabou de fazer.
    """
    banco = _banco(monkeypatch, [])
    st.save_colaborador_selecao("ana@x.com", DOCS)
    assert "user_id" not in banco.tabelas[SELECOES][0]


# ──────────────────────────────────────────────────────────────────────────
# 3. O caminho dos alertas — onde um erro manda e-mail para quem não devia
# ──────────────────────────────────────────────────────────────────────────

def test_alerta_vai_para_o_endereco_ATUAL_da_conta(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O ganho, no lugar onde ele importa. A linha guarda o endereço antigo, mas
    o destino sai de `users` pela identidade. Antes, esta seleção era
    descartada em silêncio por não casar com nenhuma conta — e a pessoa
    deixava de ser avisada de um certificado vencendo.
    """
    _banco(monkeypatch, [
        {"user_id": "u-ana", "user_email": "ana.antiga@x.com", "documentos": list(DOCS)},
    ])
    r = als._get_todos_colaboradores_selecoes()
    assert r == {"ana@x.com": DOCS}


def test_conta_desativada_nao_recebe_nem_ligada_por_id(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A barreira de 09/08 não pode ter afrouxado. `user_id` apontando para conta
    desativada continua sendo descarte — a identidade resolve quem é a pessoa,
    não se ela deve receber.
    """
    _banco(monkeypatch, [
        {"user_id": "u-saiu", "user_email": "saiu@x.com", "documentos": list(DOCS)},
    ])
    assert als._get_todos_colaboradores_selecoes() == {}


def test_user_id_orfao_nao_recebe(monkeypatch: pytest.MonkeyPatch) -> None:
    """`user_id` que não existe mais em `users` é descarte, não passe livre."""
    _banco(monkeypatch, [
        {"user_id": "u-apagado", "user_email": "ana@x.com", "documentos": list(DOCS)},
    ])
    assert als._get_todos_colaboradores_selecoes() == {}, (
        "linha com identidade morta passou pelo endereço gravado"
    )


def test_linha_sem_user_id_ainda_e_filtrada_pelo_email(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Na transição, o comportamento antigo continua valendo — inclusive o filtro."""
    _banco(monkeypatch, [
        {"user_email": "bruno@x.com", "documentos": list(DOCS)},
        {"user_email": "fantasma@outrodominio.com", "documentos": list(DOCS)},
        {"user_email": "saiu@x.com", "documentos": list(DOCS)},
    ])
    assert als._get_todos_colaboradores_selecoes() == {"bruno@x.com": DOCS}


def test_falha_ao_ler_users_nao_silencia_todo_mundo(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    "Não sei filtrar" mantém o comportamento anterior em vez de zerar a lista.
    Aqui o fail-closed seria o erro: lista vazia significa que ninguém é
    avisado de nada, e ninguém reclama de não receber e-mail.
    """
    _banco(monkeypatch, [{"user_email": "ana@x.com", "documentos": list(DOCS)}])
    monkeypatch.setattr(als, "_linhas_ativas", lambda: None)
    assert als._get_todos_colaboradores_selecoes() == {"ana@x.com": DOCS}
