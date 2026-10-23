"""Text-to-video discovery rules. Protocol selection follows the endpoint, not the model brand."""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException

ProviderId = Literal["auto", "compatible", "compatible_json", "xai", "ark", "dashscope", "minimax", "kling", "vidu", "pixverse", "siliconflow", "zhipu", "tencent", "custom"]


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    models: tuple[str, ...] = ()
    hint: str = ""


PROVIDERS = {
    "compatible": Provider("视频兼容接口 / 中转（multipart）", "", hint="按中转商文档选择协议；此项使用 multipart 提交 /videos，支持任务查询和下载。"),
    "compatible_json": Provider("视频兼容接口 / 中转（JSON）", "", hint="使用 JSON 向 /videos 提交 model 和 prompt，再查询 /videos/{id}。"),
    "xai": Provider("xAI · Grok Imagine", "https://api.x.ai/v1", ("grok-imagine-video-1.5", "grok-imagine-video-1.5-lite", "grok-imagine-video")),
    "ark": Provider("火山方舟 · Seedance", "https://ark.cn-beijing.volces.com/api/v3", ("doubao-seedance-2-5-260628", "doubao-seedance-2-0-260128"), "也可填写方舟控制台中已开通的模型 ID 或 ep- 接入点 ID。"),
    "dashscope": Provider("阿里云百炼 · 万相", "", ("wan3.0-video", "wan3.0-video-prime", "wan2.7-t2v-2026-06-12", "wan2.6-t2v"), "请粘贴控制台的业务空间 API 地址（包含 /api/v1）；模型、地址和 API Key 必须属于同一地域。"),
    "minimax": Provider("MiniMax · 海螺 / H3", "https://api.minimax.io", ("MiniMax-H3", "MiniMax-H3-Max", "MiniMax-Hailuo-2.3", "MiniMax-Hailuo-02", "T2V-01-Director"), "国内账号请按控制台使用国内 API 地址，不同站点密钥不通用。"),
    "kling": Provider("快手 · 可灵 Kling", "https://api-beijing.klingai.com/v1", ("kling-v3", "kling-v2-6", "kling-v2-5-turbo"), "密钥填写 AccessKey:SecretKey，或填写有效的 JWT；按账号地域填写接口地址。"),
    "vidu": Provider("生数 · Vidu", "https://api.vidu.cn/ent/v2", ("viduq3-pro", "viduq3-turbo")),
    "pixverse": Provider("爱诗 · PixVerse", "https://app-api.pixverse.ai/openapi/v2", ("v6-max",), "模型 ID 以 PixVerse 控制台为准。"),
    "siliconflow": Provider("硅基流动 · 视频模型", "https://api.siliconflow.cn/v1", hint="从账号的模型列表筛选文生视频，使用视频任务提交和查询接口。"),
    "zhipu": Provider("智谱 · CogVideoX", "https://open.bigmodel.cn/api/paas/v4", ("cogvideox-3",)),
    "tencent": Provider("腾讯云 · 混元视频", "https://vclm.tencentcloudapi.com", ("hunyuan-video",), "密钥填写 SecretId:SecretKey。使用腾讯云混元文生视频 API，默认广州地域，提示词最多 200 字。"),
    "custom": Provider("自定义同步视频接口", "", hint="填写完整生成地址；接收 prompt/model，返回 video/* 或 video_url/url。"),
}

HOST_PROVIDERS = {
    "x.ai": "xai", "volces.com": "ark", "volcengineapi.com": "ark",
    "aliyuncs.com": "dashscope", "minimaxi.com": "minimax", "minimax.cn": "minimax",
    "minimax.io": "minimax", "minimax.chat": "minimax", "klingai.com": "kling",
    "vidu.com": "vidu", "vidu.cn": "vidu", "pixverse.ai": "pixverse",
    "siliconflow.cn": "siliconflow", "siliconflow.com": "siliconflow", "bigmodel.cn": "zhipu",
    "vclm.tencentcloudapi.com": "tencent",
}

