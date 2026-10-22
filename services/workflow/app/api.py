import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.engine import execute, spawn
from app.graph_util import mask_graph, merge_secrets
from app.hub import hub
from app.models import WorkflowDefinition, WorkflowNodeMetric, WorkflowRun
from app.schemas import DefinitionBody, ResumeBody, RunBody
from app.security import Actor, require_actor

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


def _definition_payload(item: WorkflowDefinition) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "graph_json": mask_graph(item.graph_json),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _owned_definition(session: AsyncSession, definition_id: uuid.UUID, actor: Actor) -> WorkflowDefinition:
    item = await session.get(WorkflowDefinition, definition_id)
    if item is None or item.owner_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这个工作流")
    return item


@router.get("/definitions")
async def list_definitions(actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(
        select(WorkflowDefinition).where(WorkflowDefinition.owner_id == actor.id).order_by(WorkflowDefinition.updated_at.desc())
    )
    return [_definition_payload(item) for item in rows]


@router.post("/definitions", status_code=201)
async def create_definition(
    body: DefinitionBody,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = WorkflowDefinition(owner_id=actor.id, name=body.name.strip(), graph_json=merge_secrets(body.graph_json, None))
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _definition_payload(item)


@router.get("/definitions/{definition_id}")
async def get_definition(
    definition_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return _definition_payload(await _owned_definition(session, definition_id, actor))


@router.put("/definitions/{definition_id}")
async def update_definition(
    definition_id: uuid.UUID,
    body: DefinitionBody,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = await _owned_definition(session, definition_id, actor)
    item.name = body.name.strip()
    item.graph_json = merge_secrets(body.graph_json, item.graph_json)
    await session.commit()
    await session.refresh(item)
    return _definition_payload(item)


@router.delete("/definitions/{definition_id}", status_code=204)
async def delete_definition(
    definition_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> None:
    item = await _owned_definition(session, definition_id, actor)
    run_ids = list(await session.scalars(select(WorkflowRun.id).where(WorkflowRun.definition_id == item.id)))
    if run_ids:
        await session.execute(delete(WorkflowNodeMetric).where(WorkflowNodeMetric.run_id.in_(run_ids)))
        await session.execute(delete(WorkflowRun).where(WorkflowRun.id.in_(run_ids)))
    await session.delete(item)
    await session.commit()


@router.post("/runs", status_code=202)
async def start_run(body: RunBody, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    definition = await _owned_definition(session, body.definition_id, actor)
    text = str(body.inputs.get("input") or body.inputs.get("idea") or "")
    run = WorkflowRun(definition_id=definition.id, owner_id=actor.id, status="pending", input_text=text)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    spawn(execute(run.id))
    return {"run_id": run.id, "status": run.status}


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.owner_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这次运行")
    return {
        "id": run.id,
        "definition_id": run.definition_id,
        "status": run.status,
        "input_text": run.input_text,
        "error": run.error,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
    }


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: uuid.UUID, actor: Actor = Depends(require_actor), session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.owner_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这次运行")

    async def events():
        queue = await hub.subscribe(str(run_id))
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in {"workflow_done", "workflow_failed", "interrupt"}:
                break

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(
    run_id: uuid.UUID,
    body: ResumeBody,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.owner_id != actor.id:
        raise HTTPException(status_code=404, detail="找不到这次运行")
    if run.status != "interrupted":
        raise HTTPException(status_code=409, detail="这次运行现在不在等待确认")
    spawn(execute(run.id, {"node_id": body.node_id, "decision": body.decision, "value": body.value}))
    return {"run_id": run.id, "status": "running"}
