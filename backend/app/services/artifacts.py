"""Pulls a finished run's workspace files into object storage.

Selection is deliberately generous: anything the agent explicitly declared via
`save_artifact`, plus anything that merely *looks* like a result. An agent that
forgets to declare its segmentation must still have it scored, and the reviewer
must still be able to download it.

Staged inputs are the one thing that is never harvested — they already live in
object storage under the dataset's own prefix, and re-uploading them under the
run would duplicate every megabyte of input for both arms.
"""

from __future__ import annotations

import logging
import mimetypes

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, ArtifactKind, Run
from app.storage.s3 import artifact_key, sha256_bytes, store

logger = logging.getLogger(__name__)

MAX_ARTIFACT_BYTES = 200 * 1024 * 1024
STAGED_INPUT_PREFIX = "data/"

_KIND_BY_SUFFIX: dict[str, str] = {
    ".py": ArtifactKind.CODE,
    ".png": ArtifactKind.FIGURE,
    ".jpg": ArtifactKind.FIGURE,
    ".jpeg": ArtifactKind.FIGURE,
    ".svg": ArtifactKind.FIGURE,
    ".pdf": ArtifactKind.FIGURE,
    ".md": ArtifactKind.REPORT,
    ".json": ArtifactKind.REPORT,
    ".csv": ArtifactKind.REPORT,
    ".txt": ArtifactKind.REPORT,
    ".log": ArtifactKind.LOG,
}

INTERESTING_SUFFIXES = (
    ".nii", ".nii.gz", ".mgz", ".tif", ".tiff", ".dcm", ".npy", ".npz",
    ".png", ".jpg", ".jpeg", ".svg", ".json", ".csv", ".md", ".txt", ".py", ".log",
)


def classify_artifact(path: str) -> str:
    low = path.lower()
    if low.endswith(".log") or (low.endswith(".txt") and "log" in low):
        return ArtifactKind.LOG
    for suffix, kind in _KIND_BY_SUFFIX.items():
        if low.endswith(suffix):
            return kind
    return ArtifactKind.OUTPUT


def _is_junk(path: str) -> bool:
    parts = path.split("/")
    return any(p.startswith(".") or p == "__pycache__" for p in parts) or path.endswith(".pyc")


def select_artifact_paths(files: list[dict], declared: list[dict]) -> set[str]:
    """Everything the agent explicitly saved, plus anything that looks like a
    result. Staged inputs are excluded — they are already in object storage."""
    by_path = {f["path"]: f for f in files}
    declared_paths = {d["path"] for d in declared}
    selected: set[str] = set()

    for path, info in by_path.items():
        if path.startswith(STAGED_INPUT_PREFIX) or _is_junk(path):
            continue
        if info.get("bytes", 0) > MAX_ARTIFACT_BYTES:
            logger.warning("skipping oversized artifact %s (%d bytes)", path, info["bytes"])
            continue
        if path in declared_paths or path.lower().endswith(INTERESTING_SUFFIXES):
            selected.add(path)

    return selected


async def harvest_run_artifacts(
    session: AsyncSession, run: Run, sandbox, declared: list[dict]
) -> list[Artifact]:
    try:
        files = await sandbox.list_files(str(run.id))
    except Exception as exc:
        logger.error("could not list workspace for run %s: %s", run.id, exc)
        return []

    descriptions = {d["path"]: d.get("description", "") for d in declared}
    kinds = {d["path"]: d.get("kind") for d in declared}
    created: list[Artifact] = []

    for path in sorted(select_artifact_paths(files, declared)):
        try:
            data = await sandbox.read_file(str(run.id), path)
        except Exception as exc:
            logger.warning("could not read artifact %s: %s", path, exc)
            continue

        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        try:
            # DEVIATION FROM PLAN: the upload is guarded. `artifact_key` rejects
            # traversal, and agent-generated code names these files, so a single
            # hostile or malformed path would otherwise raise out of harvesting
            # and mark an otherwise successful run FAILED.
            key = artifact_key(run.id, path)
            store.put_bytes(key, data, media_type)
        except Exception as exc:
            logger.warning("could not store artifact %s for run %s: %s", path, run.id, exc)
            continue

        artifact = Artifact(
            run_id=run.id,
            kind=kinds.get(path) or classify_artifact(path),
            path=path,
            storage_key=key,
            media_type=media_type,
            bytes=len(data),
            sha256=sha256_bytes(data),
            artifact_metadata={
                "description": descriptions.get(path, ""),
                "declared": path in descriptions,
            },
        )
        session.add(artifact)
        created.append(artifact)

    await session.flush()
    logger.info("harvested %d artifacts for run %s", len(created), run.id)
    return created
