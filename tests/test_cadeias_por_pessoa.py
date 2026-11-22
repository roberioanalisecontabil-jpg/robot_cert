"""Trilha de instalações por pessoa (revisão de 21/11/2026, P6-1 e P5-1).

`cadeias_de_instalacao` lia os N eventos mais recentes do portal inteiro e só
depois filtrava pela pessoa: com 200 eventos de outros, as tentativas dela
sumiam da Trilha e do histórico da aba Pessoas, sem aviso."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import cert_installer
from tests.test_seguranca_lote4 import banco  # noqa: F401

AGORA = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _ev(i: int, email: str, token: str, quando: datetime, event: str = "SOLICITADO") -> dict:
    return {"id": i, "event": event, "user_email": email, "token_id": token, "status": None,
            "detail": None, "created_at": quando.isoformat(), "certificate_id": None}


def test_cadeia_da_pessoa_aparece_mesmo_com_eventos_recentes_de_outros(banco) -> None:
    banco.tabelas["install_log"] = (
        [_ev(i, "outro@x.com", f"t{i}", AGORA - timedelta(minutes=i)) for i in range(1, 301)]
        + [_ev(999, "alvo@x.com", "tA", AGORA - timedelta(days=2))]
    )
    cadeias = cert_installer.cadeias_de_instalacao(limite=200, user_email="Alvo@X.com")
    assert [c["token_id"] for c in cadeias] == ["tA"]


def test_truncado_conta_os_eventos_lidos_e_nao_os_filtrados(banco) -> None:
    banco.tabelas["install_log"] = [_ev(i, "outro@x.com", f"t{i}", AGORA - timedelta(minutes=i)) for i in range(1, 11)]
    info: dict = {}
    cadeias = cert_installer.cadeias_de_instalacao(limite=5, apenas_com_falha=True, info=info)
    assert cadeias == [] and info["truncado"] is True


def test_gravacao_guarda_o_email_em_minusculas(banco) -> None:
    banco.tabelas["install_log"] = []
    cert_installer.log_event("SOLICITADO", user_id="u", user_email=" Alvo@X.com ")
    assert banco.tabelas["install_log"][0]["user_email"] == "alvo@x.com"
