import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Annotated, TypedDict

import httpx
import litellm
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.graph_util import render_template, safe_error, secrets_in
from app.hub import hub
from app.models import WorkflowDefinition, WorkflowNodeMetric, WorkflowRun
from app.security import decrypt_secret

litellm.suppress_debug_info = True

Emit = Callable[[dict], Awaitable[None]]
checkpointer = None
TASKS: set[asyncio.Task] = set()

NODE_TYPES = {
    "llm": "llm",
    "LLMNode": "llm",
    "human": "human",
    "HumanNode": "human",
    "condition": "condition",
    "ConditionNode": "condition",
    "http": "http",
    "HTTPNode": "http",
    "media": "media",
    "MediaNode": "media",
    "code": "code",
    "CodeNode": "code",
}


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def keep_new(left: str | None, right: str | None) -> str:
    return right if right not in (None, "") else (left or "")


class GraphState(TypedDict):
    run_input: str
    last_output: Annotated[str, keep_new]
    outputs: Annotated[dict, merge_dicts]


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


def node_type(node: dict) -> str:
    raw = node.get("type") or (node.get("data") or {}).get("nodeType") or ""
    return NODE_TYPES.get(raw, raw)


async def _metrics_event(node_id: str, node_kind: str, started: float, prompt_tokens: int, completion_tokens: int, reasoning_tokens: int) -> dict:
    duration_ms = int((time.monotonic() - started) * 1000)
    seconds = duration_ms / 1000 or 0.001
    counted = completion_tokens or reasoning_tokens
    return {
        "type": "node_end",
        "node_id": node_id,
        "node_type": node_kind,
        "metrics": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "duration_ms": duration_ms,
            "tokens_per_second": round(counted / seconds, 1),
        },
    }


def make_llm(node_id: str, data: dict, emit: Emit):
    async def run(state: GraphState) -> dict:
        started = time.monotonic()
        await emit({"type": "node_start", "node_id": node_id, "node_type": "LLMNode"})
        model = (data.get("model") or "deepseek-chat").strip()
        user_text = render_template(data.get("userPrompt") or "{{input}}", state.get("run_input", ""), state.get("last_output", ""))
        if not user_text.strip():
            user_text = state.get("last_output") or state.get("run_input") or ""
        system_prompt = data.get("systemPrompt") or "你是创作助手，回答简洁、具体。"
        prompt_tokens = 0
        completion_tokens = 0
        reasoning_tokens = 0
        content_parts: list[str] = []

        if model == "mock":
            for piece in ("先看这一步要完成的画面。", "再把它收成可以直接使用的句子。"):
                reasoning_tokens += 1
                await emit({"type": "thinking_token", "node_id": node_id, "content": piece})
                await asyncio.sleep(0.05)
            text = f"电影感镜头，{user_text or '一个人走进雨里'}，柔和侧光，镜头缓慢推进。"
            completion_tokens = 1
            content_parts.append(text)
            await emit({"type": "content_token", "node_id": node_id, "content": text})
        else:
            api_base = (data.get("apiBase") or "").strip()
            api_key = decrypt_secret(data.get("apiKey") or "")
            if not api_key:
                raise ValueError("这个模型节点还没有填写密钥")
            kwargs = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "stream": True,
                "timeout": 180,
                "api_key": api_key,
            }
            kwargs["model"] = model if model.startswith("openai/") or not api_base else f"openai/{model}"
            if api_base:
                kwargs["api_base"] = api_base
            stream = await litellm.acompletion(**kwargs)
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = choices[0].delta
                    extra = getattr(delta, "model_extra", None) or {}
                    reasoning = getattr(delta, "reasoning_content", None) or extra.get("reasoning_content")
                    content = getattr(delta, "content", None) or extra.get("content")
                    if reasoning:
                        reasoning_tokens += 1
                        await emit({"type": "thinking_token", "node_id": node_id, "content": reasoning})
                    if content:
                        completion_tokens += 1
                        content_parts.append(content)
                        await emit({"type": "content_token", "node_id": node_id, "content": content})
                usage = getattr(chunk, "usage", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_tokens", None) or prompt_tokens
                    reported = getattr(usage, "completion_tokens", None)
                    if reported:
                        completion_tokens = reported
                    details = getattr(usage, "completion_tokens_details", None)
                    if details and getattr(details, "reasoning_tokens", None):
                        reasoning_tokens = details.reasoning_tokens

        text = "".join(content_parts).strip()
        await emit(await _metrics_event(node_id, "LLMNode", started, prompt_tokens, completion_tokens, reasoning_tokens))
        return {"last_output": text, "outputs": {node_id: text}}

    return run


def make_human(node_id: str, emit: Emit):
    async def run(state: GraphState) -> dict:
        decision = interrupt({"node_id": node_id, "output": state.get("last_output", "")})
        started = time.monotonic()
        await emit({"type": "node_start", "node_id": node_id, "node_type": "HumanNode"})
        if not isinstance(decision, dict):
            decision = {"decision": "approve", "value": str(decision)}
        text = "" if decision.get("decision") == "reject" else (decision.get("value") or state.get("last_output") or "")
        await emit(await _metrics_event(node_id, "HumanNode", started, 0, 0, 0))
        return {"last_output": text, "outputs": {node_id: text}}

    return run


def make_http(node_id: str, data: dict, emit: Emit):
    async def run(state: GraphState) -> dict:
        started = time.monotonic()
        await emit({"type": "node_start", "node_id": node_id, "node_type": "HTTPNode"})
        method = (data.get("method") or "GET").upper()
        url = render_template(data.get("url") or "", state.get("run_input", ""), state.get("last_output", ""))
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP 节点需要以 http 开头的网址")
        body = render_template(data.get("body") or "", state.get("run_input", ""), state.get("last_output", ""))
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, url, content=body.encode() if body and method != "GET" else None)
        text = response.text[:4000]
        await emit({"type": "content_token", "node_id": node_id, "content": text[:500]})
        await emit(await _metrics_event(node_id, "HTTPNode", started, 0, 0, 0))
        return {"last_output": text, "outputs": {node_id: text}}

    return run


