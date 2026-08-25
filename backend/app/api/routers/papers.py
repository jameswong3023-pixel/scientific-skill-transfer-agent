import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Paper, PaperPage, PaperStatus, Skill, SkillVersion
from app.db.session import get_session
from app.papers.ingest import PdfParseError
from app.schemas.paper import PaperOut, SkillDetailOut
from app.services.papers import UnsupportedUploadError, create_paper
from app.storage.s3 import store
from app.worker import enqueue

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.post("", response_model=PaperOut, status_code=201)
async def upload_paper(
    file: UploadFile = File(...), session: AsyncSession = Depends(get_session)
) -> Paper:
    data = await file.read()
    try:
        return await create_paper(session, None, file.filename or "paper.pdf", data)
    except UnsupportedUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PdfParseError as exc:
        raise HTTPException(status_code=422, detail=f"PDF could not be parsed: {exc}") from exc


@router.get("", response_model=list[PaperOut])
async def list_papers(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Paper).order_by(Paper.created_at.desc()))
    return result.scalars().all()


@router.get("/{paper_id}", response_model=PaperOut)
async def get_paper(paper_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


@router.get("/{paper_id}/pages/{page_number}")
async def get_page_image(
    paper_id: uuid.UUID, page_number: int, session: AsyncSession = Depends(get_session)
) -> Response:
    page = (
        await session.execute(
            select(PaperPage).where(
                PaperPage.paper_id == paper_id, PaperPage.page_number == page_number
            )
        )
    ).scalar_one_or_none()
    if page is None or not page.image_storage_key:
        raise HTTPException(status_code=404, detail="page image not available")
    return Response(content=store.get_bytes(page.image_storage_key), media_type="image/png")


@router.get("/{paper_id}/pages/{page_number}/text")
async def get_page_text(
    paper_id: uuid.UUID, page_number: int, session: AsyncSession = Depends(get_session)
) -> dict:
    page = (
        await session.execute(
            select(PaperPage).where(
                PaperPage.paper_id == paper_id, PaperPage.page_number == page_number
            )
        )
    ).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return {"page_number": page.page_number, "text": page.text}


@router.post("/{paper_id}/extract", status_code=202)
async def start_extraction(
    paper_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="paper not found")
    if paper.status == PaperStatus.FAILED:
        raise HTTPException(status_code=409, detail=f"paper is unusable: {paper.error}")
    job_id = await enqueue("extract_skill_job", str(paper_id))
    return {"job_id": job_id, "paper_id": str(paper_id), "status": "queued"}


@router.get("/{paper_id}/skill", response_model=SkillDetailOut)
async def get_latest_skill(paper_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            select(SkillVersion, Skill)
            .join(Skill, Skill.id == SkillVersion.skill_id)
            .where(Skill.paper_id == paper_id)
            .order_by(SkillVersion.version.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="no skill extracted for this paper yet")
    version, skill = row
    return SkillDetailOut(
        id=version.id,
        skill_id=version.skill_id,
        version=version.version,
        model=version.model,
        validation=version.validation,
        created_at=version.created_at,
        payload=version.payload,
        markdown=version.markdown,
        skill_name=skill.name,
        paper_id=skill.paper_id,
    )
