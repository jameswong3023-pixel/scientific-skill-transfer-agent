"""A/B experiment orchestration.

Both arms are launched from the same code path with the same inputs; `arm` and
`skill` are the only values that differ. They run concurrently in separate
sandbox workspaces so neither can observe the other's files.

Ground truth is loaded ONLY here, after both runs have finished.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.datasets.staging import stage_dataset
from app.db.models import (
    AgentStep,
    Artifact,
    ArtifactKind,
    DatasetFile,
    DatasetFileRole,
    Experiment,
    ExperimentStatus,
    Metric,
    Run,
    RunArm,
    RunStatus,
    SkillVersion,
)
from app.db.session import AsyncSessionLocal
from app.events.bus import RunEventEmitter, bus
from app.sandbox.client import sandbox_client
from app.storage.s3 import store

logger = logging.getLogger(__name__)

# Names that suggest a label map, ordered by how strongly they suggest it.
_SEGMENTATION_HINTS = ("segmentation", "segment", "labels", "label", "mask", "classes", "tissue")
_NOT_SEGMENTATION = ("bias", "field", "preview", "overlay", "histogram", "input", "corrected")
_VOLUME_SUFFIXES = (".nii", ".nii.gz", ".mgz", ".npy", ".tif", ".tiff")


def rank_prediction_candidates(artifacts) -> list:
    """Volume outputs that could plausibly be the segmentation, best name first."""
    candidates = [
        a
        for a in artifacts
        if a.kind in (ArtifactKind.OUTPUT, "output")
        and a.path.lower().endswith(_VOLUME_SUFFIXES)
        and not any(bad in a.path.lower() for bad in _NOT_SEGMENTATION)
    ]

    def score(a) -> int:
        low = a.path.lower()
        for i, hint in enumerate(_SEGMENTATION_HINTS):
            if hint in low:
                return len(_SEGMENTATION_HINTS) - i
        return 0

    candidates.sort(key=score, reverse=True)
    return candidates


def find_prediction_artifact(artifacts, truth_shape=None):
    """Pick the artifact that is most plausibly the segmentation result.

    Name ranking only — shape agreement is applied by `evaluate_experiment`,
    which is the layer that can afford to download and decode each candidate.
    `truth_shape` is accepted so callers can keep the documented signature.
    """
    candidates = rank_prediction_candidates(artifacts)
    return candidates[0] if candidates else None


def system_metrics_for(result: dict, duration_s: float) -> list[tuple[str, float]]:
    usage = result.get("usage") or {}
    return [
        ("agent_steps", float(result.get("iterations", 0))),
        ("code_executions", float(result.get("executions", 0))),
        ("failed_executions", float(result.get("failed_executions", 0))),
        ("runtime_seconds", float(duration_s)),
        ("total_tokens", float(usage.get("total_tokens", 0))),
        ("prompt_tokens", float(usage.get("prompt_tokens", 0))),
        ("completion_tokens", float(usage.get("completion_tokens", 0))),
        ("cost", float(usage.get("cost", 0.0))),
    ]


async def create_experiment(
    session: AsyncSession,
    paper_id: uuid.UUID | None,
    skill_version_id: uuid.UUID | None,
    dataset_id: uuid.UUID,
    task_prompt: str,
    config: dict | None = None,
) -> Experiment:
    experiment = Experiment(
        paper_id=paper_id,
        skill_version_id=skill_version_id,
        dataset_id=dataset_id,
        task_prompt=task_prompt,
        status=ExperimentStatus.PENDING,
        config={
            "model": settings.openrouter_model,
            "temperature": settings.agent_temperature,
            "max_iterations": settings.agent_max_iterations,
            **(config or {}),
        },
    )
    session.add(experiment)
    await session.flush()

    # Both runs exist from the start so the UI can render two columns before
    # either has produced anything.
    for arm in (RunArm.BASE, RunArm.SKILL):
        run = Run(experiment_id=experiment.id, arm=arm, status=RunStatus.PENDING)
        run.thread_id = str(run.id)  # LangGraph checkpoint thread == run id
        session.add(run)

    await session.flush()
    return experiment


async def _ensure_runs(session: AsyncSession, experiment_id: uuid.UUID) -> list[Run]:
    """Both arms, created if missing.

    DEVIATION FROM PLAN: the plan assumed `create_experiment` had already made
    the rows and silently did nothing when it had not — an experiment created by
    any other path would have been marked completed without running anything.
    `uq_run_experiment_arm` makes this safe to call repeatedly.
    """
    runs = (
        await session.execute(select(Run).where(Run.experiment_id == experiment_id))
    ).scalars().all()
    existing = {r.arm for r in runs}
    for arm in (RunArm.BASE, RunArm.SKILL):
        if arm in existing:
            continue
        run = Run(experiment_id=experiment_id, arm=arm, status=RunStatus.PENDING)
        run.thread_id = str(run.id)
        session.add(run)
    await session.flush()
    return list(
        (
            await session.execute(
                select(Run).where(Run.experiment_id == experiment_id).order_by(Run.arm)
            )
        ).scalars().all()
    )


async def _clear_previous_attempt(
    session: AsyncSession, experiment_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> None:
    """Wipe the rows a previous attempt of this job wrote.

    DEVIATION FROM PLAN (not in the plan at all): the arq worker runs with
    `max_tries=2`, so a timed-out or crashed experiment job is retried against
    the SAME run rows. `agent_steps` has `UniqueConstraint(run_id, seq)` and a
    fresh `RunEventEmitter` restarts at seq 0, so without this the entire replay
    timeline of the retry is silently swallowed by the emitter's persist
    try/except and the artifacts are duplicated. Object-storage blobs from the
    previous attempt are left behind deliberately — they are overwritten by key
    when the same path is produced again, and orphans are cheaper than a delete
    that could race a download.
    """
    if not run_ids:
        return
    await session.execute(delete(Metric).where(Metric.experiment_id == experiment_id))
    await session.execute(delete(Artifact).where(Artifact.run_id.in_(run_ids)))
    await session.execute(delete(AgentStep).where(AgentStep.run_id.in_(run_ids)))


async def execute_run(
    experiment_id: uuid.UUID,
    run_id: uuid.UUID,
    arm: str,
    task: str,
    skill: dict | None,
    dataset_file_ids: list[uuid.UUID],
    max_iterations: int | None = None,
) -> dict:
    from app.agents.analysis.graph import run_analysis
    from app.agents.checkpointing import analysis_checkpointer

    started = time.perf_counter()
    emit = RunEventEmitter(
        run_id=run_id,
        arm=arm,
        session_factory=AsyncSessionLocal,
        event_bus=bus,
        experiment_id=experiment_id,
    )

    async with AsyncSessionLocal() as session:
        run = await session.get(Run, run_id)
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        run.error = None
        run.finished_at = None
        run.workspace_dir = f"/work/{run_id}"
        await session.commit()

        # Ordered so both arms see byte-identical manifests. `IN (...)` has no
        # inherent ordering, and the manifest is pasted verbatim into the task
        # prompt, so an unordered fetch would make the two arms' prompts differ.
        files = (
            await session.execute(
                select(DatasetFile)
                .where(DatasetFile.id.in_(dataset_file_ids))
                .order_by(DatasetFile.filename)
            )
        ).scalars().all()

    try:
        await sandbox_client.reset(str(run_id))
        await emit("stage_data", "Preparing an isolated workspace", {"arm": arm})

        manifest = await stage_dataset(sandbox_client, str(run_id), files, store)
        await emit(
            "stage_data",
            f"Staged {len(manifest.files)} input file(s)",
            {"files": [f.path for f in manifest.files]},
        )

        # Both arms are checkpointed identically; the checkpointer is not part
        # of what differs between them. It yields None if Postgres is
        # unreachable, in which case the run proceeds without persistence
        # rather than failing.
        async with analysis_checkpointer() as checkpointer:
            result = await run_analysis(
                run_id=str(run_id),
                arm=arm,
                task=task,
                manifest_block=manifest.as_prompt_block(),
                skill=skill,
                sandbox=sandbox_client,
                emit=emit,
                max_iterations=max_iterations,
                checkpointer=checkpointer,
                thread_id=str(run_id),
            )

        duration = time.perf_counter() - started

        async with AsyncSessionLocal() as session:
            run = await session.get(Run, run_id)
            await harvest(session, run, result)
            run.status = RunStatus.FAILED if result.get("error") else RunStatus.COMPLETED
            run.error = result.get("error")
            run.finished_at = datetime.now(timezone.utc)
            run.totals = {
                "summary": (result.get("summary") or "")[:20000],
                "iterations": result.get("iterations", 0),
                "executions": result.get("executions", 0),
                "failed_executions": result.get("failed_executions", 0),
                "usage": result.get("usage", {}),
                "duration_seconds": duration,
            }
            for key, value in system_metrics_for(result, duration):
                session.add(
                    Metric(
                        experiment_id=experiment_id, run_id=run_id,
                        scope="system", key=key, value_num=value,
                    )
                )
            await session.commit()

        return {"arm": arm, "ok": not result.get("error"), "error": result.get("error")}

    except Exception as exc:
        logger.exception("run %s (%s) crashed", run_id, arm)
        await emit("error", f"Run failed: {type(exc).__name__}", {"error": str(exc)}, kind="error")
        async with AsyncSessionLocal() as session:
            run = await session.get(Run, run_id)
            if run:
                run.status = RunStatus.FAILED
                run.error = f"{type(exc).__name__}: {exc}"
                run.finished_at = datetime.now(timezone.utc)
                await session.commit()
        return {"arm": arm, "ok": False, "error": str(exc)}


async def harvest(session: AsyncSession, run: Run, result: dict) -> None:
    from app.services.artifacts import harvest_run_artifacts

    await harvest_run_artifacts(session, run, sandbox_client, result.get("artifacts", []))


def _load_array(data: bytes, filename: str):
    from app.imaging.loaders import load_volume

    suffix = "".join(Path(filename).suffixes[-2:]) or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        tmp = fh.name
    try:
        return load_volume(tmp, Path(filename).name)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _score_run_prediction(artifacts, truth_data, spacing) -> dict:
    """Score the best-matching prediction among a run's volume outputs.

    DEVIATION FROM PLAN: the plan picked one artifact by name and scored it, so a
    run that wrote `output.nii.gz` (the label map) alongside `denoised.nii.gz`
    could be scored against the wrong file and report a shape mismatch while a
    perfectly good segmentation sat next to it. The plan's own interface promised
    selection "by shape agreement, falling back to name heuristics"; this is that
    promise. Name order still decides ties, so behaviour is unchanged whenever
    exactly one candidate exists.
    """
    from app.evaluation.metrics import evaluate_segmentation

    candidates = rank_prediction_candidates(artifacts)
    if not candidates:
        return {"error": "no_prediction_artifact", "mean_dice": 0.0, "per_class": {}}

    first_result: dict | None = None
    for artifact in candidates:
        try:
            volume = _load_array(store.get_bytes(artifact.storage_key), artifact.path)
            scores = evaluate_segmentation(volume.data, truth_data, spacing=spacing)
        except Exception as exc:
            logger.warning("could not score %s: %s", artifact.path, exc)
            scores = {
                "error": f"unreadable_prediction: {exc}",
                "mean_dice": 0.0,
                "per_class": {},
            }
        scores["prediction_artifact"] = artifact.path
        if first_result is None:
            first_result = scores
        if not scores.get("error"):
            return scores

    return first_result or {"error": "no_prediction_artifact", "mean_dice": 0.0, "per_class": {}}


async def evaluate_experiment(session: AsyncSession, experiment: Experiment) -> dict:
    """Scores both runs against withheld ground truth.

    This is the first and only point at which ground-truth data is read.
    """
    truth_file = (
        await session.execute(
            select(DatasetFile).where(
                DatasetFile.dataset_id == experiment.dataset_id,
                DatasetFile.role == DatasetFileRole.GROUND_TRUTH,
            )
        )
    ).scalars().first()

    if truth_file is None:
        logger.info("experiment %s has no ground truth; skipping quality metrics", experiment.id)
        return {"evaluated": False, "reason": "no ground truth in dataset"}

    truth_vol = _load_array(store.get_bytes(truth_file.storage_key), truth_file.filename)
    spacing = truth_vol.meta.spacing

    runs = (
        await session.execute(select(Run).where(Run.experiment_id == experiment.id))
    ).scalars().all()

    summary: dict[str, dict] = {}
    for run in runs:
        artifacts = (
            await session.execute(select(Artifact).where(Artifact.run_id == run.id))
        ).scalars().all()

        scores = _score_run_prediction(list(artifacts), truth_vol.data, spacing)
        summary[run.arm] = scores

        session.add(
            Metric(experiment_id=experiment.id, run_id=run.id, scope="quality",
                   key="mean_dice", value_num=float(scores.get("mean_dice", 0.0)),
                   value_json=scores)
        )
        for label, per in (scores.get("per_class") or {}).items():
            session.add(
                Metric(experiment_id=experiment.id, run_id=run.id, scope="quality",
                       key=f"dice_class_{label}", value_num=float(per["dice"]), value_json=per)
            )

    base = summary.get(RunArm.BASE, {}).get("mean_dice", 0.0)
    skilled = summary.get(RunArm.SKILL, {}).get("mean_dice", 0.0)
    session.add(
        Metric(experiment_id=experiment.id, run_id=None, scope="comparison",
               key="dice_delta", value_num=float(skilled - base),
               value_json={"base": base, "skill": skilled, "per_arm": summary})
    )

    await session.flush()
    return {"evaluated": True, "per_arm": summary, "dice_delta": skilled - base}


async def execute_experiment(experiment_id: uuid.UUID) -> dict:
    async with AsyncSessionLocal() as session:
        experiment = await session.get(Experiment, experiment_id)
        if experiment is None:
            return {"ok": False, "error": "experiment not found"}

        experiment.status = ExperimentStatus.RUNNING
        runs = await _ensure_runs(session, experiment_id)
        await _clear_previous_attempt(session, experiment_id, [r.id for r in runs])
        await session.commit()

        skill_payload = None
        if experiment.skill_version_id:
            version = await session.get(SkillVersion, experiment.skill_version_id)
            skill_payload = version.payload if version else None

        input_files = (
            await session.execute(
                select(DatasetFile.id)
                .where(
                    DatasetFile.dataset_id == experiment.dataset_id,
                    DatasetFile.role != DatasetFileRole.GROUND_TRUTH,
                )
                .order_by(DatasetFile.filename)
            )
        ).scalars().all()

        task = experiment.task_prompt
        # Read once, applied to both arms: an identical iteration budget is part
        # of the fairness contract, and the recorded config must not be a lie.
        # `config` is caller-supplied JSON, so a non-numeric value falls back to
        # the configured default rather than crashing the graph's recursion cap.
        try:
            budget = int((experiment.config or {}).get("max_iterations"))
        except (TypeError, ValueError):
            budget = None
        if budget is not None and budget < 1:
            budget = None
        run_specs = [(r.id, r.arm) for r in runs]

    evaluation: dict = {"evaluated": False, "reason": "not attempted"}
    try:
        # Both arms run concurrently. Same task, same files, same tools, same
        # model, same budget; only `skill` differs, and only for the skill arm.
        results = await asyncio.gather(
            *[
                execute_run(
                    experiment_id=experiment_id,
                    run_id=run_id,
                    arm=arm,
                    task=task,
                    skill=skill_payload if arm == RunArm.SKILL else None,
                    dataset_file_ids=list(input_files),
                    max_iterations=budget,
                )
                for run_id, arm in run_specs
            ],
            return_exceptions=True,
        )

        async with AsyncSessionLocal() as session:
            experiment = await session.get(Experiment, experiment_id)
            experiment.status = ExperimentStatus.EVALUATING
            await session.commit()

            try:
                evaluation = await evaluate_experiment(session, experiment)
            except Exception as exc:
                logger.exception("evaluation failed for %s", experiment_id)
                evaluation = {"evaluated": False, "error": str(exc)}

            experiment.status = ExperimentStatus.COMPLETED
            experiment.completed_at = datetime.now(timezone.utc)
            await session.commit()
    except Exception as exc:
        # DEVIATION FROM PLAN: the plan had no outer guard, so an orchestration
        # failure left `experiments.status` on 'running' forever — and the SSE
        # experiment stream only terminates on a terminal status, so every
        # attached browser would hang on keepalives indefinitely.
        logger.exception("experiment %s failed to orchestrate", experiment_id)
        async with AsyncSessionLocal() as session:
            experiment = await session.get(Experiment, experiment_id)
            if experiment is not None:
                experiment.status = ExperimentStatus.FAILED
                experiment.completed_at = datetime.now(timezone.utc)
                await session.commit()
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "evaluation": evaluation}

    return {
        "ok": True,
        "runs": [r if not isinstance(r, Exception) else {"error": str(r)} for r in results],
        "evaluation": evaluation,
    }