def make_media(node_id: str, data: dict, emit: Emit, owner_id: uuid.UUID, run_id: uuid.UUID):
    async def run(state: GraphState) -> dict:
        started = time.monotonic()
        await emit({"type": "node_start", "node_id": node_id, "node_type": "MediaNode"})
        prompt = render_template(data.get("prompt") or "{{prev}}", state.get("run_input", ""), state.get("last_output", ""))
        if not prompt.strip():
            prompt = state.get("last_output") or state.get("run_input") or ""
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                f"{settings.media_url}/api/media/internal/generate",
                json={"prompt": prompt, "title": prompt[:80], "run_id": str(run_id)},
                headers={"x-internal-token": settings.internal_token, "x-user-id": str(owner_id)},
            )
        if response.status_code >= 400:
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise RuntimeError(detail or "视频生成失败")
        payload = response.json()
        text = payload.get("video_url") or ""
        await emit({"type": "content_token", "node_id": node_id, "content": text})
        await emit(await _metrics_event(node_id, "MediaNode", started, 0, 0, 0))
        return {"last_output": text, "outputs": {node_id: text}}

    return run


def build_graph(graph_json: dict, emit: Emit, owner_id: uuid.UUID, run_id: uuid.UUID):
    nodes = graph_json.get("nodes") or []
    edges = graph_json.get("edges") or []
    if not nodes:
        raise ValueError("工作流里还没有节点")
    if checkpointer is None:
        raise RuntimeError("检查点存储还没有准备好")

    by_id = {node["id"]: node for node in nodes}
    builder = StateGraph(GraphState)
    incoming = {node["id"]: 0 for node in nodes}
    outgoing: dict[str, list[tuple[str, str | None]]] = {node["id"]: [] for node in nodes}

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in by_id or target not in by_id:
            raise ValueError("连线指向了不存在的节点")
        outgoing[source].append((target, edge.get("sourceHandle")))
        incoming[target] += 1

    for node in nodes:
        kind = node_type(node)
        node_id = node["id"]
        data = node.get("data") or {}
        if kind == "llm":
            builder.add_node(node_id, make_llm(node_id, data, emit))
        elif kind == "human":
            builder.add_node(node_id, make_human(node_id, emit))
        elif kind == "http":
            builder.add_node(node_id, make_http(node_id, data, emit))
        elif kind == "media":
            builder.add_node(node_id, make_media(node_id, data, emit, owner_id, run_id))
        elif kind == "condition":
            builder.add_node(node_id, _passthrough(node_id))
        elif kind == "code":
            raise ValueError("代码节点留到下一版，当前版本不执行")
        else:
            raise ValueError(f"不支持的节点类型：{kind or '空'}")

    roots = [node_id for node_id, degree in incoming.items() if degree == 0]
    if not roots:
        raise ValueError("工作流没有起点")
    for root in roots:
        builder.add_edge(START, root)

    for source, targets in outgoing.items():
        if node_type(by_id[source]) == "condition":
            equals = (by_id[source].get("data") or {}).get("equals") or ""
            mapping = {"true": END, "false": END}
            for target, handle in targets:
                mapping["false" if handle == "false" else "true"] = target

            def route(state: GraphState, expected: str = equals) -> str:
                text = state.get("last_output") or ""
                if expected:
                    return "true" if expected in text else "false"
                return "true" if text.strip() else "false"

            builder.add_conditional_edges(source, route, mapping)
        elif targets:
            for target, _handle in targets:
                builder.add_edge(source, target)
        else:
            builder.add_edge(source, END)

    return builder.compile(checkpointer=checkpointer)


