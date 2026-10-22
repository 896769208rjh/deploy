import uuid

from pydantic import BaseModel, Field


class DefinitionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    graph_json: dict


class RunBody(BaseModel):
    definition_id: uuid.UUID
    inputs: dict = Field(default_factory=dict)


class ResumeBody(BaseModel):
    node_id: str | None = None
    decision: str = "approve"
    value: str | None = None
