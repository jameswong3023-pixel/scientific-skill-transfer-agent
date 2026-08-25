from __future__ import annotations

import logging
import mimetypes
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dataset, DatasetFile, DatasetFileRole
from app.services.papers import UnsupportedUploadError
from app.storage.s3 import dataset_file_key, sha256_bytes, store

logger = logging.getLogger(__name__)

MAX_DATASET_FILE_BYTES = 500 * 1024 * 1024

SUPPORTED_DATA_SUFFIXES = (
    ".nii", ".nii.gz", ".mgz", ".mgh",
    ".tif", ".tiff", ".ome.tif", ".ome.tiff",
    ".dcm", ".dicom", ".ima",
    ".png", ".jpg", ".jpeg", ".bmp",
    ".npy", ".npz",
    ".json", ".csv", ".txt", ".md",
)


def validate_dataset_upload(filename: str, data: bytes) -> None:
    if not data:
        raise UnsupportedUploadError("empty upload")
    if len(data) > MAX_DATASET_FILE_BYTES:
        raise UnsupportedUploadError(f"file too large: {len(data)} bytes")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise UnsupportedUploadError(f"invalid filename: {filename}")
    if not filename.lower().endswith(SUPPORTED_DATA_SUFFIXES):
        raise UnsupportedUploadError(
            f"unsupported file type for {filename}; supported: {SUPPORTED_DATA_SUFFIXES}"
        )


async def create_dataset(
    session: AsyncSession, name: str, modality: str = "unknown", description: str = ""
) -> Dataset:
    dataset = Dataset(name=name, modality=modality, description=description)
    session.add(dataset)
    await session.flush()
    return dataset


def _probe(filename: str, data: bytes) -> dict:
    """Inspect the upload so the UI can show shape/spacing before any run."""
    from app.imaging.loaders import UnreadableImageError, describe

    suffix = "".join(Path(filename).suffixes[-2:]) or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        tmp = fh.name
    try:
        return describe(tmp, filename)
    except UnreadableImageError as exc:
        return {"unreadable": str(exc)}
    except Exception as exc:
        return {"probe_error": f"{type(exc).__name__}: {exc}"}
    finally:
        Path(tmp).unlink(missing_ok=True)


async def add_dataset_file(
    session: AsyncSession,
    dataset: Dataset,
    filename: str,
    data: bytes,
    role: str = DatasetFileRole.INPUT,
) -> DatasetFile:
    validate_dataset_upload(filename, data)
    if role not in tuple(DatasetFileRole):
        raise UnsupportedUploadError(f"invalid role {role!r}")

    key = dataset_file_key(dataset.id, role, filename)
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    store.put_bytes(key, data, media_type)

    record = DatasetFile(
        dataset_id=dataset.id,
        role=role,
        filename=filename,
        storage_key=key,
        sha256=sha256_bytes(data),
        bytes=len(data),
        media_type=media_type,
        file_metadata=_probe(filename, data),
    )
    session.add(record)
    await session.flush()
    return record


async def load_dataset_file_volume(file: DatasetFile):
    from app.services.experiments import _load_array

    return _load_array(store.get_bytes(file.storage_key), file.filename)
