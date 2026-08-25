"""Copies dataset files into a run's sandbox workspace.

This module is the *only* place dataset bytes cross into the sandbox, which is
what makes ground-truth isolation auditable: there is exactly one filter to
review, and one test that fails loudly if it is ever weakened.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.db.models import DatasetFile, DatasetFileRole

logger = logging.getLogger(__name__)

STAGE_DIR = "data"
# `DatasetFileRole` is a StrEnum, so membership works for both the enum members
# and the plain `str` values SQLAlchemy hands back from Postgres.
STAGEABLE_ROLES = frozenset({DatasetFileRole.INPUT, DatasetFileRole.AUX})


@dataclass
class StagedFile:
    path: str
    bytes: int
    role: str


@dataclass
class StagedManifest:
    files: list[StagedFile] = field(default_factory=list)
    excluded_count: int = 0

    def as_prompt_block(self) -> str:
        lines = [f"  {f.path}  ({f.bytes:,} bytes)" for f in self.files]
        return "Files available in your workspace:\n" + "\n".join(lines)


async def stage_dataset(
    sandbox, run_id: str, files: Sequence[DatasetFile], store_ref
) -> StagedManifest:
    manifest = StagedManifest()

    for f in files:
        if f.role not in STAGEABLE_ROLES:
            # Never read it, never name it, never write it.
            manifest.excluded_count += 1
            continue
        data = store_ref.get_bytes(f.storage_key)
        path = f"{STAGE_DIR}/{f.filename}"
        await sandbox.write_file(run_id, path, data)
        manifest.files.append(StagedFile(path=path, bytes=len(data), role=str(f.role)))

    if not manifest.files:
        raise ValueError("no input files to stage: dataset has no input or aux files")

    logger.info(
        "staged %d files for run %s (%d withheld as ground truth)",
        len(manifest.files), run_id, manifest.excluded_count,
    )
    return manifest
