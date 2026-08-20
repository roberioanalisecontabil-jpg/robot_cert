""""Li todos" esconde o aviso, não o certificado.

A distinção é o desenho inteiro desta funcionalidade. Se marcar como lido
silenciasse o CERTIFICADO, quem lesse o aviso de "faltam 30 dias" nunca veria o
de 15, nem o do vencimento — e teria desligado um alarme sem saber. O botão
seria uma armadilha bem-intencionada.

A marca é por par (certificado, marco), com a MESMA chave que o e-mail usa para
decidir se manda reforço. As duas coisas passam a concordar sobre o que é "um
aviso": cruzou o próximo limiar, é aviso novo, reaparece nos dois canais.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import app.notification_service as ns


class _Settings:
    alertas_marcos = ""

    def effective_source(self):  # pragma: no cover - não usado nestes testes
        raise AssertionError("o payload é injetado; não deveria varrer pasta")


def _cert(nome: str, dias: int, fp: str) -> dict:
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "not_after": venc.isoformat(),
        "fingerprint_sha256": fp,
        "documento_numero": "12345678000199",
        "documento_formatado": "12.345.678/0001-99",
    }


@pytest.fixture
def sino(monkeypatch: pytest.MonkeyPatch):
    """O sino de um admin (vê tudo), com as lidas controláveis pelo teste."""
    lidas: set = set()

    monkeypatch.setattr(ns, "load_settings", lambda: _Settings())
    monkeypatch.setattr(ns, "get_latest_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(ns, "carregar_notificacoes_lidas", lambda uid: set(lidas))

    def _montar(itens: List[Dict[str, Any]]) -> Dict[str, Any]:
        monkeypatch.setattr(
            "app.main._list_certificados_payload", lambda *a, **k: {"itens": itens}
        )
        return ns.build_notifications_payload("admin@x.com", "admin", "uid-1")

    return _montar, lidas


# ══════════════════════════════════════════════════════════════════════════
# A chave
# ══════════════════════════════════════════════════════════════════════════

def test_cada_aviso_tem_chave_e_ela_muda_com_o_marco(sino) -> None:
    """Marcos diferentes do MESMO certificado são avisos diferentes."""
    montar, _ = sino

    a_25 = montar([_cert("CLIENTE", 25, "fp-1")])["itens"][0]["chave"]
    a_12 = montar([_cert("CLIENTE", 12, "fp-1")])["itens"][0]["chave"]
    vencido = montar([_cert("CLIENTE", -3, "fp-1")])["itens"][0]["chave"]

    assert a_25 != a_12 != vencido
    assert len({a_25, a_12, vencido}) == 3
    # E o fingerprint continua sendo parte da identidade: dois certificados no
    # mesmo marco não podem compartilhar chave.
    outro = montar([_cert("OUTRO", 25, "fp-2")])["itens"][0]["chave"]
    assert outro != a_25


def test_dias_dentro_do_mesmo_marco_produzem_a_mesma_chave(sino) -> None:
    """Senão o aviso reapareceria todo dia, e "li todos" nunca funcionaria."""
    montar, _ = sino
    c_25 = montar([_cert("CLIENTE", 25, "fp-1")])["itens"][0]["chave"]
    c_20 = montar([_cert("CLIENTE", 20, "fp-1")])["itens"][0]["chave"]
    assert c_25 == c_20, "25 e 20 dias estão ambos no marco de 30"


# ══════════════════════════════════════════════════════════════════════════
# O efeito de marcar
# ══════════════════════════════════════════════════════════════════════════

def test_lido_sai_da_lista_e_do_badge(sino) -> None:
    """Ficar nos totais faria o badge seguir aceso — o que o botão resolve."""
    montar, lidas = sino
    itens = [_cert("A", 5, "fp-a"), _cert("B", 5, "fp-b")]

    antes = montar(itens)
    assert antes["total_acionavel"] == 2

    lidas.add(antes["itens"][0]["chave"])
    depois = montar(itens)

    assert depois["total_acionavel"] == 1
    assert len(depois["itens"]) == 1
    assert depois["itens"][0]["nome"] == "B"


def test_o_certificado_volta_ao_cruzar_o_proximo_prazo(sino) -> None:
    """O teste que justifica o desenho todo.

    A pessoa lê o aviso de 30 dias e marca. Quinze dias depois o certificado
    entra no marco de 15 — e precisa reaparecer, porque agora é outra coisa
    que ela precisa saber.
    """
    montar, lidas = sino

    aos_25 = montar([_cert("CLIENTE", 25, "fp-1")])
    lidas.add(aos_25["itens"][0]["chave"])

    # Mesmo certificado, mesmo dia: continua escondido.
    assert montar([_cert("CLIENTE", 25, "fp-1")])["itens"] == []

    # Cruzou para o marco de 15: volta.
    voltou = montar([_cert("CLIENTE", 12, "fp-1")])
    assert len(voltou["itens"]) == 1
    assert voltou["total_acionavel"] == 1


def test_o_vencimento_volta_mesmo_com_o_aviso_de_prazo_lido(sino) -> None:
    """Ler "vence em 5 dias" não pode esconder "venceu"."""
    montar, lidas = sino
    lidas.add(montar([_cert("CLIENTE", 5, "fp-1")])["itens"][0]["chave"])

    vencido = montar([_cert("CLIENTE", -1, "fp-1")])
    assert len(vencido["itens"]) == 1


def test_sem_nada_marcado_o_sino_e_o_de_antes(sino) -> None:
    """A ausência de linhas na tabela nova não pode mudar nada."""
    montar, _ = sino
    d = montar([_cert("A", 5, "fp-a"), _cert("B", -2, "fp-b")])
    assert d["total_acionavel"] == 2
    assert len(d["itens"]) == 2


def test_falha_ao_ler_as_lidas_mostra_tudo_em_vez_de_esconder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direção do erro importa.

    Falhar e devolver "nada lido" faz o sino repetir algo que a pessoa já viu —
    irritante. Falhar e esconder faria um vencimento sumir por erro de leitura.
    Só a primeira é aceitável, e é a que `carregar_notificacoes_lidas` implementa.
    """
    import app.settings_state as ss

    class _ClientQuebrado:
        def table(self, _n):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(ss, "_supabase", lambda: _ClientQuebrado())
    assert ss.carregar_notificacoes_lidas("uid-1") == set()
