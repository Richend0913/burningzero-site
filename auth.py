"""BURNING ZERO — JWT authentication helpers."""

import os
import time
from datetime import datetime, timedelta

import bcrypt
import jwt

# Secret key — in production, use env var
SECRET_KEY = os.environ.get("BZ_JWT_SECRET", "bz_s3cret_k3y_ch4nge_in_pr0d_2026")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72

ADMIN_EMAIL = "richend0913@gmail.com"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "is_admin": email == ADMIN_EMAIL,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def is_admin(email: str) -> bool:
    return email == ADMIN_EMAIL
