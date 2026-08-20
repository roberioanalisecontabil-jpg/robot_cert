# -*- coding: utf-8 -*-
"""
Matriz de permissões por papel (`app/permissoes.py`).

Etapa 3 de `docs/PLANO_niveis_de_acesso.md`. Os testes aqui travam as decisões
de modelo, não a implementação: se amanhã a matriz vier de outro lugar, estes
testes devem continuar valendo.
"""
from __future__ import annotations

import pytest

from app import permissoes


@pytest.fixture(autouse=True)
def cache_limpo() -> None:
    """A matriz é cacheada por 30s; sem isto um teste contamina o seguinte."""
    permissoes.invalidar_cache()


def test_admin_e_sempre_total_e_nao_depende_da_matriz() -> None:
    """
    `admin` não tem linha na tabela, por desenho.

    É o que impede o engano mais caro possível numa tela de permissões: o
    administrador desmarcando o próprio acesso a Usuários e ficando sem como
    voltar. Não é validação que pode falhar — é ausência de dado.
    """
    for modulo in permissoes.MODULOS:
        assert permissoes.nivel_de("admin", modulo) == permissoes.NIVEL_EDITAR

    # Nem uma matriz vinda do banco muda isso: `admin` não passa pela consulta.
    assert "admin" not in permissoes.PADRAO


def test_papel_desconhecido_nao_herda_acesso() -> None:
    """Falha fechada: papel sem linha na matriz não ganha nada por omissão."""
    for modulo in permissoes.MODULOS:
        assert permissoes.nivel_de("auditor", modulo) == permissoes.NIVEL_NENHUM
    assert permissoes.nivel_de("", "inicio") == permissoes.NIVEL_NENHUM


def test_editar_satisfaz_ler_mas_ler_nao_satisfaz_editar() -> None:
    assert permissoes.pode("gestor", "carteiras", permissoes.NIVEL_LER)
    assert permissoes.pode("gestor", "carteiras", permissoes.NIVEL_EDITAR)
    assert permissoes.pode("user", "historico", permissoes.NIVEL_LER)
    assert not permissoes.pode("user", "historico", permissoes.NIVEL_EDITAR)
    assert not permissoes.pode("user", "usuarios", permissoes.NIVEL_LER)


def test_modulo_desconhecido_estoura_em_vez_de_devolver_nenhum() -> None:
    """
    Erro de digitação no nome do módulo não pode virar "sem permissão".

    `require_modulo("usuarios ")` com espaço sobrando devolveria `nenhum` em
    silêncio e trancaria todo mundo para fora de um módulo que ninguém mexeu.
    """
    with pytest.raises(ValueError):
        permissoes.nivel_de("user", "modulo-que-nao-existe")
    with pytest.raises(ValueError):
        permissoes.pode("user", "inicio", "nivel-que-nao-existe")


def test_padrao_reproduz_o_comportamento_de_hoje() -> None:
    """
    A semente é o comportamento atual, não uma política nova.

    Ligar esta camada não pode mudar nada no dia do deploy — assim qualquer
    diferença observada depois é mudança que alguém fez de propósito, e não
    efeito colateral da migration.
    """
    # Só admin vê Dashboard, Instalador, Usuários e Configuração (ui-common.js).
    for papel in ("gestor", "user"):
        for modulo in ("dashboard", "instalador", "usuarios", "configuracao"):
            assert permissoes.nivel_de(papel, modulo) == permissoes.NIVEL_NENHUM

    # Carteiras é do gestor, e só dele entre os não-admin.
    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_EDITAR
    assert permissoes.nivel_de("user", "carteiras") == permissoes.NIVEL_NENHUM

    # As telas de consulta ficam abertas a quem está autenticado, como hoje.
    for papel in ("gestor", "user"):
        for modulo in ("inicio", "historico", "vencidos", "duplicidades", "acompanhamento"):
            assert permissoes.nivel_de(papel, modulo) == permissoes.NIVEL_LER


def test_matriz_para_papel_devolve_todos_os_modulos() -> None:
    """O menu monta a partir disto; faltar chave viraria item invisível."""
    for papel in ("admin", "gestor", "user", "papel-novo"):
        linha = permissoes.matriz_para_papel(papel)
        assert set(linha) == set(permissoes.MODULOS)
        assert all(v in permissoes.NIVEIS for v in linha.values())


