import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dataset, DatasetFile, DatasetFileRole
from app.db.session import get_session
from app.imaging.render import render_slice_png, slice_count
from app.schemas.dataset import (
    DatasetCreate,
    DatasetDetailOut,
    DatasetFileOut,
    DatasetOut,
)
from app.services.datasets import (
    add_dataset_file,
    create_dataset,
    load_dataset_file_volume,
)
from app.services.papers import UnsupportedUploadError

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.post("", response_model=DatasetOut, status_code=201)
async def create(body: DatasetCreate, session: AsyncSession = Depends(get_session)):
    return await create_dataset(session, body.name, body.modality, body.description)


@router.get("", response_model=list[DatasetOut])
async def list_datasets(session: AsyncSession = Depends(get_session)):
    return (
        await session.execute(select(Dataset).order_by(Dataset.created_at.desc()))
    ).scalars().all()


# HEAD is registered explicitly. The viewer probes this route with HEAD purely
# to read X-Slice-Count before deciding how many slices to offer, and FastAPI
# does not synthesise HEAD for a GET-only route -- the probe came back 405, the
# frontend swallowed it, and the scrubber silently fell back to a single slice.
# Starlette drops the body for HEAD, so the probe stays cheap.
@router.api_route("/files/{file_id}/slice", methods=["GET", "HEAD"])
async def dataset_file_slice(
    file_id: uuid.UUID,
    axis: str = Query("axial"),
    index: int = Query(0),
    cmap: str = Query("gray"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    record = await session.get(DatasetFile, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="file not found")
    try:
        volume = await load_dataset_file_volume(record)
        png = render_slice_png(volume.data, axis=axis, index=index, cmap=cmap)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"cannot render: {exc}") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Slice-Count": str(slice_count(volume.data.shape, axis)),
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{dataset_id}", response_model=DatasetDetailOut)
async def get_dataset(dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    files = (
        await session.execute(
            select(DatasetFile)
            .where(DatasetFile.dataset_id == dataset_id)
            .order_by(DatasetFile.created_at)
        )
    ).scalars().all()
    return DatasetDetailOut(
        id=dataset.id, name=dataset.name, modality=dataset.modality,
        description=dataset.description, created_at=dataset.created_at,
        files=[DatasetFileOut.model_validate(f) for f in files],
    )


@router.get("/{dataset_id}/files", response_model=list[DatasetFileOut])
async def list_dataset_files(
    dataset_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return (
        await session.execute(
            select(DatasetFile)
            .where(DatasetFile.dataset_id == dataset_id)
            .order_by(DatasetFile.created_at)
        )
    ).scalars().all()


@router.post("/{dataset_id}/files", response_model=DatasetFileOut, status_code=201)
async def upload_file(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    role: str = Form(DatasetFileRole.INPUT),
    session: AsyncSession = Depends(get_session),
):
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    try:
        return await add_dataset_file(
            session, dataset, file.filename or "data.bin", await file.read(), role
        )
    except UnsupportedUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
