import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DatasetFileRole(StrEnum):
    INPUT = "input"
    GROUND_TRUTH = "ground_truth"
    AUX = "aux"


class Dataset(Base):
    __tablename__ = "datasets"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    modality: Mapped[str] = mapped_column(String(60), default="unknown")
    description: Mapped[str] = mapped_column(Text, default="")

    files: Mapped[list["DatasetFile"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DatasetFile(Base):
    __tablename__ = "dataset_files"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=DatasetFileRole.INPUT, index=True)
    filename: Mapped[str] = mapped_column(String(300))
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    media_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    dataset: Mapped["Dataset"] = relationship(back_populates="files")
