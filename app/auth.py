import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

# Configurações de segurança JWT
SECRET_KEY = os.getenv("JWT_SECRET", "super_secret_key_change_me_in_production_123456")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 dias

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None

class User(BaseModel):
    id: str
    email: EmailStr
    role: str
    created_at: str

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str = "user"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_user_from_db(client, email: str) -> Optional[dict]:
    try:
        r = client.table("users").select("*").eq("email", email).execute()
        if r.data:
            return r.data[0]
    except Exception:
        pass
    return None

def create_user_in_db(client, user: UserCreate) -> Optional[dict]:
    hashed = get_password_hash(user.password)
    try:
        r = client.table("users").insert({
            "email": user.email,
            "password_hash": hashed,
            "role": user.role
        }).execute()
        if r.data:
            return r.data[0]
    except Exception:
        pass
    return None
