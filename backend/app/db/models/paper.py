import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaperStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    FAILED = "failed"


class Paper(Base):
    __tablename__ = "papers"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(300))
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default=PaperStatus.UPLOADED)
    error: Mapped[str | None] = mapped_column(Text)

    pages: Mapped[list["PaperPage"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="PaperPage.page_number"
    )


class PaperPage(Base):
    __tablename__ = "paper_pages"
    __table_args__ = (UniqueConstraint("paper_id", "page_number", name="uq_paper_page"),)

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    image_storage_key: Mapped[str | None] = mapped_column(String(500))

    paper: Mapped["Paper"] = relationship(back_populates="pages")
