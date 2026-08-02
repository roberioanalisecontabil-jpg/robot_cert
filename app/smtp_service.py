import os
import base64
import hashlib
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

def _get_fernet_key() -> bytes:
    """
    Retorna a chave Fernet de 32 bytes.
    1. Tenta usar a variável ENCRYPTION_KEY do .env.
    2. Se não estiver configurada, deriva uma chave a partir de JWT_SECRET_KEY.
    """
    key_str = os.getenv("ENCRYPTION_KEY")
    if key_str:
        try:
            # Verifica se já é uma chave Fernet válida
            key = key_str.encode()
            Fernet(key)
            return key
        except Exception:
            # Deriva uma chave Fernet válida a partir do texto
            return base64.urlsafe_b64encode(hashlib.sha256(key_str.encode()).digest())
            
    # Fallback determinístico baseado na JWT_SECRET_KEY
    jwt_secret = os.getenv("JWT_SECRET_KEY", "default-certguard-fallback-secret-2026")
    return base64.urlsafe_b64encode(hashlib.sha256(jwt_secret.encode()).digest())

def encrypt_password(password: str) -> str:
    """Criptografa uma senha usando Fernet."""
    if not password:
        return ""
    try:
        f = Fernet(_get_fernet_key())
        return f.encrypt(password.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Erro na criptografia de senha (detalhes mascarados)")
        raise RuntimeError("Falha ao criptografar senha") from e

def decrypt_password(encrypted: str) -> str:
    """Descriptografa uma senha usando Fernet."""
    if not encrypted:
        return ""
    try:
        f = Fernet(_get_fernet_key())
        return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Erro na descriptografia de senha (detalhes mascarados)")
        return ""

def validate_smtp_config(use_tls: bool, use_ssl: bool) -> None:
    """Garante que STARTTLS (TLS) e SSL implícito não estejam ativos juntos."""
    if use_tls and use_ssl:
        raise ValueError("STARTTLS (TLS) e SSL não podem estar ativos simultaneamente.")

def send_smtp_email(
    host: str,
    port: int,
    user: str,
    password_enc: str,
    use_tls: bool,
    use_ssl: bool,
    from_email: str,
    to_email: str,
    subject: str,
    html_content: str
) -> None:
    """
    Conecta ao servidor SMTP e envia um e-mail.
    Garante o mascaramento de logs e prevenção de StartTLS/SSL concorrentes.
    """
    validate_smtp_config(use_tls, use_ssl)
    
    decrypted_password = decrypt_password(password_enc)
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email or user
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            
        with server:
            if not use_ssl and use_tls:
                server.starttls()
                
            if user and decrypted_password:
                server.login(user, decrypted_password)
                
            server.sendmail(from_email or user, [to_email], msg.as_string())
            
    except Exception as e:
        # Mascara o log de erro para nunca expor dados sensíveis ou senhas
        err_msg = str(e)
        # Substitui menções de credenciais e senhas nos logs por mascaramentos genéricos
        for secret in [user, decrypted_password]:
            if secret and len(secret) > 2:
                err_msg = err_msg.replace(secret, "***")
        logger.error(f"Falha ao enviar e-mail via SMTP (conexão ou credenciais incorretas): {err_msg}")
        raise RuntimeError(f"Erro no envio de e-mail SMTP: {err_msg}") from None
