import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

ERRO_SEM_CHAVE = (
    "ENCRYPTION_KEY não configurada. É a chave que cifra a senha SMTP em "
    "repouso e não tem substituto: sem ela o portal não sobe.\n"
    "Gere uma com:\n"
    '  python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"\n'
    "e defina ENCRYPTION_KEY no .env (local) ou no painel de variáveis de "
    "ambiente da plataforma (Vercel/Render) — o .env não sobe no deploy."
)


def _get_fernet_key() -> bytes:
    """
    Chave Fernet dedicada, sem derivação de fallback.

    O desenho anterior tinha dois fallbacks encadeados, ambos perigosos:

    1. Sem ENCRYPTION_KEY, derivava a chave da JWT_SECRET_KEY. Isso amarrava
       dois segredos de propósito diferente — girar a JWT, que é rotina de
       segurança, tornava toda senha SMTP já gravada indecifrável. E o erro era
       mudo: `decrypt_password` devolve "" quando falha, então o sintoma era
       "os alertas pararam de enviar", não "a chave mudou".

    2. Sem JWT_SECRET_KEY, caía numa constante escrita no repositório
       ("default-certguard-fallback-secret-2026"). Qualquer pessoa com o código
       e uma cópia do banco decifrava a senha SMTP.

    Havia ainda um terceiro caminho: uma ENCRYPTION_KEY que não fosse Fernet
    válida era silenciosamente convertida por SHA-256. Um erro de digitação
    passava a valer como chave — e mudava o resultado da cifragem sem avisar.

    Agora é exigida uma chave Fernet válida, ou levanta.
    """
    key_str = (os.getenv("ENCRYPTION_KEY") or "").strip()
    if not key_str:
        raise RuntimeError(ERRO_SEM_CHAVE)

    key = key_str.encode()
    try:
        Fernet(key)
    except Exception as e:
        raise RuntimeError(
            "ENCRYPTION_KEY definida mas inválida: precisa ser uma chave Fernet "
            "(32 bytes em base64 urlsafe, 44 caracteres). Gere uma com:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from e
    return key


def verificar_chave_configurada() -> None:
    """
    Falha cedo, no boot, em vez de no primeiro alerta.

    Sem isto o problema só apareceria quando alguém salvasse a configuração de
    SMTP ou o job diário tentasse enviar — possivelmente semanas depois do
    deploy que perdeu a variável.
    """
    _get_fernet_key()

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
