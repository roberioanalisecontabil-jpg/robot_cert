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


USERS = [
    {"email": "ativo@empresa.com", "role": "user"},
    {"email": "chefe@empresa.com", "role": "admin"},
    {"email": "saiu@empresa.com", "role": "disabled"},
]

SELECOES = [
    {"user_email": "ativo@empresa.com", "documentos": ["27049257000194"]},
    {"user_email": "chefe@empresa.com", "documentos": ["37894958000183"]},
    {"user_email": "saiu@empresa.com", "documentos": ["27049257000194"]},
    {"user_email": "agent@internal", "documentos": ["12345678000190"]},
    {"user_email": "fantasma@outrodominio.com", "documentos": ["27049257000194"]},
]


def test_usuario_desativado_nao_recebe() -> None:
    with patch.object(als, "_supabase", lambda: _banco(USERS, SELECOES)):
        r = als._get_todos_colaboradores_selecoes()

    assert "saiu@empresa.com" not in r, "desativar no painel tem de parar o e-mail"


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


def test_falha_ao_listar_usuarios_nao_silencia_os_alertas() -> None:
    """
    Se a consulta a `users` falhar, o filtro não se aplica e as seleções
    passam inteiras.

    A alternativa — tratar erro como "ninguém está ativo" — transformaria uma
    falha de leitura em silêncio total dos alertas, que é o pior modo de
    falhar para um sistema cuja função é avisar sobre vencimento.
    """
    class BancoQueFalhaEmUsers(_FakeSupabase):
        def table(self, nome: str):
            if nome == "users":
                raise RuntimeError("indisponível")
            return super().table(nome)

    banco = BancoQueFalhaEmUsers({"colaborador_cert_selecoes": SELECOES})
    with patch.object(als, "_supabase", lambda: banco):
        r = als._get_todos_colaboradores_selecoes()

    assert set(r) == {s["user_email"] for s in SELECOES}


def test_sem_supabase_usa_arquivo_local_sem_filtrar() -> None:
    """Modo offline: não há tabela `users` para consultar."""
    local = {"alguem@empresa.com": ["27049257000194"]}
    with patch.object(als, "_supabase", lambda: None):
        with patch.object(als, "_load_colaborador_file_dict", lambda: local):
            r = als._get_todos_colaboradores_selecoes()

    assert r == local


def test_comparacao_de_email_ignora_caixa() -> None:
    """`users` e as seleções podem divergir na capitalização."""
    users = [{"email": "Fulano@Empresa.com", "role": "user"}]
    selecoes = [{"user_email": "fulano@empresa.com", "documentos": ["1"]}]

    with patch.object(als, "_supabase", lambda: _banco(users, selecoes)):
        r = als._get_todos_colaboradores_selecoes()

    assert "fulano@empresa.com" in r, "divergência de caixa não pode cortar o alerta"
