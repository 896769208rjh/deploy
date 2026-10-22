from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.security import decode_token

app = FastAPI(title="gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROUTES = (
    ("/api/auth", settings.identity_url),
    ("/api/workflow", settings.workflow_url),
    ("/api/media", settings.media_url),
    ("/api/blog", settings.blog_url),
    ("/api/bookmarks", settings.bookmark_url),
)

HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding"}


def is_public(method: str, path: str) -> bool:
    if method == "POST" and path in {"/api/auth/register", "/api/auth/login"}:
        return True
    if method == "GET" and (
        path == "/api/media/plaza"
        or path.startswith("/api/media/posts/")
        or path.startswith("/api/media/objects/")
        or path.startswith("/api/bookmarks/files/")
    ):
        return True
    return False


def upstream_for(path: str) -> str | None:
    for prefix, base in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return base
    return None


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if request.url.path.endswith("/stream"):
        return request.query_params.get("access_token")
    return None


@app.on_event("startup")
async def startup() -> None:
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.client.aclose()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    full_path = "/" + path
    base = upstream_for(full_path)
    if base is None:
        raise HTTPException(status_code=404, detail="没有这个接口")

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_HEADERS
        and key.lower() not in {"x-user-id", "x-user-role", "x-internal-token"}
    }
    headers["x-internal-token"] = settings.internal_token
    token = bearer_token(request)
    if token:
        payload = decode_token(token)
        headers["x-user-id"] = str(payload.get("sub", ""))
        headers["x-user-role"] = str(payload.get("role", "user"))
    elif not is_public(request.method, full_path):
        raise HTTPException(status_code=401, detail="请先登录")

    query = [(key, value) for key, value in request.query_params.multi_items() if key != "access_token"]
    target = base + full_path
    if query:
        target += "?" + urlencode(query)

    body = await request.body()
    client: httpx.AsyncClient = app.state.client
    try:
        upstream = await client.send(
            client.build_request(request.method, target, content=body, headers=headers),
            stream=True,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="下游服务暂时不可用") from exc

    content_type = upstream.headers.get("content-type", "")
    passthrough = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "cache-control", "x-accel-buffering"}
    }
    if "text/event-stream" in content_type:

        async def iterate():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(iterate(), status_code=upstream.status_code, headers=passthrough, media_type="text/event-stream")

    content = await upstream.aread()
    await upstream.aclose()
    return Response(content=content, status_code=upstream.status_code, headers=passthrough)
