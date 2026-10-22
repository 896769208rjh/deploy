import ipaddress
import socket
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Header, HTTPException

from app.config import settings


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


def require_admin(actor: Actor) -> None:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以管理博客数据源")


def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="只接受 http 或 https 网址")
    host = parsed.hostname.strip(".").lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise HTTPException(status_code=422, detail="这个地址不能抓取")
    infos = socket.getaddrinfo(host, None)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise HTTPException(status_code=422, detail="这个地址不能抓取")
