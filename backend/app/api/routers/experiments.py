import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artifact,
    Dataset,
    DatasetFile,
    Experiment,
    ExperimentStatus,
    Metric,
    Paper,
    Run,
    SkillVersion,
)
from app.db.session import get_session
from app.imaging.render import render_mask_overlay_png, render_slice_png, slice_count
from app.schemas.dataset import DatasetDetailOut, DatasetFileOut
from app.schemas.experiment import (
    ArtifactOut,
    ComparisonOut,
    ExperimentCreate,
    ExperimentOut,
    RunOut,
)
from app.services.experiments import create_experiment
from app.services.export import build_zip_layout, write_zip
from app.storage.s3 import store
from app.worker import enqueue

router = APIRouter(prefix="/api", tags=["experiments"])


@router.post("/experiments", response_model=ExperimentOut, status_code=201)
async def create(body: ExperimentCreate, session: AsyncSession = Depends(get_session)):
    return await create_experiment(
        session, body.paper_id, body.skill_version_id, body.dataset_id,
        body.task_prompt, body.config,
    )


@router.get("/experiments", response_model=list[ExperimentOut])
async def list_experiments(session: AsyncSession = Depends(get_session)):
    return (
        await session.execute(select(Experiment).order_by(Experiment.created_at.desc()))
    ).scalars().all()


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return experiment


@router.post("/experiments/{experiment_id}/run", status_code=202)
async def start(experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if experiment.status in (ExperimentStatus.RUNNING, ExperimentStatus.EVALUATING):
        raise HTTPException(status_code=409, detail="experiment is already running")
    job_id = await enqueue("run_experiment_job", str(experiment_id))
    return {"job_id": job_id, "experiment_id": str(experiment_id), "status": "queued"}


async def _load_comparison(session: AsyncSession, experiment_id: uuid.UUID):
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    runs = (
        await session.execute(
            select(Run).where(Run.experiment_id == experiment_id).order_by(Run.arm)
        )
    ).scalars().all()
    artifacts = (
        await session.execute(
            select(Artifact).where(Artifact.run_id.in_([r.id for r in runs] or [None]))
        )
    ).scalars().all()
    metrics = (
        await session.execute(select(Metric).where(Metric.experiment_id == experiment_id))
    ).scalars().all()
    return experiment, list(runs), list(artifacts), list(metrics)


async def _dataset_detail(
    session: AsyncSession, dataset_id: uuid.UUID | None
) -> DatasetDetailOut | None:
    """The input dataset, files included, so the comparison can show the original.

    `DatasetFileOut` omits `storage_key`, so this exposes no object-store paths.
    Ground-truth files are listed here exactly as they already are on the dataset
    page — that is a reviewer-facing view. The agents never see this payload;
    their isolation is enforced at sandbox staging, not by hiding rows from the UI.
    """
    if dataset_id is None:
        return None
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        return None
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


@router.get("/experiments/{experiment_id}/comparison", response_model=ComparisonOut)
async def comparison(experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    experiment, runs, artifacts, metrics = await _load_comparison(session, experiment_id)

    by_run: dict[str, list[ArtifactOut]] = defaultdict(list)
    for a in artifacts:
        by_run[str(a.run_id)].append(ArtifactOut.model_validate(a))

    shaped: dict[str, dict] = {"system": defaultdict(dict), "quality": defaultdict(dict),
                               "comparison": {}}
    arm_of = {str(r.id): r.arm for r in runs}
    for m in metrics:
        if m.scope == "comparison":
            shaped["comparison"][m.key] = {"value": m.value_num, **(m.value_json or {})}
        else:
            arm = arm_of.get(str(m.run_id), "unknown")
            bucket = shaped.setdefault(m.scope, defaultdict(dict))
            bucket[arm][m.key] = {"value": m.value_num, "detail": m.value_json}

    return ComparisonOut(
        experiment=ExperimentOut.model_validate(experiment),
        runs=[RunOut.model_validate(r) for r in runs],
        artifacts=dict(by_run),
        metrics={k: dict(v) if isinstance(v, defaultdict) else v for k, v in shaped.items()},
        dataset=await _dataset_detail(session, experiment.dataset_id),
    )


@router.get("/experiments/{experiment_id}/download")
async def download(experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    experiment, runs, artifacts, metrics = await _load_comparison(session, experiment_id)

    by_run: dict[str, list] = defaultdict(list)
    for a in artifacts:
        by_run[str(a.run_id)].append(a)

    skill_version = (
        await session.get(SkillVersion, experiment.skill_version_id)
        if experiment.skill_version_id
        else None
    )
    paper = (
        await session.get(Paper, experiment.paper_id) if experiment.paper_id else None
    )

    # DEVIATION FROM PLAN: the plan keyed this blob on `m.key` alone. Both arms
    # write the same system keys ("agent_steps", "cost", ...), so one arm
    # silently overwrote the other and the exported metrics.json described a
    # single run. Nesting by arm keeps the comparison the archive is for.
    arm_of = {str(r.id): r.arm for r in runs}
    by_arm: dict[str, dict] = defaultdict(dict)
    comparison_metrics: dict[str, dict] = {}
    for m in metrics:
        entry = {"value": m.value_num, "scope": m.scope, "detail": m.value_json}
        if m.scope == "comparison" or m.run_id is None:
            comparison_metrics[m.key] = entry
        else:
            by_arm[arm_of.get(str(m.run_id), "unknown")][m.key] = entry
    metric_blob = {"by_arm": dict(by_arm), "comparison": comparison_metrics}

    layout = build_zip_layout(
        experiment, runs, by_run, skill_version, metric_blob, paper=paper
    )
    filename = f"experiment-{experiment_id}.zip"
    return StreamingResponse(
        write_zip(layout, fetch=store.get_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---- artifact access -------------------------------------------------------

@router.get("/artifacts/{artifact_id}")
async def download_artifact(
    artifact_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        content = store.get_bytes(artifact.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"artifact bytes missing: {exc}") from exc
    return Response(
        content=content,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.path.split("/")[-1]}"'},
    )


async def _artifact_volume(session: AsyncSession, artifact_id: uuid.UUID):
    from app.services.experiments import _load_array

    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        return artifact, _load_array(store.get_bytes(artifact.storage_key), artifact.path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"not a renderable image: {exc}") from exc


# HEAD registered explicitly so the viewer's X-Slice-Count probe works; see the
# matching comment in routers/datasets.py.
@router.get("/artifacts/{artifact_id}/slice", operation_id="artifact_slice")
@router.head("/artifacts/{artifact_id}/slice", operation_id="artifact_slice_head")
async def artifact_slice(
    artifact_id: uuid.UUID,
    axis: str = Query("axial"),
    index: int = Query(0),
    cmap: str = Query("gray"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _, volume = await _artifact_volume(session, artifact_id)
    try:
        png = render_slice_png(volume.data, axis, index, cmap)
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


@router.get("/artifacts/{artifact_id}/overlay")
async def artifact_overlay(
    artifact_id: uuid.UUID,
    axis: str = Query("axial"),
    index: int = Query(0),
    alpha: float = Query(0.55),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _, volume = await _artifact_volume(session, artifact_id)
    try:
        png = render_mask_overlay_png(volume.data, axis, index, alpha)
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
