import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Bookmark
from app.security import Actor, assert_public_url, require_actor
from app.storage import local_path, presign, put_bytes

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


@router.get("/files/{key:path}")
async def read_file(key: str) -> FileResponse:
    try:
        path = local_path(key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="找不到图标") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="找不到图标")
    return FileResponse(path)
MAX_BYTES = 512 * 1024


class BookmarkBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.og_title = ""
        self.icons: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self.in_title = True
        if tag == "meta" and attr.get("property") == "og:title":
            self.og_title = attr.get("content", "")
        if tag == "meta" and attr.get("property") == "og:image":
            self.icons.append((2, attr.get("content", "")))
        if tag == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "")
            if "apple-touch-icon" in rel:
                self.icons.append((0, href))
            elif "icon" in rel:
                self.icons.append((1, href))

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False


async def read_limited(response: httpx.Response, truncate: bool = False) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            if truncate:
                return bytes(data[:MAX_BYTES])
            raise HTTPException(status_code=422, detail="响应超过 512KB")
    return bytes(data)


async def fetch(client: httpx.AsyncClient, url: str, hops: int = 0) -> tuple[bytes, str]:
    assert_public_url(url)
    response = await client.get(url, follow_redirects=False)
    if response.status_code in {301, 302, 303, 307, 308}:
        if hops >= 3:
            raise HTTPException(status_code=422, detail="重定向过多")
        location = response.headers.get("location")
        if not location:
            raise HTTPException(status_code=422, detail="重定向缺少地址")
        return await fetch(client, urljoin(url, location), hops + 1)
    if response.status_code >= 400:
        raise HTTPException(status_code=422, detail="页面抓取失败")
    return await read_limited(response, truncate=True), url


def payload(item: Bookmark) -> dict:
    return {
        "id": item.id,
        "url": item.url,
        "title": item.title,
        "favicon_url": presign(item.favicon_key),
        "created_at": item.created_at,
    }


@router.get("")
async def list_bookmarks(actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(select(Bookmark).where(Bookmark.owner_id == actor.id).order_by(Bookmark.created_at.desc()))
    return [payload(item) for item in rows]


@router.post("", status_code=201)
async def create_bookmark(body: BookmarkBody, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    page_url = body.url.strip()
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "ai-platform-bookmark"}) as client:
        try:
            html, final_url = await fetch(client, page_url)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=422, detail="抓取超时，请换一个更快的页面") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=422, detail="页面抓取失败") from exc
        parser = PageParser()
        parser.feed(html.decode("utf-8", errors="ignore"))
        title = (parser.og_title or "".join(parser.title_parts)).strip() or final_url
        candidates = [urljoin(final_url, href) for _, href in sorted(parser.icons) if href]
        candidates.append(urljoin(final_url, "/favicon.ico"))
        icon = b""
        content_type = "image/x-icon"
        for candidate in candidates:
            if candidate.startswith("data:"):
                continue
            try:
                data, _ = await fetch(client, candidate)
            except HTTPException:
                continue
            if data:
                icon = data
                if candidate.lower().endswith(".png"):
                    content_type = "image/png"
                elif candidate.lower().endswith((".jpg", ".jpeg")):
                    content_type = "image/jpeg"
                elif candidate.lower().endswith(".svg"):
                    content_type = "image/svg+xml"
                break
    key = ""
    if icon:
        key = f"{actor.id}/{uuid.uuid4()}"
        put_bytes(key, icon, content_type)
    item = Bookmark(owner_id=actor.id, url=page_url, title=title[:300], favicon_key=key)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return payload(item)


@router.delete("/{bookmark_id}", status_code=204)
async def delete_bookmark(
    bookmark_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> None:
    item = await session.get(Bookmark, bookmark_id)
    if item is None or item.owner_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这个书签")
    await session.delete(item)
    await session.commit()
