import asyncio

from fastapi import FastAPI
from sqlalchemy import text

from app.api import router
from app.db import Base, engine

app = FastAPI(title="blog-rag")
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            async with engine.begin() as connection:
                await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await connection.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError("blog database unavailable") from last_error


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
