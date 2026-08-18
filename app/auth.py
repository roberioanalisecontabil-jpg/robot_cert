import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

# Configurações de segurança
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 horas

# Papel e estado da conta são coisas separadas desde 15/08/2026. Antes,
# desativar alguém gravava role='disabled' e apagava o papel — reativar um
# administrador virava adivinhação.
PAPEIS_VALIDOS = ("admin", "gestor", "user")


def conta_ativa(user: dict) -> bool:
    """
    A conta pode entrar e ser considerada em listagens de gente ativa?

    Mora aqui, e não em `main`, porque quem decide isso são dois módulos: o
    login e o envio de alertas. Duas cópias da regra divergiriam, e a que
    divergisse para o lado permissivo não daria sintoma nenhum — alguém
    desativado voltaria a receber e-mail sem ninguém notar.

    O valor legado 'disabled' continua barrando de propósito: numa base onde a
    migration ainda não rodou, olhar só `ativo` (ausente, logo verdadeiro por
    omissão) liberaria exatamente quem foi desativado. Na dúvida, barra.
    """
    if (user.get("role") or "").strip().lower() == "disabled":
        return False
    ativo = user.get("ativo")
    return True if ativo is None else bool(ativo)


def _get_secret_key() -> str:
    secret = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY não configurada no ambiente.")
    return secret

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    # Preenchido por `main._sessao_do_token`, que já leu a linha em `users` para
    # validar a sessão. Não vem do JWT e não é assinado: é só o `id` da conta
    # que acabou de ser conferida, carregado para as rotas não repetirem a
    # consulta. Fica None quando não houve leitura — sem Supabase configurado,
    # e no agente por X-API-Key, que não tem conta no portal.
    user_id: Optional[str] = None
    # Instante de emissão, este SIM vindo do token assinado. Comparado com
    # `users.senha_alterada_em` para uma troca de senha derrubar as sessões
    # abertas. None só em identidade sem JWT (agente, anônimo).
    emitido_em: Optional[datetime] = None
    # A senha atual foi definida por outra pessoa — cadastro ou redefinição
    # pelo admin. Enquanto for True, `require_auth` recusa toda rota que não
    # seja a de trocar a senha. Vem do banco, nunca do token.
    deve_trocar_senha: bool = False

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # O bcrypt espera bytes
        password_bytes = plain_password.encode('utf-8')
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    # O bcrypt espera bytes
    password_bytes = password.encode('utf-8')
    # Gera o salt e o hash com fator de custo (rounds) explícito recomendado pela OWASP
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    # Aware em vez de utcnow() (deprecado). O epoch gravado em exp/nbf não muda:
    # o python-jose converte datetimes via utctimetuple(), que já normaliza para
    # UTC — tokens emitidos antes e depois desta troca expiram no mesmo instante.
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iss": "robot_cert_portal",
        "aud": "robot_cert_users",
        "nbf": now,
        # `iat` é o claim padrão para "quando este token nasceu", e
        # `main._sessao_do_token` o compara com `users.senha_alterada_em` para
        # derrubar sessão aberta depois de uma troca de senha. O `nbf` acima
        # carrega o mesmo instante e serve de queda para tokens emitidos antes
        # de 17/08 — sem ela, todo mundo seria deslogado no deploy.
        "iat": now,
    })
    encoded_jwt = jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(
            token, 
            _get_secret_key(), 
            algorithms=[ALGORITHM],
            issuer="robot_cert_portal",
            audience="robot_cert_users"
        )
        email: str = payload.get("sub")
        role: str = payload.get("role")
        if email is None:
            return None
        # `iat` primeiro, `nbf` como queda: tokens emitidos antes de 17/08 não
        # têm `iat`, e sem a queda eles ficariam sem instante de emissão — o
        # que faria a comparação com `senha_alterada_em` não ter o que comparar.
        bruto = payload.get("iat") or payload.get("nbf")
        emitido = (
            datetime.fromtimestamp(int(bruto), tz=timezone.utc) if bruto else None
        )
        return TokenData(email=email, role=role, emitido_em=emitido)
    except (JWTError, RuntimeError, TypeError, ValueError, OSError, OverflowError):
        return None
