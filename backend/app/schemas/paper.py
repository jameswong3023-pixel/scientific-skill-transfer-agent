import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    filename: str
    page_count: int
    status: str
    error: str | None
    created_at: datetime


class SkillVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    skill_id: uuid.UUID
    version: int
    model: str
    validation: dict[str, Any]
    created_at: datetime


class SkillDetailOut(SkillVersionOut):
    payload: dict[str, Any]
    markdown: str
    skill_name: str = ""
    paper_id: uuid.UUID | None = None
