"""ENCRYPTION_KEY dedicada, sem fallback silencioso.

O desenho anterior tinha três caminhos de degradação, todos mudos:

1. Sem ENCRYPTION_KEY, derivava a chave da JWT_SECRET_KEY — girar a JWT
   (rotina de segurança) tornava a senha SMTP gravada indecifrável, e
   `decrypt_password` devolve "" em vez de levantar, então o sintoma era "os
   alertas pararam", não "a chave mudou".
2. Sem JWT_SECRET_KEY, caía numa constante escrita no repositório.
3. Uma ENCRYPTION_KEY malformada era convertida por SHA-256 — um erro de
   digitação virava chave válida e mudava o resultado da cifragem.

Nenhum deles levantava. Estes testes fixam que agora todos levantam.
"""

import pytest
from cryptography.fernet import Fernet

from app import smtp_service


def test_sem_chave_levanta_com_mensagem_acionavel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "uma-jwt-qualquer")

    with pytest.raises(RuntimeError) as exc:
        smtp_service._get_fernet_key()

    msg = str(exc.value)
    assert "ENCRYPTION_KEY" in msg
    assert "Fernet.generate_key" in msg, "a mensagem tem de dizer COMO gerar"


def test_sem_chave_nao_deriva_da_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    """O fallback perigoso: dois segredos de propósito diferente amarrados."""
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-que-antes-viraria-chave-de-cifra")

    with pytest.raises(RuntimeError):
        smtp_service.encrypt_password("qualquer-senha")


def test_chave_malformada_levanta_em_vez_de_ser_convertida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antes, um erro de digitação virava chave via SHA-256, sem avisar."""
    monkeypatch.setenv("ENCRYPTION_KEY", "isto-nao-e-uma-chave-fernet")

    with pytest.raises(RuntimeError) as exc:
        smtp_service._get_fernet_key()
    assert "inválida" in str(exc.value)


def test_chave_valida_faz_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    chave = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", chave)

    cifrada = smtp_service.encrypt_password("senha-do-smtp")
    assert cifrada != "senha-do-smtp"
    assert smtp_service.decrypt_password(cifrada) == "senha-do-smtp"


def test_senha_cifrada_com_outra_chave_nao_decifra(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O motivo de existir scripts/rotate_smtp_password.py: trocada a chave, o
    ciphertext antigo é irrecuperável — e falha devolvendo "", em silêncio.
    """
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    cifrada = smtp_service.encrypt_password("senha-original")

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert smtp_service.decrypt_password(cifrada) == ""


def test_verificacao_de_boot_levanta_sem_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        smtp_service.verificar_chave_configurada()


def test_boot_do_portal_recusa_sem_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A verificação está no lifespan: o portal não sobe sem a chave.

    Falhar aqui é o ponto — o desenho anterior subia e só quebrava semanas
    depois, no primeiro envio de alerta.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass
