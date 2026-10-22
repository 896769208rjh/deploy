import base64
import hashlib
import ipaddress
import socket
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException

from app.config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
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
    return Actor(id=uuid.UUID(x_user_id), role=x_user_role)


def require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    if x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="未授权")


def assert_download_host(url: str) -> None:
    host = urlparse(url).hostname
    if not host:
        raise HTTPException(status_code=422, detail="视频地址不正确")
    if host in {"metadata.google.internal", "metadata.internal"}:
        raise HTTPException(status_code=422, detail="不能下载这个地址")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="视频地址无法解析") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(status_code=422, detail="不能下载这个地址")
