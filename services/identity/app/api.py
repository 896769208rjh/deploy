import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def require_gateway(x_internal_token: str | None = Header(default=None)) -> None:
    if x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="未授权")


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    return value


@router.post("/register", response_model=AuthResponse)
async def register(
    body: RegisterRequest,
    _: None = Depends(require_gateway),
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    email = normalize_email(body.email)
    existing = await session.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="这个邮箱已经注册")
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name.strip(), role="user")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return AuthResponse(token=create_token(str(user.id), user.role, user.email), user=UserResponse.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    _: None = Depends(require_gateway),
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    email = normalize_email(body.email)
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    return AuthResponse(token=create_token(str(user.id), user.role, user.email), user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(
    _: None = Depends(require_gateway),
    x_user_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="缺少用户")
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="用户标识不正确") from exc
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
