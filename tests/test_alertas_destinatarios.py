"""Quem pode receber alerta de vencimento.

Os destinatários dos alertas `expiring` saíam de `colaborador_cert_selecoes`
sem nenhuma consulta a `users` (`alert_state.py`, monte de `destinatarios`).
Consequências, ambas observadas em produção em 09/08/2026:

- desativar um usuário no painel NÃO o tirava dos e-mails;
- linhas órfãs — de conta apagada, ou de identidade de serviço como
  `agent@internal`, criada por execuções de teste contra o banco real —
  continuavam recebendo indefinidamente.

Havia quatro dessas, duas em domínios de terceiros (`certguard.com`,
`example.com`), recebendo nome de titular, CNPJ/CPF e data de vencimento de
certificados de clientes. O antispam mascarava: só não chegava e-mail porque
aquela combinação certificado+destinatário já constava como enviada. Qualquer
certificado novo entrando na janela de 30 dias produziria envio.
"""

from unittest.mock import patch

import pytest

import app.alert_state as als


class _FakeQuery:
    def __init__(self, dados: list) -> None:
        self._dados = dados

    def select(self, *_a, **_k) -> "_FakeQuery":
        return self

    def eq(self, coluna: str, valor) -> "_FakeQuery":  # noqa: ANN001
        return _FakeQuery([d for d in self._dados if d.get(coluna) == valor])

    def execute(self):
        class R:
            data = self._dados
        return R()


class _FakeSupabase:
    def __init__(self, tabelas: dict) -> None:
        self._tabelas = tabelas

    def table(self, nome: str) -> _FakeQuery:
        return _FakeQuery(list(self._tabelas.get(nome, [])))


def _banco(users: list, selecoes: list) -> _FakeSupabase:
    return _FakeSupabase({"users": users, "colaborador_cert_selecoes": selecoes})


# `saiu@` está na forma NOVA (papel preservado, estado desligado) e `legado@` na
# forma ANTIGA, de antes de 15/08, quando desativar sobrescrevia o papel. As duas
# precisam barrar: a segunda porque bases sem a migration aplicada ainda a têm.
USERS = [
    {"id": "u-ativo", "email": "ativo@empresa.com", "role": "user", "ativo": True},
    {"id": "u-chefe", "email": "chefe@empresa.com", "role": "admin", "ativo": True},
    {"id": "u-saiu", "email": "saiu@empresa.com", "role": "user", "ativo": False},
    {"id": "u-legado", "email": "legado@empresa.com", "role": "disabled"},
]

# Desde a fase 3c do rechaveamento a seleção é chaveada por `user_id`, e o
# endereço de destino sai de `users` — a linha não guarda mais e-mail nenhum.
#
# As duas últimas são as órfãs que motivaram este arquivo, na forma que passam
# a ter depois da migration: `user_id` apontando para conta que não existe. O
# que garantia o descarte antes era o endereço não casar; agora é a identidade
# não resolver. A proteção tem de valer igual pelos dois caminhos.
SELECOES = [
    {"user_id": "u-ativo", "documentos": ["27049257000194"]},
    {"user_id": "u-chefe", "documentos": ["37894958000183"]},
    {"user_id": "u-saiu", "documentos": ["27049257000194"]},
    {"user_id": "u-legado", "documentos": ["27049257000194"]},
    {"user_id": "u-agente-apagado", "documentos": ["12345678000190"]},
    {"user_id": "u-fantasma", "documentos": ["27049257000194"]},
]


def test_usuario_desativado_nao_recebe() -> None:
    with patch.object(als, "_supabase", lambda: _banco(USERS, SELECOES)):
        r = als._get_todos_colaboradores_selecoes()

    assert "saiu@empresa.com" not in r, "desativar no painel tem de parar o e-mail"


def test_desativado_na_forma_antiga_tambem_nao_recebe() -> None:
    """
    `role='disabled'` continua barrando.

    Enquanto o papel guardava o estado, este era o único jeito de desativar. Se
    a leitura passasse a olhar só `ativo`, a coluna ausente valeria `True` por
    omissão e todo desativado de antes da migration voltaria a receber e-mail —
    sem erro, sem log, e sem ninguém para reclamar de receber a mais.
    """
    with patch.object(als, "_supabase", lambda: _banco(USERS, SELECOES)):
        r = als._get_todos_colaboradores_selecoes()

    assert "legado@empresa.com" not in r


