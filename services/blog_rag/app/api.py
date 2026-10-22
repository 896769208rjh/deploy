import json
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import BlogChunk, BlogSource
from app.security import Actor, assert_public_url, require_actor, require_admin

router = APIRouter(prefix="/api/blog", tags=["blog"])
_embedder = None


class SourceBody(BaseModel):
    type: str
    uri: str = Field(min_length=1, max_length=2000)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._title = False
        self.skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.skip = True
        if tag == "title":
            self._title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip = False
        if tag == "title":
            self._title = False

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self._title:
            self.title += data
        elif data.strip():
            self.parts.append(data.strip())


def plain_text(html: str) -> tuple[str, str]:
    parser = TextParser()
    parser.feed(html)
    text_value = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return parser.title.strip() or "未命名", text_value


def chunks_of(value: str, size: int = 800) -> list[str]:
    pieces = []
    start = 0
    while start < len(value):
        pieces.append(value[start : start + size])
        start += size - 100
    return [piece for piece in pieces if piece.strip()]


def embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(settings.embedding_model)
    return _embedder


def embed_texts(values: list[str]) -> list[list[float]]:
    return [list(map(float, vector)) for vector in embedder().embed(values)]


async def load_documents(source: BlogSource) -> list[tuple[str, str, str]]:
    allow_private = source.type == "internal"
    if not allow_private:
        assert_public_url(source.uri)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.get(source.uri)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = urljoin(source.uri, response.headers.get("location") or "")
            if not allow_private:
                assert_public_url(location)
            response = await client.get(location)
    if response.status_code >= 400:
        raise HTTPException(status_code=422, detail="数据源抓取失败")
    body = response.text
    if source.type == "rss":
        parsed = feedparser.parse(body)
        documents = []
        for entry in parsed.entries:
            title = entry.get("title") or "未命名"
            link = entry.get("link") or source.uri
            summary = entry.get("summary") or entry.get("description") or ""
            _, text_value = plain_text(summary)
            documents.append((link, title, text_value or summary))
        return documents
    if body.lstrip().startswith("[") or body.lstrip().startswith("{"):
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            return [(item.get("url") or source.uri, item.get("title") or "未命名", item.get("text") or "") for item in payload]
    title, text_value = plain_text(body)
    return [(source.uri, title, text_value)]


@router.get("/sources")
async def list_sources(_: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(select(BlogSource).order_by(BlogSource.last_ingested_at.desc().nulls_last()))
    return [{"id": item.id, "type": item.type, "uri": item.uri, "last_ingested_at": item.last_ingested_at} for item in rows]


@router.post("/sources", status_code=201)
async def add_source(body: SourceBody, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(actor)
    if body.type not in {"rss", "url", "internal"}:
        raise HTTPException(status_code=422, detail="类型只能是 rss、url 或 internal")
    item = BlogSource(type=body.type, uri=body.uri.strip())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "type": item.type, "uri": item.uri, "last_ingested_at": item.last_ingested_at}


@router.post("/ingest")
async def ingest(actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(actor)
    sources = list(await session.scalars(select(BlogSource)))
    total = 0
    for source in sources:
        documents = await load_documents(source)
        await session.execute(delete(BlogChunk).where(BlogChunk.source_id == source.id))
        rows: list[BlogChunk] = []
        texts: list[str] = []
        metas: list[tuple[str, str]] = []
        for url, title, content in documents:
            for piece in chunks_of(content):
                texts.append(piece)
                metas.append((url, title))
        if texts:
            vectors = embed_texts(texts)
            for (url, title), piece, vector in zip(metas, texts, vectors, strict=True):
                rows.append(BlogChunk(source_id=source.id, url=url, title=title[:300], text=piece, embedding=vector))
            session.add_all(rows)
            total += len(rows)
        source.last_ingested_at = datetime.now(timezone.utc)
    await session.commit()
    return {"chunks": total}


@router.post("/chat")
async def chat(body: ChatBody, _: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    vector = embed_texts([body.message])[0]
    distance = BlogChunk.embedding.cosine_distance(vector)
    rows = list(await session.scalars(select(BlogChunk).order_by(distance).limit(5)))
    sources = [{"title": row.title, "url": row.url} for row in rows]
    context = "\n\n".join(f"{row.title}\n{row.url}\n{row.text}" for row in rows)

    async def events():
        yield f"data: {json.dumps({'type': 'sources', 'items': sources}, ensure_ascii=False)}\n\n"
        if not rows:
            message = "还没有可检索的文章。请管理员先添加数据源并摄取。"
            yield f"data: {json.dumps({'type': 'content_token', 'content': message}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return
        if not settings.deepseek_api_key:
            message = "已经找到相关文章，但还没有配置 DEEPSEEK_API_KEY，暂时不能生成回答。"
            yield f"data: {json.dumps({'type': 'content_token', 'content': message}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return
        payload = {
            "model": settings.deepseek_model,
            "stream": True,
            "messages": [
                {"role": "system", "content": "根据给出的文章片段回答问题。答案里要提到文章标题。没有依据时直接说没找到。"},
                {"role": "user", "content": f"资料：\n{context}\n\n问题：{body.message}"},
            ],
        }
        headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream("POST", f"{settings.deepseek_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="ignore")[:300]
                    yield f"data: {json.dumps({'type': 'error', 'detail': detail}, ensure_ascii=False)}\n\n"
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                    reasoning = delta.get("reasoning_content")
                    content = delta.get("content")
                    if reasoning:
                        yield f"data: {json.dumps({'type': 'thinking_token', 'content': reasoning}, ensure_ascii=False)}\n\n"
                    if content:
                        yield f"data: {json.dumps({'type': 'content_token', 'content': content}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