NON_TEXT_VIDEO = re.compile(
    r"(?:^|[/_.-])(?:i2v|r2v|s2v|v2v|fl2v)(?:$|[/_.-])|image[-_ ]?to[-_ ]?video|image2video|"
    r"(?:image|video)[-_ ]?edit|motion[-_ ]?control|upscal|avatar|lip[-_ ]?sync|"
    r"seedream|embedding|rerank|transcrib|(?:^|[-_])tts(?:$|[-_])|"
    r"grok-imagine-image|minimax-hailuo-2\.3-fast|viduq3-(?:pro-fast|mix)|kling-v2-1(?!-master)|kling.*(?:omni|o1)", re.I,
)
VIDEO_FAMILY = re.compile(
    r"seedance|grok-imagine-video|(?:^|[/_-])wan[x\d.-]*(?:.*t2v|.*video)|"
    r"hailuo|minimax-h3|(?:^|[/_-])t2v[-_]|kling[-_/]v|vidu(?:q|[-_/])|"
    r"pixverse|cogvideox|hunyuan[-_]?video|ltx[-_.]?video|mochi[-_]|"
    r"(?:^|[/_-])veo(?:[-_.\d]|$)|sora[-_]|runway.*gen|gen[-_]\d.*(?:turbo|video)|ray[-_]\d|happyhorse.*t2v", re.I,
)


def resolve_provider(base_url: str, provider: str = "auto") -> str:
    if base_url.strip().lower() == "mock":
        return "mock"
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="接口地址需为 http/https 地址，密钥请填在密钥栏，不要放在网址中")
    host = parsed.hostname.lower()
    if host == "api.openai.com":
        raise HTTPException(status_code=422, detail="OpenAI 官方 Sora / Videos API 已于 2026-09-24 下线，请使用仍提供视频服务的平台")
    if provider != "auto":
        if provider not in PROVIDERS:
            raise HTTPException(status_code=422, detail="不支持的接口类型")
        return provider
    for domain, kind in HOST_PROVIDERS.items():
        if host == domain or host.endswith("." + domain):
            return kind
    path = parsed.path.rstrip("/")
    if path.endswith("/contents/generations/tasks"):
        return "ark"
    if path.endswith("/videos/generations"):
        return "xai"
    if path.endswith(("/generate", "/video_generation")):
        return "custom"
    return "compatible"


def _modalities(value) -> set[str]:
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, list):
        return {str(item).lower() for item in value}
    return set()


def is_text_to_video(item: dict | str, provider: str = "compatible") -> bool:
    if isinstance(item, str):
        item = {"id": item}
    mid = str(item.get("id") or item.get("model") or item.get("name") or "")
    if not mid or NON_TEXT_VIDEO.search(mid):
        return False
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    inputs = _modalities(item.get("input_modalities") or architecture.get("input_modalities"))
    outputs = _modalities(item.get("output_modalities") or architecture.get("output_modalities"))
    if inputs and "text" not in inputs:
        return False
    if outputs:
        return "video" in outputs
    capabilities = item.get("capabilities") or []
    if isinstance(capabilities, dict):
        if capabilities.get("text_to_video") is False:
            return False
        if capabilities.get("text_to_video") is True:
            return True
    elif isinstance(capabilities, list) and any(str(cap).lower() in {"text-to-video", "text_to_video", "t2v"} for cap in capabilities):
        return True
    if provider == "pixverse" and re.fullmatch(r"v\d+(?:\.\d+)?(?:-max)?", mid):
        return True
    return bool(VIDEO_FAMILY.search(mid))


def filter_models(payload, provider: str) -> tuple[list[dict], int]:
    raw = payload if isinstance(payload, list) else payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise HTTPException(status_code=502, detail="模型列表格式不正确，需要 data/models 数组")
    found: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, (dict, str)) or not is_text_to_video(item, provider):
            continue
        entry = {"id": item} if isinstance(item, str) else item
        mid = str(entry.get("id") or entry.get("model") or entry.get("name"))
        found[mid] = {"id": mid, "name": str(entry.get("name") or mid), "owned_by": str(entry.get("owned_by") or ""), "source": "discovered"}
    return list(found.values()), len(raw) - len(found)


def validate_model(model: str, provider: str) -> None:
    if provider == "mock":
        return
    if not model and provider != "custom":
        raise HTTPException(status_code=422, detail="请选择或填写文生视频模型 ID")
    if NON_TEXT_VIDEO.search(model) or re.search(r"^(?:gpt-|o[134][-\d]|claude-|deepseek-|qwen|glm-|grok-[1-9]|dall-e|flux|stable-diffusion)", model, re.I):
        raise HTTPException(status_code=422, detail="该模型不能在当前文字生成视频页面使用，请选择文生视频模型")
