"""Testes do sino de notificações (ordenação, deduplicação e totais).

A ordenação anterior punha os vencidos primeiro e ordenava por `dias_restantes`
crescente. Como vencidos têm dias negativos, isso colocava o certificado mais
ANTIGO no topo (um vencido há 936 dias) e empurrava os "expirando" — os únicos
sobre os quais ainda dá para agir — para o fim de uma lista de 519 itens.
É um defeito silencioso: nada quebra, a lista só fica inútil. Daí estes testes.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

import app.notification_service as ns


def _cert(nome: str, dias: int, fingerprint: str, doc: str = "12345678000199") -> dict:
    """Certificado sintético que vence em `dias` (negativo = já vencido)."""
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "not_after": venc.isoformat(),
        "fingerprint_sha256": fingerprint,
        "documento_numero": doc,
        "documento_formatado": doc,
    }


@pytest.fixture
def certificados() -> list:
    return [
        _cert("VENCEU HA 900 DIAS", -900, "aaa"),
        _cert("VENCE EM 25 DIAS", 25, "bbb"),
        _cert("VENCEU HA 2 DIAS", -2, "ccc"),
        _cert("VENCE AMANHA", 1, "ddd"),
        _cert("VENCE EM 25 DIAS", 25, "bbb"),  # mesmo certificado, outro arquivo
        _cert("VENCE EM 200 DIAS", 200, "eee"),  # fora da janela: não é alerta
        _cert("VENCEU HA 40 DIAS", -40, "fff"),  # vencido fora da janela de ação
    ]


@pytest.fixture
def alertas(certificados):
    with patch.object(ns, "load_settings", lambda: None), patch.object(
        ns, "get_latest_snapshot", lambda: None
    ), patch("app.main._list_certificados_payload", lambda *a, **k: {"itens": certificados}):
        yield ns.get_active_alerts("admin@exemplo.com", "admin")


def test_expirando_vem_antes_de_vencido(alertas) -> None:
    tipos = [a["tipo"] for a in alertas]
    ultimo_expirando = max(i for i, t in enumerate(tipos) if t == "expiring")
    primeiro_vencido = min(i for i, t in enumerate(tipos) if t == "expired")
    assert ultimo_expirando < primeiro_vencido


def test_expirando_ordenado_do_mais_urgente(alertas) -> None:
    exp = [a for a in alertas if a["tipo"] == "expiring"]
    assert [a["nome"] for a in exp] == ["VENCE AMANHA", "VENCE EM 25 DIAS"]
    assert exp == sorted(exp, key=lambda a: a["dias_restantes"])


def test_vencido_mais_recente_primeiro(alertas) -> None:
    """O bug original: o vencido há 900 dias aparecia no topo de tudo."""
    venc = [a["nome"] for a in alertas if a["tipo"] == "expired"]
    assert venc == ["VENCEU HA 2 DIAS", "VENCEU HA 40 DIAS", "VENCEU HA 900 DIAS"]
    assert alertas[0]["nome"] != "VENCEU HA 900 DIAS"


def test_duplicata_por_fingerprint_colapsa_em_uma_linha(alertas) -> None:
    bbb = [a for a in alertas if a["fingerprint_sha256"] == "bbb"]
    assert len(bbb) == 1
    assert bbb[0]["ocorrencias"] == 2, "a contagem de arquivos não pode ser perdida"


def test_certificado_fora_da_janela_futura_nao_vira_alerta(alertas) -> None:
    assert "VENCE EM 200 DIAS" not in [a["nome"] for a in alertas]


def test_vencido_antigo_e_listado_mas_nao_e_acionavel(alertas) -> None:
    """Continua visível na lista; só não conta para o badge do sino."""
    por_nome = {a["nome"]: a for a in alertas}
    assert por_nome["VENCEU HA 40 DIAS"]["acionavel"] is False
    assert por_nome["VENCEU HA 2 DIAS"]["acionavel"] is True


def test_mensagens_em_linguagem_natural(alertas) -> None:
    por_nome = {a["nome"]: a["mensagem"] for a in alertas}
    assert "vence amanhã" in por_nome["VENCE AMANHA"]
    assert "venceu há 2 dias" in por_nome["VENCEU HA 2 DIAS"]


def test_payload_separa_totais_dos_itens(certificados) -> None:
    with patch.object(ns, "load_settings", lambda: None), patch.object(
        ns, "get_latest_snapshot", lambda: None
    ), patch("app.main._list_certificados_payload", lambda *a, **k: {"itens": certificados}):
        p = ns.build_notifications_payload("admin@exemplo.com", "admin")

    assert p["total"] == 5  # 6 alertas brutos - 1 duplicata
    assert p["total_expirando"] == 2
    assert p["total_vencidos"] == 3
    assert p["total_acionavel"] == 3  # exclui o vencido há 40 dias
    assert p["arquivos_duplicados_agrupados"] == 1
    assert p["truncado"] is False


def test_payload_trunca_e_sinaliza(certificados) -> None:
    total = ns.NOTIF_MAX_ITENS + 10
    muitos = [_cert(f"CERT {i}", -i - 1, f"fp{i}") for i in range(total)]
    with patch.object(ns, "load_settings", lambda: None), patch.object(
        ns, "get_latest_snapshot", lambda: None
    ), patch("app.main._list_certificados_payload", lambda *a, **k: {"itens": muitos}):
        p = ns.build_notifications_payload("admin@exemplo.com", "admin")

    assert p["total"] == total
    assert p["exibidos"] == ns.NOTIF_MAX_ITENS
    assert p["truncado"] is True
    assert len(p["itens"]) == ns.NOTIF_MAX_ITENS


def test_usuario_comum_ve_apenas_o_que_selecionou(certificados) -> None:
    with patch.object(ns, "load_settings", lambda: None), patch.object(
        ns, "get_latest_snapshot", lambda: None
    ), patch("app.main._list_certificados_payload", lambda *a, **k: {"itens": certificados}):
        # O duplo recebe (email, user_id): desde a fase 2 do rechaveamento de
        # colaborador_cert_selecoes a seleção é procurada pela identidade, e o
        # e-mail é só a queda enquanto `user_email` existir.
        with patch.object(ns, "load_colaborador_selecao", lambda e, uid=None: ["12345678000199"]):
            assert len(ns.get_active_alerts("user@exemplo.com", "user")) == 5
        with patch.object(ns, "load_colaborador_selecao", lambda e, uid=None: []):
            assert ns.get_active_alerts("user@exemplo.com", "user") == []
