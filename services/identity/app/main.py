import asyncio
import logging

from fastapi import FastAPI
from sqlalchemy import select

from app.config import settings
from app.api import router
from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password

logger = logging.getLogger("identity")
app = FastAPI(title="identity")
app.include_router(router)


async def prepare_database() -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError("identity database unavailable") from last_error


async def seed_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        return
    email = settings.admin_email.strip().lower()
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing:
            return
        session.add(
            User(
                email=email,
                password_hash=hash_password(settings.admin_password),
                display_name="管理员",
                role="admin",
            )
        )
        await session.commit()
        logger.info("seeded admin %s", email)


@app.on_event("startup")
async def startup() -> None:
    await prepare_database()
    await seed_admin()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
