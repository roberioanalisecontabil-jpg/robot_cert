"""Histórico de concessão e revogação de acesso.

`permissoes` já guardava `alterado_em` e `alterado_por`: quem mexeu POR ÚLTIMO
naquela célula. Isso não diz o que havia antes nem quantas vezes mudou —
conceder e revogar no mesmo dia deixa a linha idêntica à de quem nunca mexeu, e
é justamente a sequência que uma auditoria de acesso precisa ver.

Duas decisões governam estes testes, e as duas são sobre o que a trilha NÃO
pode fazer:

1. **Só o que mudou.** A tela grava a matriz inteira a cada clique em Salvar.
   Sem o diff seriam 20 linhas por clique, e o histórico registraria cliques em
   vez de decisões — tão inútil quanto não registrar nada.
2. **Nunca derrubar a gravação.** Se a trilha pudesse falhar a concessão, uma
   tabela ausente trancaria o administrador fora de conceder acesso. "Não
   consegui registrar" viraria "você não pode" — a inversão que este módulo
   evita em todo o resto.
"""

from typing import Any, Dict, List

import pytest

from app import permissoes


class _Tabela:
    def __init__(self, pai: "_Sb", nome: str) -> None:
        self._pai, self._nome = pai, nome

    def upsert(self, linhas, **_kw) -> "_Tabela":
        self._pai.upserts.append((self._nome, linhas))
        return self

    def insert(self, linhas) -> "_Tabela":
        if self._pai.falhar_trilha and self._nome == "permissoes_trilha":
            raise RuntimeError("relation permissoes_trilha does not exist")
        self._pai.inseridos.setdefault(self._nome, []).extend(linhas)
        return self

    def select(self, *_a, **_k) -> "_Tabela":
        return self

    def order(self, *_a, **_k) -> "_Tabela":
        return self

    def limit(self, *_a, **_k) -> "_Tabela":
        return self

    def execute(self):
        class R:
            data: List[Dict[str, Any]] = []
        return R()


class _Sb:
    def __init__(self, falhar_trilha: bool = False) -> None:
        self.upserts: list = []
        self.inseridos: Dict[str, list] = {}
        self.falhar_trilha = falhar_trilha

    def table(self, nome: str) -> _Tabela:
        return _Tabela(self, nome)


def _matriz(gestor_usuarios: str = "ler", user_dashboard: str = "nenhum"):
    """Matriz completa e válida, com duas células parametrizáveis."""
    base = {}
    for papel in permissoes.PAPEIS_CONFIGURAVEIS:
        base[papel] = {}
        for modulo in permissoes.MODULOS:
            base[papel][modulo] = permissoes.NIVEL_LER
    base["gestor"]["usuarios"] = gestor_usuarios
    base["user"]["dashboard"] = user_dashboard
    return base


@pytest.fixture
def gravacao(monkeypatch: pytest.MonkeyPatch):
    """`gravar` contra um Supabase falso, com o estado anterior controlável."""
    def _preparar(antes, falhar_trilha=False):
        sb = _Sb(falhar_trilha=falhar_trilha)
        monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
        monkeypatch.setattr("app.settings_state._supabase", lambda: sb)
        monkeypatch.setattr(permissoes, "_buscar_no_banco", lambda: antes)
        monkeypatch.setattr(permissoes, "invalidar_cache", lambda: None)
        return sb
    return _preparar


# ══════════════════════════════════════════════════════════════════════════
# Só o que mudou
# ══════════════════════════════════════════════════════════════════════════

def test_registra_uma_linha_por_celula_alterada(gravacao) -> None:
    antes = _matriz(gestor_usuarios="ler", user_dashboard="nenhum")
    sb = gravacao(antes)

    permissoes.gravar(
        _matriz(gestor_usuarios="editar", user_dashboard="ler"),
        alterado_por="roberio@analisegroup.cnt.br",
    )

    trilha = sb.inseridos.get("permissoes_trilha") or []
    assert len(trilha) == 2, f"esperava 2 mudanças, vieram {len(trilha)}"

    por_celula = {(t["papel"], t["modulo"]): t for t in trilha}
    assert por_celula[("gestor", "usuarios")]["de"] == "ler"
    assert por_celula[("gestor", "usuarios")]["para"] == "editar"
    assert por_celula[("user", "dashboard")]["de"] == "nenhum"
    assert por_celula[("user", "dashboard")]["para"] == "ler"
    assert all(t["alterado_por"] == "roberio@analisegroup.cnt.br" for t in trilha)


def test_salvar_sem_alterar_nada_nao_gera_linha(gravacao) -> None:
    """O que mantém a trilha legível: ela guarda decisões, não cliques."""
    antes = _matriz()
    sb = gravacao(antes)

    permissoes.gravar(_matriz(), alterado_por="alguem@x.com")

    assert sb.inseridos.get("permissoes_trilha") is None
    # E a gravação em si aconteceu — não gerar trilha não é não gravar.
    assert any(nome == "permissoes" for nome, _ in sb.upserts)


def test_primeira_gravacao_registra_a_celula_que_passou_a_existir(gravacao) -> None:
    """Banco vazio: `de` fica vazio, e a linha existe.

    Ignorá-la faria a concessão inicial — a que define o portal inteiro — ser a
    única sem registro.
    """
    sb = gravacao({})
    permissoes.gravar(_matriz(), alterado_por="admin@x.com")

    trilha = sb.inseridos.get("permissoes_trilha") or []
    assert len(trilha) == len(permissoes.PAPEIS_CONFIGURAVEIS) * len(permissoes.MODULOS)
    assert all(t["de"] == "" for t in trilha)


def test_revogacao_e_registrada_como_concessao(gravacao) -> None:
    """Tirar acesso precisa deixar rastro tanto quanto dar."""
    sb = gravacao(_matriz(gestor_usuarios="editar"))
    permissoes.gravar(_matriz(gestor_usuarios="nenhum"), alterado_por="admin@x.com")

    trilha = sb.inseridos.get("permissoes_trilha") or []
    assert len(trilha) == 1
    assert trilha[0]["de"] == "editar"
    assert trilha[0]["para"] == "nenhum"


# ══════════════════════════════════════════════════════════════════════════
# Nunca derrubar a gravação
# ══════════════════════════════════════════════════════════════════════════

def test_trilha_indisponivel_nao_impede_a_concessao(gravacao, caplog) -> None:
    """A decisão que separa este desenho da postura estrita de auditoria.

    "Sem trilha, sem mudança" não cabe aqui: a permissão É o mecanismo de
    recuperação de acesso do portal, e travá-la por causa do registro cria um
    modo de falha pior do que o que o registro previne.
    """
    sb = gravacao(_matriz(gestor_usuarios="ler"), falhar_trilha=True)

    resultado = permissoes.gravar(
        _matriz(gestor_usuarios="editar"), alterado_por="admin@x.com"
    )

    assert resultado["gestor"]["usuarios"] == "editar", "a permissão precisa valer"
    assert any(nome == "permissoes" for nome, _ in sb.upserts)
    # E a falha não pode ser silenciosa: alguém precisa poder descobrir que o
    # histórico tem um buraco.
    assert any(
        "trilha" in r.message.lower() and r.levelname == "ERROR" for r in caplog.records
    ), [r.message for r in caplog.records]


def test_ler_trilha_sem_supabase_devolve_lista_vazia(monkeypatch) -> None:
    """A aba não pode quebrar porque o histórico ficou indisponível."""
    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: False)
    assert permissoes.ler_trilha() == []
