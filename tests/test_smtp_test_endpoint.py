"""Rota POST /api/settings/smtp/test — o botão "Enviar Teste" da tela.

A rota chamava `send_smtp_email(...)`, mas esse nome nunca esteve entre os
imports de `app/main.py`: o arquivo importa apenas `encrypt_password` e
`validate_smtp_config` de `app.smtp_service`. Toda chamada levantava
NameError, e o usuário via "name 'send_smtp_email' is not defined".

Passou despercebido por dois motivos que se reforçam:

1. Nenhum teste tocava a rota, e um NameError dentro de uma função só aparece
   quando a função executa — importar o módulo não acusa nada.
2. O caminho dos alertas de verdade (`trigger_all_alerts`) funciona, porque
   `app/alert_state.py` importa `send_smtp_email` por conta própria. Então
   "os alertas enviam" e "o botão de teste envia" eram coisas diferentes, e a
   primeira funcionando escondia a segunda quebrada.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth, smtp_service
from app.settings_state import PortalSettings


def _admin() -> dict:
    tok = auth.create_access_token({"sub": "admin@exemplo.com", "role": "admin"})
    return {"Authorization": f"Bearer {tok}"}


def _configuracao_valida() -> PortalSettings:
    return PortalSettings(
        source_folder="",
        expired_folder="",
        machine_id="default",
        smtp_host="smtp.exemplo.com",
        smtp_port=587,
        smtp_user="portal@exemplo.com",
        smtp_password_encrypted="cifrado-qualquer",
        smtp_use_tls=True,
        smtp_use_ssl=False,
        smtp_from_email="portal@exemplo.com",
        smtp_alerts_enabled=True,
    )


def test_envio_de_teste_chega_ao_smtp(client: TestClient) -> None:
    """O caminho feliz: a rota tem de alcançar send_smtp_email, não estourar."""
    with patch("app.main.load_settings", _configuracao_valida):
        with patch.object(smtp_service, "send_smtp_email") as enviar:
            r = client.post(
                "/api/settings/smtp/test",
                json={"target_email": "destino@exemplo.com"},
                headers=_admin(),
            )

    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    enviar.assert_called_once()

    kwargs = enviar.call_args.kwargs
    assert kwargs["to_email"] == "destino@exemplo.com"
    assert kwargs["host"] == "smtp.exemplo.com"
    assert kwargs["from_email"] == "portal@exemplo.com"
    # A senha vai cifrada; quem decifra é o smtp_service.
    assert kwargs["password_enc"] == "cifrado-qualquer"


def test_erro_do_servidor_smtp_vira_400_com_a_mensagem(client: TestClient) -> None:
    """
    O texto do erro precisa chegar ao usuário: é por ele que se distingue
    "senha de app faltando" de "host errado".
    """
    with patch("app.main.load_settings", _configuracao_valida):
        with patch.object(
            smtp_service,
            "send_smtp_email",
            side_effect=Exception("535 5.7.8 Username and Password not accepted"),
        ):
            r = client.post(
                "/api/settings/smtp/test",
                json={"target_email": "destino@exemplo.com"},
                headers=_admin(),
            )

    assert r.status_code == 400
    assert "535" in r.json()["detail"]


def test_sem_host_configurado_recusa_antes_de_tentar(client: TestClient) -> None:
    vazio = PortalSettings(source_folder="", expired_folder="", machine_id="default")

    with patch("app.main.load_settings", lambda: vazio):
        with patch.object(smtp_service, "send_smtp_email") as enviar:
            r = client.post(
                "/api/settings/smtp/test",
                json={"target_email": "destino@exemplo.com"},
                headers=_admin(),
            )

    assert r.status_code == 400
    assert "não configurado" in r.json()["detail"].lower()
    enviar.assert_not_called()


def test_usuario_comum_nao_dispara_teste(client: TestClient) -> None:
    """Enviar e-mail em nome do portal é ação de admin."""
    tok = auth.create_access_token({"sub": "user@exemplo.com", "role": "user"})

    r = client.post(
        "/api/settings/smtp/test",
        json={"target_email": "destino@exemplo.com"},
        headers={"Authorization": f"Bearer {tok}"},
    )

    assert r.status_code == 403


def test_disparo_manual_de_alertas_responde(client: TestClient) -> None:
    """
    A rota vizinha, que funcionava. Fica aqui para que as duas passem a ser
    exercitadas juntas — foi a diferença entre elas que escondeu o defeito.
    """
    with patch("app.main.trigger_all_alerts", lambda: {"enviados": 0}):
        r = client.post("/api/settings/alerts/trigger", headers=_admin())

    assert r.status_code == 200
    assert r.json()["ok"] is True
