import uuid
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Post, VideoApiConfig
from app.security import Actor, decrypt_secret, encrypt_secret, require_actor, require_internal
from app.storage import local_path, presign, put_bytes
from app.video_catalog import PROVIDERS, ProviderId, resolve_provider, validate_model
from app.video_providers import generate_video, probe_video_models

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/objects/{key:path}")
async def read_object(key: str) -> FileResponse:
    try:
        path = local_path(key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="找不到文件") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="找不到文件")
    return FileResponse(path)


class ConfigBody(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    provider: ProviderId = "auto"


class ProbeBody(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(default="", max_length=500)
    provider: ProviderId = "auto"
    config_id: uuid.UUID | None = None


class GenerateBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    title: str = Field(default="", max_length=200)
    publish: bool = False
    run_id: uuid.UUID | None = None
    model: str = Field(default="", max_length=200)


class VisibilityBody(BaseModel):
    visibility: str


def config_payload(item: VideoApiConfig) -> dict:
    return {"id": item.id, "base_url": item.base_url, "has_api_key": bool(item.api_key_encrypted), "model": item.model, "provider": item.provider, "created_at": item.created_at}


def post_payload(item: Post) -> dict:
    return {
        "id": item.id,
        "author_id": item.author_id,
        "title": item.title,
        "prompt": item.prompt,
        "video_url": presign(item.video_key),
        "run_id": item.run_id,
        "visibility": item.visibility,
        "created_at": item.created_at,
    }


async def store_video(owner_id: uuid.UUID, prompt: str, title: str, visibility: str, run_id: uuid.UUID | None, data: bytes) -> Post:
    key = f"{owner_id}/{uuid.uuid4()}.mp4"
    put_bytes(key, data, "video/mp4")
    return Post(author_id=owner_id, title=title or prompt[:80], prompt=prompt, video_key=key, run_id=run_id, visibility=visibility)


@router.get("/providers")
async def list_providers(_: Actor = Depends(require_actor)) -> list[dict]:
    return [{"id": key, "name": info.name, "base_url": info.base_url, "hint": info.hint} for key, info in PROVIDERS.items()]


async def latest_config(session: AsyncSession, owner_id: uuid.UUID) -> VideoApiConfig:
    item = await session.scalar(
        select(VideoApiConfig).where(VideoApiConfig.owner_id == owner_id).order_by(VideoApiConfig.created_at.desc())
    )
    if item is None:
        raise HTTPException(status_code=409, detail="先填写视频接口地址和密钥")
    return item


@router.get("/configs")
async def list_configs(actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(select(VideoApiConfig).where(VideoApiConfig.owner_id == actor.id).order_by(VideoApiConfig.created_at.desc()))
    return [config_payload(item) for item in rows]


@router.post("/configs", status_code=201)
async def create_config(body: ConfigBody, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    if body.base_url.strip().lower() != "mock" and not body.api_key:
        raise HTTPException(status_code=422, detail="请填写接口密钥")
    kind = resolve_provider(body.base_url, body.provider)
    validate_model(body.model.strip(), kind)
    item = VideoApiConfig(
        owner_id=actor.id,
        base_url=body.base_url.strip(),
        api_key_encrypted=encrypt_secret(body.api_key) if body.api_key else "",
        model=body.model.strip(),
        provider=body.provider,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return config_payload(item)


@router.put("/configs/{config_id}")
async def update_config(
    config_id: uuid.UUID,
    body: ConfigBody,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = await session.get(VideoApiConfig, config_id)
    if item is None or item.owner_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这个配置")
    kind = resolve_provider(body.base_url, body.provider)
    validate_model(body.model.strip(), kind)
    if kind != "mock" and not body.api_key and not item.api_key_encrypted:
        raise HTTPException(status_code=422, detail="请填写接口密钥")
    if kind != "mock" and not body.api_key and (body.base_url.strip() != item.base_url or body.provider != item.provider):
        raise HTTPException(status_code=422, detail="更换接口地址或类型时，请重新填写该平台密钥")
    item.base_url = body.base_url.strip()
    if body.api_key:
        item.api_key_encrypted = encrypt_secret(body.api_key)
    item.model = body.model.strip()
    item.provider = body.provider
    await session.commit()
    await session.refresh(item)
    return config_payload(item)


@router.post("/configs/probe")
async def probe_models(body: ProbeBody, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    api_key = body.api_key.strip()
    if not api_key and body.config_id:
        config = await session.get(VideoApiConfig, body.config_id)
        if config is None or config.owner_id != actor.id:
            raise HTTPException(status_code=404, detail="找不到这个配置")
        if config.base_url != body.base_url.strip() or config.provider != body.provider:
            raise HTTPException(status_code=422, detail="更换接口时请重新填写密钥")
        api_key = decrypt_secret(config.api_key_encrypted)
    if body.base_url.strip().lower() != "mock" and not api_key:
        raise HTTPException(status_code=422, detail="请填写接口密钥")
    return await probe_video_models(body.base_url, api_key, body.provider)


async def generate_for(owner_id: uuid.UUID, body: GenerateBody, session: AsyncSession) -> Post:
    config = await latest_config(session, owner_id)
    model = body.model.strip() or config.model
    data = await generate_video(config.base_url, decrypt_secret(config.api_key_encrypted), body.prompt, model, config.provider)
    post = await store_video(owner_id, body.prompt, body.title, "public" if body.publish else "private", body.run_id, data)
    session.add(post)
    await session.commit()
    await session.refresh(post)
    return post


@router.post("/generate", status_code=201)
async def generate(body: GenerateBody, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    return post_payload(await generate_for(actor.id, body, session))


@router.post("/internal/generate", status_code=201)
async def generate_internal(
    body: GenerateBody,
    _: None = Depends(require_internal),
    x_user_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="缺少用户")
    post = await generate_for(uuid.UUID(x_user_id), body, session)
    return {"post_id": post.id, "video_url": presign(post.video_key)}


@router.get("/plaza")
async def plaza(_: None = Depends(require_internal), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(select(Post).where(Post.visibility == "public").order_by(Post.created_at.desc()).limit(60))
    return [post_payload(item) for item in rows]


@router.get("/profile")
async def profile(actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(select(Post).where(Post.author_id == actor.id).order_by(Post.created_at.desc()))
    return [post_payload(item) for item in rows]


@router.get("/posts/{post_id}")
async def get_post(
    post_id: uuid.UUID,
    _: None = Depends(require_internal),
    x_user_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = await session.get(Post, post_id)
    if item is None:
        raise HTTPException(status_code=404, detail="找不到这条视频")
    if item.visibility != "public" and str(item.author_id) != (x_user_id or ""):
        raise HTTPException(status_code=404, detail="找不到这条视频")
    return post_payload(item)


@router.post("/posts/{post_id}/visibility")
async def set_visibility(
    post_id: uuid.UUID,
    body: VisibilityBody,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if body.visibility not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="可见范围只能是公开或仅自己")
    item = await session.get(Post, post_id)
    if item is None or item.author_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这条视频")
    item.visibility = body.visibility
    await session.commit()
    await session.refresh(item)
    return post_payload(item)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: uuid.UUID, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> None:
    item = await session.get(Post, post_id)
    if item is None or item.author_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这条视频")
    await session.delete(item)
    await session.commit()