def _passthrough(node_id: str):
    async def run(state: GraphState) -> dict:
        text = state.get("last_output") or ""
        return {"last_output": text, "outputs": {node_id: text}}

    return run


async def _set_status(run_id: uuid.UUID, status: str, error: str | None) -> None:
    async with SessionLocal() as session:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            return
        run.status = status
        run.error = error
        if status in {"succeeded", "failed"}:
            run.ended_at = datetime.now(timezone.utc)
        await session.commit()


async def _totals(run_id: uuid.UUID) -> tuple[int, int]:
    async with SessionLocal() as session:
        row = await session.execute(
            select(
                func.coalesce(func.sum(WorkflowNodeMetric.prompt_tokens + WorkflowNodeMetric.completion_tokens + WorkflowNodeMetric.reasoning_tokens), 0),
                func.coalesce(func.sum(WorkflowNodeMetric.duration_ms), 0),
            ).where(WorkflowNodeMetric.run_id == run_id)
        )
        tokens, duration = row.one()
        return int(tokens), int(duration)


async def execute(run_id: uuid.UUID, resume: dict | None = None) -> None:
    async with SessionLocal() as session:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            return
        definition = await session.get(WorkflowDefinition, run.definition_id)
        if definition is None:
            return
        graph_json = definition.graph_json
        owner_id = run.owner_id
        input_text = run.input_text
        run.status = "running"
        run.error = None
        await session.commit()

    known_secrets = secrets_in(graph_json)

    async def emit(event: dict) -> None:
        event.setdefault("ts", int(time.time()))
        await hub.publish(str(run_id), event)
        if event.get("type") == "node_end":
            metrics = event.get("metrics") or {}
            async with SessionLocal() as session:
                session.add(
                    WorkflowNodeMetric(
                        run_id=run_id,
                        node_id=event.get("node_id") or "",
                        prompt_tokens=int(metrics.get("prompt_tokens") or 0),
                        completion_tokens=int(metrics.get("completion_tokens") or 0),
                        reasoning_tokens=int(metrics.get("reasoning_tokens") or 0),
                        duration_ms=int(metrics.get("duration_ms") or 0),
                    )
                )
                await session.commit()

    try:
        graph = build_graph(graph_json, emit, owner_id, run_id)
        config = {"configurable": {"thread_id": str(run_id)}}
        try:
            if resume is None:
                await graph.ainvoke({"run_input": input_text, "last_output": "", "outputs": {}}, config)
            else:
                await graph.ainvoke(Command(resume=resume), config)
        except GraphInterrupt:
            pass
        snapshot = await graph.aget_state(config)
        interrupts = getattr(snapshot, "interrupts", ()) or ()
        if interrupts:
            payload = getattr(interrupts[0], "value", {}) or {}
            await emit({"type": "interrupt", "node_id": payload.get("node_id"), "payload": payload, "run_id": str(run_id)})
            await _set_status(run_id, "interrupted", None)
            return
        tokens, duration = await _totals(run_id)
        await emit({"type": "workflow_done", "run_id": str(run_id), "total_tokens": tokens, "total_ms": duration})
        await _set_status(run_id, "succeeded", None)
    except Exception as exc:
        message = safe_error(exc, known_secrets)
        await emit({"type": "workflow_failed", "run_id": str(run_id), "detail": message})
        await _set_status(run_id, "failed", message)
