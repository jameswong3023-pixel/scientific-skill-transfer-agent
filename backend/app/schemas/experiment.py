import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.dataset import DatasetDetailOut


class ExperimentCreate(BaseModel):
    dataset_id: uuid.UUID
    task_prompt: str
    paper_id: uuid.UUID | None = None
    skill_version_id: uuid.UUID | None = None
    config: dict[str, Any] = {}


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    arm: str
    status: str
    error: str | None
    totals: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID | None
    kind: str
    path: str
    media_type: str
    bytes: int
    artifact_metadata: dict[str, Any]


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_prompt: str
    status: str
    config: dict[str, Any]
    paper_id: uuid.UUID | None
    skill_version_id: uuid.UUID | None
    dataset_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


class ComparisonOut(BaseModel):
    experiment: ExperimentOut
    runs: list[RunOut]
    artifacts: dict[str, list[ArtifactOut]]
    metrics: dict[str, Any]
    # The brief's Results section asks the comparison to show the *original
    # input* beside each arm's output. The viewer renders slices by dataset-file
    # id, so the comparison payload has to carry the input file, not just the
    # dataset id on the experiment.
    dataset: DatasetDetailOut | None = None
