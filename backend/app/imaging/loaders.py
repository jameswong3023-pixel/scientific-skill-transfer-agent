"""Modality-agnostic image loading.

Adding a new scientific format means writing one adapter function and calling
register_adapter(). Nothing in the agent, API, or renderer changes — which is
what keeps the architecture from being hard-coded to MRI.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


class UnreadableImageError(Exception):
    """The file could not be interpreted as a supported scientific image."""


@dataclass
class VolumeMeta:
    shape: tuple[int, ...]
    ndim: int
    dtype: str
    spacing: tuple[float, ...] | None
    modality: str
    value_range: tuple[float, float]
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": list(self.shape),
            "ndim": self.ndim,
            "dtype": self.dtype,
            "spacing": list(self.spacing) if self.spacing else None,
            "modality": self.modality,
            "value_range": [float(self.value_range[0]), float(self.value_range[1])],
            **self.extra,
        }


@dataclass
class LoadedVolume:
    data: np.ndarray
    meta: VolumeMeta


Adapter = Callable[[Path, str], LoadedVolume]
_ADAPTERS: dict[str, Adapter] = {}


def register_adapter(extensions: Iterable[str], fn: Adapter) -> None:
    for ext in extensions:
        _ADAPTERS[ext.lower()] = fn


def _ext_of(filename: str) -> str:
    low = filename.lower()
    if low.endswith(".nii.gz"):
        return ".nii.gz"
    if low.endswith(".ome.tif") or low.endswith(".ome.tiff"):
        return ".tif"
    return Path(low).suffix


def _meta_from(arr: np.ndarray, modality: str, spacing, extra=None) -> VolumeMeta:
    finite = arr[np.isfinite(arr)] if arr.size else arr
    vmin = float(finite.min()) if finite.size else 0.0
    vmax = float(finite.max()) if finite.size else 0.0
    return VolumeMeta(
        shape=tuple(int(s) for s in arr.shape),
        ndim=int(arr.ndim),
        dtype=str(arr.dtype),
        spacing=spacing,
        modality=modality,
        value_range=(vmin, vmax),
        extra=extra or {},
    )


def _load_nifti(path: Path, filename: str) -> LoadedVolume:
    import nibabel as nib

    img = nib.load(str(path))
    arr = np.asarray(img.dataobj)
    zooms = tuple(float(z) for z in img.header.get_zooms()[: arr.ndim])
    extra = {
        "affine": np.asarray(img.affine).tolist(),
        "units": str(img.header.get_xyzt_units()),
    }
    return LoadedVolume(data=arr, meta=_meta_from(arr, "nifti", zooms, extra))


def _load_tiff(path: Path, filename: str) -> LoadedVolume:
    import tifffile

    arr = tifffile.imread(str(path))
    arr = np.asarray(arr)
    return LoadedVolume(data=arr, meta=_meta_from(arr, "tiff", None))


def _load_dicom(path: Path, filename: str) -> LoadedVolume:
    import pydicom

    ds = pydicom.dcmread(str(path))
    arr = np.asarray(ds.pixel_array)
    spacing = None
    if hasattr(ds, "PixelSpacing"):
        ps = [float(x) for x in ds.PixelSpacing]
        thick = float(getattr(ds, "SliceThickness", 1.0))
        spacing = tuple(ps + [thick]) if arr.ndim == 3 else tuple(ps)
    extra = {
        "study_description": str(getattr(ds, "StudyDescription", "")),
        "modality_tag": str(getattr(ds, "Modality", "")),
    }
    return LoadedVolume(data=arr, meta=_meta_from(arr, "dicom", spacing, extra))


def _load_pillow(path: Path, filename: str) -> LoadedVolume:
    from PIL import Image

    with Image.open(path) as im:
        im.load()
        arr = np.asarray(im)
        mode = str(im.mode)
    return LoadedVolume(data=arr, meta=_meta_from(arr, "image", None, {"mode": mode}))


def _load_npy(path: Path, filename: str) -> LoadedVolume:
    arr = np.load(str(path), allow_pickle=False)
    return LoadedVolume(data=arr, meta=_meta_from(arr, "array", None))


register_adapter((".nii", ".nii.gz", ".mgz", ".mgh"), _load_nifti)
register_adapter((".tif", ".tiff"), _load_tiff)
register_adapter((".dcm", ".dicom", ".ima"), _load_dicom)
register_adapter((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"), _load_pillow)
register_adapter((".npy",), _load_npy)


def load_volume(path: Path | str, filename: str | None = None) -> LoadedVolume:
    path = Path(path)
    filename = filename or path.name
    ext = _ext_of(filename)
    adapter = _ADAPTERS.get(ext)
    if adapter is None:
        raise UnreadableImageError(
            f"unsupported image format '{ext}' for {filename}; "
            f"supported: {sorted(_ADAPTERS)}"
        )
    try:
        return adapter(path, filename)
    except UnreadableImageError:
        raise
    except Exception as exc:
        raise UnreadableImageError(
            f"could not read {filename}: {type(exc).__name__}: {exc}"
        ) from exc


def describe(path: Path | str, filename: str | None = None) -> dict[str, Any]:
    """Metadata for the agent's inspect_image tool."""
    vol = load_volume(path, filename)
    d = vol.meta.to_dict()
    arr = vol.data
    if arr.size:
        finite = arr[np.isfinite(arr)]
        if finite.size:
            d["mean"] = float(finite.mean())
            d["std"] = float(finite.std())
            d["percentiles"] = {
                p: float(np.percentile(finite, p)) for p in (1, 25, 50, 75, 99)
            }
            uniques = np.unique(finite[: min(finite.size, 2_000_000)])
            d["n_unique_sampled"] = int(uniques.size)
            d["looks_like_labels"] = bool(
                uniques.size <= 32 and np.allclose(uniques, np.round(uniques))
            )
    return d


def supported_extensions() -> list[str]:
    return sorted(_ADAPTERS)
