"""
A seleção pertence à identidade. Estado final do rechaveamento (fase 3c).

`colaborador_cert_selecoes` é lida e gravada **só** por `user_id`.
`user_email` deixou de ser escrita — virou coluna anulável na 3b-2 e sai na 3d.

O que isto compra, e que o remendo de 16/08 (`_mover_selecoes_de_email`) não
comprava: aquilo consertava o CHAMADOR. Um UPDATE direto no banco, uma rota
nova ou uma importação voltavam a desprender a linha. Agora ela não fala mais
de endereço, então não há o que desprender — e aquele helper virou código
morto e foi apagado, que era o sinal combinado de conclusão.
"""

from typing import Any, Dict, List

import pytest

import app.alert_state as als
import app.settings_state as st

DOCS = ["27049257000194", "37894958000183"]
SELECOES = "colaborador_cert_selecoes"


class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l, self._f = linhas, []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def upsert(self, p: Dict[str, Any], **k: Any) -> "_Query":
        # Guarda o on_conflict: gravar por identidade e conciliar por outra
        # coluna criaria linha nova a cada save, e o teste tem de enxergar isso.
        self._op, self._p = "upsert", p
        self._chave = k.get("on_conflict", "user_id")
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._f.append((coluna, valor))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def execute(self) -> _Res:
        if self._op == "upsert":
            for r in self._l:
                if r.get(self._chave) is not None and r.get(self._chave) == self._p.get(self._chave):
                    r.update(self._p)
                    return _Res([dict(r)])
            self._l.append(dict(self._p))
            return _Res([dict(self._p)])
        return _Res([dict(r) for r in self._l if all(r.get(c) == v for c, v in self._f)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []))


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
# 1. Leitura
# ──────────────────────────────────────────────────────────────────────────

def test_le_pela_identidade(monkeypatch: pytest.MonkeyPatch) -> None:
    """A linha não guarda endereço nenhum, e mesmo assim é encontrada."""
    _banco(monkeypatch, [{"user_id": "u-ana", "documentos": list(DOCS)}])
    assert st.load_colaborador_selecao("ana@x.com", "u-ana") == DOCS


def test_o_email_nao_encontra_mais_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A queda para `user_email` saiu na 3c. Ela existiu na fase 2 para curar
    linhas criadas antes dela, e só pôde sair depois de a produção confirmar
    1 linha, 1 ligada, 0 órfãs. Fixado aqui porque reintroduzir a queda
    "por segurança" quebraria a 3d, que remove a coluna.
    """
    _banco(monkeypatch, [{"user_email": "ana@x.com", "documentos": list(DOCS)}])
    assert st.load_colaborador_selecao("ana@x.com", "u-ana") == []


def test_sem_identidade_recusa_e_avisa(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Devolver `[]` calado faria a pessoa ver a seleção vazia e concluir que
    perdeu o trabalho dela. Nenhum chamador deveria chegar aqui sem identidade
    desde a fase 2 — se chegar, tem de aparecer no log.
    """
    _banco(monkeypatch, [{"user_id": "u-ana", "documentos": list(DOCS)}])
    with caplog.at_level("WARNING"):
        assert st.load_colaborador_selecao("ana@x.com") == []
    assert "sem user_id" in caplog.text


def test_sem_supabase_le_o_ficheiro_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O ficheiro local continua chaveado por e-mail: nesse modo não existe tabela
    `users`, então ali a identidade *é* o endereço. Os dois backends divergem
    de propósito.
    """
    monkeypatch.setattr(st, "_supabase", lambda: None)
    monkeypatch.setattr(st, "_load_colaborador_file_dict", lambda: {"ana@x.com": DOCS})
    assert st.load_colaborador_selecao("ana@x.com", "u-ana") == DOCS


# ──────────────────────────────────────────────────────────────────────────
# 2. Gravação
# ──────────────────────────────────────────────────────────────────────────

def test_grava_so_a_identidade(monkeypatch: pytest.MonkeyPatch) -> None:
    """`user_email` deixou de ser escrita — some da tabela na 3d."""
    banco = _banco(monkeypatch, [])
    st.save_colaborador_selecao("ana@x.com", DOCS, "u-ana")

    linha = banco.tabelas[SELECOES][0]
    assert linha["user_id"] == "u-ana"
    assert linha["documentos"] == DOCS
    assert "user_email" not in linha


def test_regravar_atualiza_em_vez_de_duplicar(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O `on_conflict` é `user_id`. Se apontasse para outra coluna, cada save
    criaria linha nova, a `UNIQUE (user_id)` recusaria a segunda, e a pessoa
    perderia a alteração — ou pior, ficaria com duas seleções disputando.
    """
    banco = _banco(monkeypatch, [{"user_id": "u-ana", "documentos": ["11111111111111"]}])
    st.save_colaborador_selecao("ana@x.com", DOCS, "u-ana")

    assert len(banco.tabelas[SELECOES]) == 1
    assert banco.tabelas[SELECOES][0]["documentos"] == DOCS