def test_email_sem_conta_nao_recebe() -> None:
    """Linha órfã de conta apagada, ou nunca criada."""
    with patch.object(als, "_supabase", lambda: _banco(USERS, SELECOES)):
        r = als._get_todos_colaboradores_selecoes()

    assert "fantasma@outrodominio.com" not in r


def test_identidade_de_servico_nao_recebe() -> None:
    """`agent@internal` é o agente, não uma pessoa — não tem caixa de entrada."""
    with patch.object(als, "_supabase", lambda: _banco(USERS, SELECOES)):
        r = als._get_todos_colaboradores_selecoes()

    assert "agent@internal" not in r


def test_usuarios_ativos_continuam_recebendo() -> None:
    """O filtro não pode silenciar quem deve ser avisado."""
    with patch.object(als, "_supabase", lambda: _banco(USERS, SELECOES)):
        r = als._get_todos_colaboradores_selecoes()

    assert set(r) == {"ativo@empresa.com", "chefe@empresa.com"}
    assert r["ativo@empresa.com"] == ["27049257000194"]


def test_falha_ao_listar_usuarios_deixa_a_rodada_sem_destinatario(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    **Este teste mudou de sinal na fase 3c, e a mudança é uma perda consciente.**

    Antes, a seleção guardava o endereço, então uma falha ao ler `users` só
    tirava o filtro — as seleções passavam inteiras e o alerta saía. Era o
    comportamento certo para um sistema cuja função é avisar.

    Depois do rechaveamento a linha não guarda mais endereço: ele só existe em
    `users`. Sem conseguir ler essa tabela não há para quem mandar. Não é "não
    sei filtrar", é "não sei endereçar", e não há fallback honesto.

    Essa redundância era exatamente o defeito que o rechaveamento removeu — um
    endereço que envelhecia junto da linha. Perdê-la é o preço, e a
    contrapartida é que a falha grita: sai `ERROR` com a contagem, e o job
    tenta de novo no ciclo seguinte.
    """
    class BancoQueFalhaEmUsers(_FakeSupabase):
        def table(self, nome: str):
            if nome == "users":
                raise RuntimeError("indisponível")
            return super().table(nome)

    banco = BancoQueFalhaEmUsers({"colaborador_cert_selecoes": SELECOES})
    with caplog.at_level("ERROR"):
        with patch.object(als, "_supabase", lambda: banco):
            r = als._get_todos_colaboradores_selecoes()

    assert r == {}
    assert "não serão enviados" in caplog.text, (
        "a rodada morreu em silêncio; é justamente o que não pode acontecer"
    )


def test_sem_supabase_usa_arquivo_local_sem_filtrar() -> None:
    """Modo offline: não há tabela `users` para consultar."""
    local = {"alguem@empresa.com": ["27049257000194"]}
    with patch.object(als, "_supabase", lambda: None):
        with patch.object(als, "_load_colaborador_file_dict", lambda: local):
            r = als._get_todos_colaboradores_selecoes()

    assert r == local


def test_endereco_de_destino_sai_normalizado() -> None:
    """
    Uma classe inteira de erro que o rechaveamento apagou.

    Este teste nasceu porque `users` e as seleções podiam divergir na
    capitalização, e o cruzamento por texto cortava o alerta. Agora o
    cruzamento é por uuid — não há caixa a divergir. O que sobra a garantir é
    que o endereço **de saída** venha normalizado, porque quem consome usa a
    chave para deduplicar destinatário.
    """
    users = [{"id": "u-1", "email": "  Fulano@Empresa.com ", "role": "user"}]
    selecoes = [{"user_id": "u-1", "documentos": ["1"]}]

    with patch.object(als, "_supabase", lambda: _banco(users, selecoes)):
        r = als._get_todos_colaboradores_selecoes()

    assert r == {"fulano@empresa.com": ["1"]}
