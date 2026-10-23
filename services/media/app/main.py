import asyncio

from fastapi import FastAPI
from sqlalchemy import text

from app.api import router
from app.db import Base, engine
from app.storage import ensure_bucket

app = FastAPI(title="media")
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                # Existing installations predate provider selection; keep old configurations on auto detection.
                await connection.execute(text("ALTER TABLE video_api_configs ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'auto'"))
            await asyncio.to_thread(ensure_bucket)
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError("media database unavailable") from last_error


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
