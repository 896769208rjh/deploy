"""Provider-specific task submission, polling and authenticated video retrieval."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from app.config import settings
from app.security import assert_download_host
from app.video_catalog import PROVIDERS, filter_models, resolve_provider, validate_model

SUFFIXES = (
    "/services/aigc/video-generation/video-synthesis", "/contents/generations/tasks",
    "/video/text/generate", "/videos/generations", "/videos/text2video", "/video_generation",
    "/chat/completions", "/video/submit", "/videos/submit", "/text2video", "/videos", "/models",
)
DEFAULT_PATH = {"ark": "/api/v3", "dashscope": "/api/v1", "vidu": "/ent/v2", "pixverse": "/openapi/v2", "zhipu": "/api/paas/v4"}
FAILED = {"failed", "fail", "failure", "error", "expired", "cancelled", "canceled", "rejected", "7", "8"}
SUCCEEDED = {"done", "completed", "succeeded", "success", "succeed", "1"}


def api_root(base_url: str, provider: str) -> str:
    parsed = urlsplit(base_url.strip().rstrip("/"))
    path = parsed.path.rstrip("/")
    for suffix in SUFFIXES:
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    if not path:
        path = DEFAULT_PATH.get(provider, "" if provider in {"minimax", "custom"} else "/v1")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def auth_headers(provider: str, api_key: str) -> dict[str, str]:
    if provider == "pixverse":
        return {"API-KEY": api_key, "Ai-trace-id": str(uuid.uuid4())}
    if provider == "vidu":
        return {"Authorization": f"Token {api_key}"}
    if provider == "kling" and ":" in api_key:
        access, secret = api_key.split(":", 1)
        if not access or not secret:
            raise HTTPException(status_code=422, detail="可灵密钥请使用 AccessKey:SecretKey 格式")
        def encode(value: bytes) -> str:
            return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        now = int(time.time())
        parts = [encode(b'{"alg":"HS256","typ":"JWT"}'), encode(json.dumps({"iss": access, "exp": now + 1800, "nbf": now - 5}).encode())]
        signed = ".".join(parts)
        api_key = signed + "." + encode(hmac.new(secret.encode(), signed.encode(), hashlib.sha256).digest())
    return {"Authorization": f"Bearer {api_key}"}


def tencent_request(base_url: str, api_key: str, body: dict, action: str) -> tuple[bytes, dict[str, str]]:
    credentials = api_key.split(":", 1)
    if len(credentials) != 2 or not all(credentials):
        raise HTTPException(status_code=422, detail="腾讯云密钥请使用 SecretId:SecretKey 格式")
    secret_id, secret_key = credentials
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
    host = urlsplit(base_url).netloc
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    canonical = "\n".join(["POST", "/", "", f"content-type:application/json\nhost:{host}\n", "content-type;host", hashlib.sha256(content).hexdigest()])
    scope = f"{date}/vclm/tc3_request"
    to_sign = "\n".join(["TC3-HMAC-SHA256", str(timestamp), scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("TC3" + secret_key).encode()
    for piece in (date, "vclm", "tc3_request"):
        key = hmac.new(key, piece.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return content, {
        "Authorization": f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, SignedHeaders=content-type;host, Signature={signature}",
        "Content-Type": "application/json", "Host": host,
        "X-TC-Action": action, "X-TC-Version": "2024-05-23",
        "X-TC-Region": "ap-guangzhou", "X-TC-Timestamp": str(timestamp),
    }


def _error(payload: dict, api_key: str) -> str:
    error = payload.get("error") or payload.get("Error") or payload.get("base_resp") or {}
    if isinstance(error, dict):
        text = error.get("message") or error.get("Message") or error.get("status_msg") or error.get("code")
    else:
        text = error
    text = str(text or payload.get("ErrorMessage") or payload.get("task_status_msg") or payload.get("message") or payload.get("ErrMsg") or payload.get("reason") or payload.get("err_code") or "接口返回错误")
    for secret in [api_key, *api_key.split(":")]:
        if secret:
            text = text.replace(secret, "***")
    return text[:300]


def parse_response(response: httpx.Response, api_key: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"视频服务返回非 JSON 响应（HTTP {response.status_code}），请检查接口地址") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="视频服务响应格式不正确")
    if isinstance(payload.get("Response"), dict) and payload["Response"].get("Error"):
        raise HTTPException(status_code=502, detail=f"腾讯云拒绝请求：{_error(payload['Response'], api_key)}")
    base_resp = payload.get("base_resp") or {}
    business_error = (isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0, "0")) or payload.get("ErrCode") not in (None, 0, "0") or payload.get("code") not in (None, "", 0, "0", 200, "200")
    if response.is_error or business_error or payload.get("error"):
        raise HTTPException(status_code=502, detail=f"视频服务拒绝请求（HTTP {response.status_code}）：{_error(payload, api_key)}")
    return payload


async def probe_video_models(base_url: str, api_key: str, provider: str = "auto") -> dict:
    kind = resolve_provider(base_url, provider)
    if kind == "mock":
        return {"models": [{"id": "mock", "name": "样片（mock）", "source": "preset"}], "endpoint_type": kind, "source": "preset", "filtered_count": 0}
    info = PROVIDERS[kind]
    # These native APIs do not expose an OpenAI-compatible video model listing.
    if kind not in {"compatible", "compatible_json", "xai", "ark", "siliconflow"}:
        return {"models": [{"id": mid, "name": mid, "source": "preset"} for mid in info.models], "endpoint_type": kind, "source": "preset", "filtered_count": 0, "hint": "以下是官方文生视频预设，未验证账号权限；也可手动填写控制台模型 ID。" + info.hint}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(api_root(base_url, kind) + "/models", headers=auth_headers(kind, api_key))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="无法读取模型列表，请检查网络、接口地址和密钥") from exc
    if response.status_code in {404, 405}:
        return {"models": [{"id": mid, "name": mid, "source": "preset"} for mid in info.models], "endpoint_type": kind, "source": "preset", "filtered_count": 0, "hint": "该接口没有模型列表；预设未验证账号权限，也可手动填写模型 ID。"}
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="模型列表返回了非 JSON 内容，请填写 API 地址") from exc
    if response.is_error:
        detail = _error(payload, api_key) if isinstance(payload, dict) else "请检查密钥及模型列表权限"
        raise HTTPException(status_code=502, detail=f"模型列表读取失败（HTTP {response.status_code}）：{detail}")
    models, removed = filter_models(payload, kind)
    if not models and info.models:
        return {"models": [{"id": mid, "name": mid, "source": "preset"} for mid in info.models], "endpoint_type": kind, "source": "preset", "filtered_count": removed, "hint": "接口列表未返回可识别的文生视频模型；以下为官方预设，未验证账号权限，也可填写控制台模型 ID。"}
    return {"models": models, "endpoint_type": kind, "source": "discovered", "filtered_count": removed, "hint": "已筛选文生视频模型；实际调用受账号权限、额度及平台服务状态影响。" if models else "没有识别到文生视频模型；已过滤聊天、图片和图生视频模型。可填写平台确认支持的模型 ID。"}


@dataclass
class VideoTask:
    create_url: str
    body: dict
    poll_url: str
    poll_method: str = "GET"
    poll_body: dict | None = None
    multipart: bool = False
    content_url: str = ""


def make_task(base_url: str, kind: str, model: str, prompt: str) -> VideoTask:
    root = api_root(base_url, kind)
    body = {"model": model, "prompt": prompt}
    if kind == "tencent":
        if model != "hunyuan-video":
            raise HTTPException(status_code=422, detail="腾讯云混元直连接口请选择 hunyuan-video")
        if len(prompt.strip()) > 200:
            raise HTTPException(status_code=422, detail="腾讯云混元视频提示词不能超过 200 个字符")
        endpoint = urlunsplit((*urlsplit(base_url)[:2], "/", "", ""))
        return VideoTask(endpoint, {"Prompt": prompt, "Resolution": "720p"}, endpoint, "POST", {"JobId": "{id}"})
    if kind == "ark":
        endpoint = root + "/contents/generations/tasks"
        return VideoTask(endpoint, {"model": model, "content": [{"type": "text", "text": prompt}]}, endpoint + "/{id}")
    if kind == "dashscope":
        parameters = {"duration": 5, "resolution": "720P", "ratio": "16:9"} if model.startswith(("wan3.", "wan2.7", "happyhorse")) else {"duration": 5, "size": "1280*720"}
        return VideoTask(root + "/services/aigc/video-generation/video-synthesis", {"model": model, "input": {"prompt": prompt}, "parameters": parameters}, root + "/tasks/{id}")
    if kind == "minimax":
        root = root.removesuffix("/v1").removesuffix("/v2")
        if model.lower().startswith("minimax-h3"):
            return VideoTask(root + "/v2/video_generation", {"model": model, "content": [{"type": "text", "text": prompt}], "resolution": "768P", "duration": 5, "ratio": "16:9"}, root + "/v2/query/video_generation/{id}")
        return VideoTask(root + "/v1/video_generation", {**body, "duration": 6, "resolution": "720P" if model.upper().startswith("T2V-") else "768P"}, root + "/v1/query/video_generation?task_id={id}")
    if kind == "kling":
        endpoint = root + "/videos/text2video"
        return VideoTask(endpoint, {"model_name": model, "prompt": prompt, "duration": "5", "mode": "pro", "aspect_ratio": "16:9"}, endpoint + "/{id}")
    if kind == "vidu":
        return VideoTask(root + "/text2video", {**body, "style": "general", "duration": 5, "aspect_ratio": "16:9", "resolution": "720p"}, root + "/tasks/{id}/creations")
    if kind == "pixverse":
        return VideoTask(root + "/video/text/generate", {**body, "duration": 5, "quality": "720p", "aspect_ratio": "16:9"}, root + "/video/result/{id}")
    if kind == "siliconflow":
        return VideoTask(root + "/video/submit", {**body, "image_size": "1280x720"}, root + "/video/status", "POST", {"requestId": "{id}"})
    if kind == "zhipu":
        if len(prompt) > 512:
            raise HTTPException(status_code=422, detail="智谱视频提示词不能超过 512 个字符")
        return VideoTask(root + "/videos/generations", body, root + "/async-result/{id}")
    if kind == "xai":
        return VideoTask(root + "/videos/generations", body, root + "/videos/{id}")
    if kind == "custom":
        return VideoTask(base_url.strip().rstrip("/"), {"prompt": prompt, **({"model": model} if model else {})}, "")
    if kind == "compatible_json":
        return VideoTask(root + "/videos", body, root + "/videos/{id}")
    return VideoTask(root + "/videos", {**body, "seconds": "4", "size": "1280x720"}, root + "/videos/{id}", multipart=True, content_url=root + "/videos/{id}/content")


def _task_data(payload: dict, kind: str) -> dict:
    key = {"ark": "", "dashscope": "output", "kling": "data", "pixverse": "Resp", "tencent": "Response"}.get(kind)
    if kind == "minimax" and isinstance(payload.get("task"), dict):
        return payload["task"]
    data = payload.get(key, payload) if key else payload
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="视频任务响应格式不正确")
    return data


def _video_url(data: dict) -> str:
    for key in ("video_url", "url", "download_url", "ResultVideoUrl"):
        if isinstance(data.get(key), str) and data[key]:
            return data[key]
    for key in ("content", "video", "result", "results", "task_result", "output", "data"):
        if isinstance(data.get(key), dict):
            found = _video_url(data[key])
            if found:
                return found
    for key in ("videos", "creations", "video_result", "data"):
        for value in data.get(key, []) if isinstance(data.get(key), list) else []:
            if isinstance(value, dict) and (found := _video_url(value)):
                return found
    return ""


async def download_video(client: httpx.AsyncClient, url: str) -> bytes:
    # CDN requests never receive provider credentials; validate every redirect.
    for _ in range(5):
        assert_download_host(url)
        response = await client.get(url, follow_redirects=False)
        if response.is_redirect and response.headers.get("location"):
            url = urljoin(url, response.headers["location"])
            continue
        if response.is_error or not response.content:
            raise HTTPException(status_code=502, detail="成片下载失败")
        media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        is_mp4 = len(response.content) >= 12 and response.content[4:8] == b"ftyp"
        if not media_type.startswith("video/") and not is_mp4:
            raise HTTPException(status_code=502, detail="下载地址未返回视频文件")
        return response.content
    raise HTTPException(status_code=502, detail="成片下载重定向过多")


async def generate_video(base_url: str, api_key: str, prompt: str, model: str = "", provider: str = "auto", *, client: httpx.AsyncClient | None = None) -> bytes:
    kind = resolve_provider(base_url, provider)
    if kind == "mock":
        path = Path(settings.sample_path)
        if not path.is_file():
            raise HTTPException(status_code=500, detail="样片还没有准备好")
        return path.read_bytes()
    validate_model(model, kind)
    if not api_key:
        raise HTTPException(status_code=422, detail="请填写视频接口密钥")
    if client is None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as owned:
            return await generate_video(base_url, api_key, prompt, model, provider, client=owned)
    task = make_task(base_url, kind, model, prompt)
    headers = auth_headers(kind, api_key)
    if kind == "dashscope":
        headers["X-DashScope-Async"] = "enable"
    task_id = ""
    try:
        kwargs = {"files": {key: (None, str(value)) for key, value in task.body.items()}} if task.multipart else {"json": task.body}
        if kind == "tencent":
            content, headers = tencent_request(base_url, api_key, task.body, "SubmitHunyuanToVideoJob")
            kwargs = {"content": content}
        response = await client.post(task.create_url, headers=headers, **kwargs)
        if not response.is_error and response.headers.get("content-type", "").startswith("video/"):
            if not response.content:
                raise HTTPException(status_code=502, detail="视频接口返回了空文件")
            return response.content
        payload = parse_response(response, api_key)
        data = _task_data(payload, kind)
        task_id = str(data.get("task_id") or data.get("id") or data.get("request_id") or data.get("requestId") or data.get("video_id") or data.get("JobId") or "")
        deadline = time.monotonic() + settings.video_timeout_seconds
        while True:
            status = str(data.get("task_status") or data.get("status") or data.get("state") or data.get("Status") or "").lower()
            if status in FAILED:
                raise HTTPException(status_code=502, detail=f"视频生成失败（任务 {task_id}）：{_error(data, api_key)}")
            video_url = _video_url(data)
            if video_url and (not status or status in SUCCEEDED):
                return await download_video(client, video_url)
            if status in SUCCEEDED:
                if kind == "minimax" and data.get("file_id"):
                    root = api_root(base_url, kind).removesuffix("/v1").removesuffix("/v2")
                    result = await client.get(root + "/v1/files/retrieve", params={"file_id": data["file_id"]}, headers=headers)
                    file_data = parse_response(result, api_key).get("file", {})
                    if file_data.get("download_url"):
                        return await download_video(client, file_data["download_url"])
                elif task.content_url and task_id:
                    content = await client.get(task.content_url.format(id=quote(task_id, safe="")), headers=headers)
                    if not content.is_error and content.content and content.headers.get("content-type", "").startswith("video/"):
                        return content.content
                raise HTTPException(status_code=502, detail=f"任务 {task_id} 已完成，但接口没有返回可下载的视频")
            if not task.poll_url or not task_id:
                raise HTTPException(status_code=502, detail="视频服务没有返回成片地址或任务 ID，请检查所选接口类型")
            if time.monotonic() >= deadline:
                raise HTTPException(status_code=504, detail=f"等待视频生成超时（任务 {task_id}），平台可能仍在生成，请先查询该任务，避免重复计费")
            await asyncio.sleep(settings.video_poll_interval_seconds)
            poll_headers = auth_headers(kind, api_key)
            kwargs = {"json": {key: value.replace("{id}", task_id) for key, value in task.poll_body.items()}} if task.poll_body else {}
            if kind == "tencent":
                content, poll_headers = tencent_request(base_url, api_key, kwargs["json"], "DescribeHunyuanToVideoJob")
                kwargs = {"content": content}
            response = await client.request(task.poll_method, task.poll_url.format(id=quote(task_id, safe="")), headers=poll_headers, **kwargs)
            data = _task_data(parse_response(response, api_key), kind)
    except httpx.HTTPError as exc:
        suffix = f"（任务 {task_id}；请先查询该任务，避免重复计费）" if task_id else "；若提交已被平台接收，请先检查平台任务记录"
        raise HTTPException(status_code=502, detail=f"视频服务连接失败{suffix}") from exc
