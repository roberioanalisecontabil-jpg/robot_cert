import os
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

# Configurações de segurança
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 horas


def _get_secret_key() -> str:
    secret = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY não configurada no ambiente.")
    return secret

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None

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
    now = datetime.utcnow()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iss": "robot_cert_portal",
        "aud": "robot_cert_users",
        "nbf": now
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
        return TokenData(email=email, role=role)
    except (JWTError, RuntimeError):
        return None
