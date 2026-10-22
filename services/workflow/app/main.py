import asyncio

from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

import app.engine as engine_module
from app.api import router
from app.config import settings
from app.db import Base, engine

app = FastAPI(title="workflow")
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
    raise RuntimeError("workflow database unavailable") from last_error


@app.on_event("startup")
async def startup() -> None:
    await prepare_database()
    pool = AsyncConnectionPool(
        settings.checkpoint_database_url,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    engine_module.checkpointer = saver
    app.state.checkpoint_pool = pool


@app.on_event("shutdown")
async def shutdown() -> None:
    pool = getattr(app.state, "checkpoint_pool", None)
    if pool is not None:
        await pool.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
