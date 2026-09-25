import ipaddress
import os
import smtplib
import socket
import ssl
import logging
from typing import List, Optional
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

class ErroSmtp(RuntimeError):
    """Falha ao enviar. As subclasses dizem QUAL, para a tela responder por
    classe sem repetir o texto do servidor (achado #35)."""


class ErroConexaoSmtp(ErroSmtp):
    """Não conectou: nome não resolve, porta fechada, tempo esgotado."""


class ErroTlsSmtp(ErroSmtp):
    """A camada segura falhou: certificado inválido, STARTTLS recusado."""


class ErroAutenticacaoSmtp(ErroSmtp):
    """O servidor recusou usuário/senha."""


_HOSTS_LOCAIS = ("localhost", "127.0.0.1", "::1")

# Portas em que um servidor SMTP atende. Qualquer outra é outra coisa —
# banco, RDP, SSH — e a tela de SMTP não é o lugar para falar com ela (#33).
PORTAS_SMTP = frozenset({25, 465, 587, 2525})


def _host_e_local(host: str) -> bool:
    return (host or "").strip().lower() in _HOSTS_LOCAIS


def validate_smtp_config(
    use_tls: bool, use_ssl: bool, host: Optional[str] = None, port: Optional[int] = None
) -> None:
    """Garante uma escolha de segurança coerente.

    STARTTLS e SSL juntos não existem. E "nenhuma" só existe para servidor
    LOCAL (achado #15): com um relay na própria máquina o tráfego não sai
    dela; com qualquer outro host, usuário e senha iriam em claro pela rede.
    `host=None` mantém a checagem antiga, para quem só quer os dois booleanos.
    `port`, quando informada, tem de ser de SMTP (#33).
    """
    if use_tls and use_ssl:
        raise ValueError("STARTTLS (TLS) e SSL não podem estar ativos simultaneamente.")
    if host is not None and not use_tls and not use_ssl and host.strip() and not _host_e_local(host):
        raise ValueError(
            "Sem TLS a senha do SMTP viajaria em claro. Escolha STARTTLS ou SSL/TLS; "
            "\"Nenhuma\" só vale para um servidor na própria máquina (localhost)."
        )
    if port is not None and int(port) not in PORTAS_SMTP:
        raise ValueError(f"Porta {port} não é de SMTP. Use 25, 465, 587 ou 2525.")


def resolver_enderecos(host: str) -> List[str]:
    """Os IPs para os quais o nome aponta. Separado para o teste substituir."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(sa[0]) for *_, sa in infos})


def exigir_destino_publico(host: str, port: int) -> None:
    """Recusa, ANTES de conectar, um destino que não é um servidor SMTP de
    verdade (achado #33).

    `PUT /api/settings` + `POST /smtp/test` era um primitivo de conexão TCP a
    partir do servidor, com o erro devolvido: metadados da nuvem em
    169.254.169.254, `127.0.0.1:<porta>`, a rede interna toda. Porta fora da
    lista de SMTP, endereço link-local, multicast, reservado ou loopback
    disfarçado são recusados sempre; rede privada só com o host em
    `config.SMTP_HOSTS_PERMITIDOS`; `localhost` passa (é o "servidor local"
    do lote 1). As mensagens não repetem o host nem o IP de propósito.
    """
    from app import config as _config

    if int(port) not in PORTAS_SMTP:
        raise ValueError(f"Porta {port} não é de SMTP. Use 25, 465, 587 ou 2525.")
    h = (host or "").strip().lower()
    if not h:
        raise ValueError("Servidor SMTP não configurado.")
    if _host_e_local(h):
        return
    try:
        ips = resolver_enderecos(h)
    except (socket.gaierror, OSError, UnicodeError) as e:
        logger.warning("Servidor SMTP não resolve: %s", e)
        raise ValueError("Não foi possível resolver o nome do servidor SMTP.") from None
    if not ips:
        raise ValueError("Não foi possível resolver o nome do servidor SMTP.")
    permitidos = {x.lower() for x in (getattr(_config, "SMTP_HOSTS_PERMITIDOS", None) or [])}
    for texto in ips:
        try:
            ip = ipaddress.ip_address(texto.split("%")[0])
        except ValueError:
            raise ValueError("Não foi possível resolver o nome do servidor SMTP.") from None
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("Servidor SMTP aponta para endereço interno ou reservado — recusado.")
        if ip.is_private and h not in permitidos:
            raise ValueError(
                "Servidor SMTP em rede interna não é permitido. Se for um relay da "
                "empresa, inclua-o em SMTP_HOSTS_PERMITIDOS no servidor."
            )


def _contexto_tls() -> ssl.SSLContext:
    """Contexto que VERIFICA o certificado do servidor e o nome do host.

    `smtplib` sem `context=` usa um contexto que não verifica nada: qualquer
    um no caminho apresentava um certificado próprio e recebia usuário e
    senha (achado #15).
    """
    return ssl.create_default_context()


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
    validate_smtp_config(use_tls, use_ssl, host=host)
    exigir_destino_publico(host, port)

    decrypted_password = decrypt_password(password_enc)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email or user
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        ctx = _contexto_tls()
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=10)

        with server:
            if not use_ssl and use_tls:
                server.starttls(context=ctx)

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
        logger.error(f"Falha ao enviar e-mail via SMTP: {type(e).__name__}: {err_msg}")
        raise _classificar(e, err_msg) from None


def _classificar(e: BaseException, texto: str) -> ErroSmtp:
    """Mapeia a exceção da `smtplib`/rede para a classe que a tela conhece."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return ErroAutenticacaoSmtp(texto)
    if isinstance(e, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return ErroTlsSmtp(texto)
    if isinstance(e, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
                      socket.gaierror, socket.timeout, TimeoutError, ConnectionError, OSError)):
        return ErroConexaoSmtp(texto)
    return ErroSmtp(texto)