def test_sem_identidade_nao_grava_e_grita(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Gravar sem `user_id` produziria linha órfã de nascença, e `user_id` é o
    alvo do `on_conflict`. A seleção fica só no ficheiro local — que na Vercel
    é efêmero —, então isto é perda de dado e sai como ERROR.
    """
    banco = _banco(monkeypatch, [])
    with caplog.at_level("ERROR"):
        st.save_colaborador_selecao("ana@x.com", DOCS)

    assert banco.tabelas[SELECOES] == []
    assert "não foi gravada" in caplog.text


# ──────────────────────────────────────────────────────────────────────────
# 3. O caminho dos alertas — onde um erro manda e-mail para quem não devia
# ──────────────────────────────────────────────────────────────────────────

def test_destino_e_o_endereco_atual_da_conta(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O ganho, no lugar onde ele importa. O endereço sai de `users` pela
    identidade. E-mail trocado depois da escolha deixa de perder o
    destinatário — antes a seleção era descartada em silêncio por não casar
    com conta nenhuma, e a pessoa parava de ser avisada de vencimento.
    """
    _banco(monkeypatch, [{"user_id": "u-ana", "documentos": list(DOCS)}])
    assert als._get_todos_colaboradores_selecoes() == {"ana@x.com": DOCS}


def test_conta_desativada_nao_recebe(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A barreira de 09/08 não pode ter afrouxado. Identidade resolve QUEM é a
    pessoa, não SE ela deve receber.
    """
    _banco(monkeypatch, [{"user_id": "u-saiu", "documentos": list(DOCS)}])
    assert als._get_todos_colaboradores_selecoes() == {}


def test_identidade_morta_nao_recebe(monkeypatch: pytest.MonkeyPatch) -> None:
    """`user_id` que não existe mais em `users` é descarte, não passe livre."""
    _banco(monkeypatch, [{"user_id": "u-apagado", "documentos": list(DOCS)}])
    assert als._get_todos_colaboradores_selecoes() == {}


def test_linha_sem_identidade_e_contada_nao_ignorada(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Não deveria existir: a produção foi conferida com 0 linhas assim antes da
    3c, e a gravação recusa criar. Se voltar a aparecer, é sinal de que algo
    escreve na tabela por fora do portal — e isso tem de ser visível.
    """
    _banco(monkeypatch, [{"documentos": list(DOCS)}])
    with caplog.at_level("WARNING"):
        assert als._get_todos_colaboradores_selecoes() == {}
    assert "por fora do portal" in caplog.text


def test_users_ilegivel_deixa_a_rodada_sem_destinatario(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Perda consciente da fase 3c: a linha não guarda mais endereço, então sem
    `users` não há para quem mandar. Não é "não sei filtrar", é "não sei
    endereçar", e não há fallback honesto.

    A contrapartida é que a falha grita. Uma rodada inteira de alertas deixando
    de sair em silêncio é o pior modo de falhar para um sistema cuja função é
    avisar sobre vencimento.
    """
    _banco(monkeypatch, [{"user_id": "u-ana", "documentos": list(DOCS)}])
    monkeypatch.setattr(als, "_linhas_ativas", lambda: None)

    with caplog.at_level("ERROR"):
        assert als._get_todos_colaboradores_selecoes() == {}
    assert "não serão enviados" in caplog.text