def test_tabela_ausente_cai_no_padrao_em_vez_de_derrubar_o_portal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Código pode chegar antes da migration.

    É a lição registrada na migration de 18/08: "código antes da coluna faria
    toda requisição autenticada virar 503 — o portal inteiro parando". Tabela
    que ainda não existe vale como "não configurado", e o padrão entra.
    """
    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            raise RuntimeError(
                "{'message': \"Could not find the table 'public.permissoes' "
                "in the schema cache\", 'code': 'PGRST205'}"
            )

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_EDITAR


def test_falha_de_leitura_nao_e_falta_de_permissao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Banco fora do ar levanta — quem chama traduz em 503, nunca em 403.

    Mesmo princípio de `cert_installer.AlcanceIndisponivel`: um 403 aqui faria a
    pessoa acreditar que perdeu um acesso que continua sendo dela, e o suporte
    procuraria a permissão errada.
    """
    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            raise RuntimeError("connection refused")

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    with pytest.raises(permissoes.PermissoesIndisponiveis):
        permissoes.nivel_de("gestor", "carteiras")

    # E o admin continua passando: ele não consulta a matriz.
    assert permissoes.nivel_de("admin", "carteiras") == permissoes.NIVEL_EDITAR


def test_tabela_vazia_vale_como_nao_semeada(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Zero linhas é "ainda não semeada", não "ninguém pode nada".

    Fechar tudo aqui derrubaria o acesso de todo mundo entre a criação da tabela
    e o INSERT da semente — uma janela de segundos que ninguém quer descobrir em
    produção.
    """
    class _Resp:
        data: list = []

    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            return _Resp()

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_EDITAR


def test_matriz_do_banco_vence_o_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configurar tem que valer — senão a tela seria decorativa."""
    class _Resp:
        data = [
            {"papel": "gestor", "modulo": "carteiras", "nivel": "ler"},
            {"papel": "user", "modulo": "instalador", "nivel": "editar"},
            # Lixo: módulo inexistente e nível inválido são descartados sem
            # derrubar a leitura inteira.
            {"papel": "user", "modulo": "modulo-fantasma", "nivel": "editar"},
            {"papel": "user", "modulo": "inicio", "nivel": "super"},
        ]

    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            return _Resp()

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_LER
    assert permissoes.nivel_de("user", "instalador") == permissoes.NIVEL_EDITAR
    # O que veio do banco substitui a linha inteira do papel: o que não foi
    # gravado é `nenhum`, e não o valor do padrão. Meia-configuração seria pior
    # que nenhuma — a tela mostraria uma coisa e o servidor faria outra.
    assert permissoes.nivel_de("user", "historico") == permissoes.NIVEL_NENHUM
    assert permissoes.nivel_de("user", "inicio") == permissoes.NIVEL_NENHUM


def test_semente_da_migration_e_identica_ao_padrao_do_codigo() -> None:
    """
    O SQL e o Python não podem divergir.

    Se a semente da migration disser uma coisa e `PADRAO` outra, o portal se
    comporta de um jeito antes de rodar a migration e de outro depois — e a
    diferença apareceria como "mudou sozinho" para quem usa. Este teste é a
    única coisa que amarra os dois arquivos.
    """
    import re
    from pathlib import Path

    sql_path = Path("supabase/pendentes/20260820100000_permissoes_por_papel.sql")
    if not sql_path.is_file():  # migration já aplicada e movida para migrations/
        sql_path = Path("supabase/migrations/20260820100000_permissoes_por_papel.sql")
    assert sql_path.is_file(), "migration de permissões sumiu"

    sql = sql_path.read_text(encoding="utf-8")

    semente: dict = {}
    for papel, modulo, nivel in re.findall(r"\('(gestor|user)',\s*'(\w+)',\s*'(\w+)'", sql):
        semente.setdefault(papel, {})[modulo] = nivel

    for papel in ("gestor", "user"):
        for modulo in permissoes.MODULOS:
            assert semente[papel][modulo] == permissoes.PADRAO[papel][modulo], (
                f"{papel}/{modulo}: SQL diz {semente[papel][modulo]!r}, "
                f"código diz {permissoes.PADRAO[papel][modulo]!r}"
            )

    # E o `check` do banco tem que aceitar exatamente os módulos que o código
    # conhece — nem mais (aceitaria lixo), nem menos (recusaria valor legítimo).
    bloco = re.search(r"modulo\s+text not null check \(modulo in \(([^)]*)\)", sql, re.S)
    assert bloco, "o check de modulo sumiu da migration"
    assert set(re.findall(r"'(\w+)'", bloco.group(1))) == set(permissoes.MODULOS)
