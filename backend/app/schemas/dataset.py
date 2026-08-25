import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DatasetFileOut(BaseModel):
    # Deliberately omits storage_key: object keys are internal.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    role: str
    bytes: int
    media_type: str
    file_metadata: dict[str, Any]
    created_at: datetime


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    modality: str
    description: str
    created_at: datetime


class DatasetDetailOut(DatasetOut):
    files: list[DatasetFileOut] = []


class DatasetCreate(BaseModel):
    name: str
    modality: str = "unknown"
    description: str = ""
