"""Downloadable experiment archive.

The layout mirrors the structure in the brief so a reviewer can unzip it and
immediately find the paper, the skill, both agents' code and outputs, and the
comparison metrics.
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

ARM_DIR = {"base": "base_agent", "skill": "skill_agent"}

# Flush to the client roughly every 8 MiB rather than buffering a whole archive
# of volumes in the API process.
CHUNK_BYTES = 8 * 1024 * 1024


def _arm_subdir(kind: str) -> str:
    return "generated_code" if kind in ("code", "log") else "outputs"


def build_zip_layout(
    experiment,
    runs,
    artifacts_by_run,
    skill_version,
    metrics: dict | None = None,
    paper=None,
) -> dict[str, tuple[str, object]]:
    """Maps archive path -> (source, payload).

    source == "inline"  -> payload is bytes
    source == "storage" -> payload is an object-storage key to stream
    """
    layout: dict[str, tuple[str, object]] = {}

    layout["experiment.json"] = (
        "inline",
        json.dumps(
            {
                "id": str(experiment.id),
                "task": experiment.task_prompt,
                "status": experiment.status,
                "config": experiment.config,
            },
            indent=2,
            default=str,
        ).encode(),
    )

    # The source PDF is the provenance root of everything else in the archive:
    # without it a reader cannot check a quoted parameter against the paper it
    # was taken from. Normalised to `source.pdf` to match the brief's tree, so
    # the real upload name is preserved alongside it rather than lost.
    if paper is not None and getattr(paper, "storage_key", None):
        layout["paper/source.pdf"] = ("storage", paper.storage_key)
        layout["paper/paper.json"] = (
            "inline",
            json.dumps(
                {
                    "id": str(paper.id),
                    "title": paper.title,
                    "original_filename": paper.filename,
                    "page_count": paper.page_count,
                    "sha256": paper.sha256,
                    "status": paper.status,
                },
                indent=2,
                default=str,
            ).encode(),
        )

    if skill_version is not None:
        layout["skill/skill.json"] = (
            "inline",
            json.dumps(skill_version.payload, indent=2, default=str).encode(),
        )
        layout["skill/skill.md"] = ("inline", (skill_version.markdown or "").encode())

    for run in runs:
        directory = ARM_DIR.get(run.arm, run.arm)
        layout[f"{directory}/run.json"] = (
            "inline",
            json.dumps(
                {
                    "id": str(run.id),
                    "arm": run.arm,
                    "status": run.status,
                    "totals": run.totals,
                },
                indent=2,
                default=str,
            ).encode(),
        )
        for artifact in artifacts_by_run.get(str(run.id), []):
            path = f"{directory}/{_arm_subdir(artifact.kind)}/{artifact.path}"
            layout[path] = ("storage", artifact.storage_key)

    layout["comparison/metrics.json"] = (
        "inline",
        json.dumps(metrics or {}, indent=2, default=str).encode(),
    )
    return layout


class _ChunkedSink:
    """A write-only, non-seekable sink that hands out completed chunks.

    DEVIATION FROM PLAN: the plan streamed by rewinding and truncating a shared
    `BytesIO` between chunks. `zipfile` records each member's header offset from
    `fp.tell()`, so rewinding made every offset after the first flush restart at
    zero and produced an archive no unzipper could read — invisible in a small
    test, guaranteed in a real export of two segmentation volumes. Reporting a
    cumulative `tell()` and refusing `seek` keeps the offsets honest and makes
    `zipfile` emit data descriptors, which is the documented way to stream.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._offset = 0

    def write(self, data: bytes) -> int:
        self._buffer += data
        self._offset += len(data)
        return len(data)

    def tell(self) -> int:
        return self._offset

    def flush(self) -> None:
        return None

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def take(self) -> bytes:
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk


def write_zip(
    layout: dict[str, tuple[str, object]], fetch: Callable[[str], bytes]
) -> Iterator[bytes]:
    """Builds the archive, yielding bytes as entries are added.

    A missing or unreadable object is logged and skipped — one bad artifact must
    not cost the user the entire download.
    """
    sink = _ChunkedSink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, (source, payload) in sorted(layout.items()):
            try:
                data = payload if source == "inline" else fetch(payload)
            except Exception as exc:
                logger.warning("skipping %s in export: %s", path, exc)
                continue
            zf.writestr(path, data)
            if sink.pending > CHUNK_BYTES:
                yield sink.take()
    yield sink.take()
