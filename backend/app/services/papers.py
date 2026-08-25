from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skill_extraction.schema import Skill as SkillModel
from app.db.models import Paper, PaperPage, PaperStatus, Skill, SkillVersion
from app.papers.ingest import PdfParseError, parse_pdf
from app.storage.s3 import paper_key, paper_page_key, sha256_bytes, store

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 60 * 1024 * 1024
PDF_MAGIC = b"%PDF"


class UnsupportedUploadError(ValueError):
    """Upload rejected before any parsing is attempted."""


def validate_pdf_upload(filename: str, data: bytes) -> None:
    if not data:
        raise UnsupportedUploadError("empty upload")
    if len(data) > MAX_PDF_BYTES:
        raise UnsupportedUploadError(
            f"file too large: {len(data)} bytes (limit {MAX_PDF_BYTES})"
        )
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedUploadError(f"unsupported extension for {filename}; expected .pdf")
    if not data.lstrip()[:4].startswith(PDF_MAGIC):
        raise UnsupportedUploadError("file content is not a PDF (magic bytes mismatch)")


def compute_next_version(existing: Sequence[int]) -> int:
    return (max(existing) + 1) if existing else 1


async def create_paper(
    session: AsyncSession, workspace_id: uuid.UUID | None, filename: str, data: bytes
) -> Paper:
    validate_pdf_upload(filename, data)

    paper = Paper(
        workspace_id=workspace_id,
        filename=filename,
        storage_key="",
        sha256=sha256_bytes(data),
        status=PaperStatus.PARSING,
    )
    paper.storage_key = paper_key(paper.id, filename)
    store.put_bytes(paper.storage_key, data, "application/pdf")
    session.add(paper)
    await session.flush()

    try:
        parsed = parse_pdf(data, render_pages=True)
    except PdfParseError as exc:
        paper.status = PaperStatus.FAILED
        paper.error = str(exc)
        await session.flush()
        raise

    paper.title = parsed.title or filename
    paper.page_count = len(parsed.pages)
    paper.status = PaperStatus.PARSED

    for page in parsed.pages:
        image_key = None
        if page.image_png:
            image_key = paper_page_key(paper.id, page.page_number)
            store.put_bytes(image_key, page.image_png, "image/png")
        session.add(
            PaperPage(
                paper_id=paper.id,
                page_number=page.page_number,
                text=page.text,
                char_count=page.char_count,
                image_storage_key=image_key,
            )
        )

    await session.flush()
    logger.info("paper %s parsed: %d pages", paper.id, paper.page_count)
    return paper


async def load_parsed_pages(session: AsyncSession, paper_id: uuid.UUID):
    from app.papers.ingest import ParsedPage, ParsedPaper

    rows = (
        await session.execute(
            select(PaperPage).where(PaperPage.paper_id == paper_id).order_by(PaperPage.page_number)
        )
    ).scalars().all()
    paper = await session.get(Paper, paper_id)
    pages = [
        ParsedPage(page_number=r.page_number, text=r.text, char_count=r.char_count)
        for r in rows
    ]
    return ParsedPaper(
        title=paper.title if paper else None,
        pages=pages,
        total_chars=sum(p.char_count for p in pages),
        is_scanned=False,
    )


async def persist_skill(
    session: AsyncSession, paper: Paper, result: dict
) -> SkillVersion:
    skill_model: SkillModel | None = result.get("skill")
    if skill_model is None:
        raise ValueError(result.get("error") or "extraction produced no skill")

    slug = skill_model.name.lower().replace(" ", "-")[:200]
    skill = (
        await session.execute(
            select(Skill).where(Skill.paper_id == paper.id, Skill.slug == slug)
        )
    ).scalar_one_or_none()

    if skill is None:
        skill = Skill(
            workspace_id=paper.workspace_id,
            paper_id=paper.id,
            name=skill_model.name,
            slug=slug,
        )
        session.add(skill)
        await session.flush()

    existing = (
        await session.execute(
            select(SkillVersion.version).where(SkillVersion.skill_id == skill.id)
        )
    ).scalars().all()

    from app.config import settings

    version = SkillVersion(
        skill_id=skill.id,
        version=compute_next_version(list(existing)),
        payload=skill_model.model_dump(mode="json"),
        markdown=result.get("markdown", ""),
        model=settings.openrouter_model,
        validation=result.get("validation", {}),
    )
    session.add(version)
    paper.status = PaperStatus.EXTRACTED
    await session.flush()
    return version
