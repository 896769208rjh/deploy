import base64
import hashlib
import uuid
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException

from app.config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value or value.startswith("enc:"):
        return value
    return "enc:" + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("enc:"):
        return value
    try:
        return _fernet().decrypt(value[4:].encode()).decode()
    except InvalidToken:
        return ""


@dataclass
class Actor:
    id: uuid.UUID
    role: str


def require_actor(
    x_internal_token: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_role: str = Header(default="user"),
) -> Actor:
    if x_internal_token != settings.internal_token or not x_user_id:
        raise HTTPException(status_code=401, detail="未授权")
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="用户标识不正确") from exc
    return Actor(id=user_id, role=x_user_role)
