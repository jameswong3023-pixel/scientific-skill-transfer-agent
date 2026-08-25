import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunArm(StrEnum):
    BASE = "base"
    SKILL = "skill"


class ArtifactKind(StrEnum):
    CODE = "code"
    OUTPUT = "output"
    FIGURE = "figure"
    REPORT = "report"
    LOG = "log"


class Experiment(Base):
    __tablename__ = "experiments"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("papers.id", ondelete="SET NULL")
    )
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skill_versions.id", ondelete="SET NULL")
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL")
    )
    task_prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=ExperimentStatus.PENDING, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["Run"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("experiment_id", "arm", name="uq_run_experiment_arm"),
    )

    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    arm: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.PENDING, index=True)
    # LangGraph checkpoint thread. Reconciles in-flight graph state with these rows.
    thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    workspace_dir: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    experiment: Mapped["Experiment"] = relationship(back_populates="runs")
    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.seq"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_step_run_seq"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(30), default="node")
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped["Run"] = relationship(back_populates="steps")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_steps.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(80), index=True)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Artifact(Base):
    __tablename__ = "artifacts"

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default=ArtifactKind.OUTPUT, index=True)
    path: Mapped[str] = mapped_column(String(400))
    storage_key: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped["Run"] = relationship(back_populates="artifacts")


class Metric(Base):
    __tablename__ = "metrics"

    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(30), default="quality")  # quality|system
    key: Mapped[str] = mapped_column(String(120), index=True)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
