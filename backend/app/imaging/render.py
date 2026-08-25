"""Server-side slice rendering.

Rendering on the server means the browser needs no NIfTI/DICOM parser and no
WebGL, and every modality reaches the UI through one code path. Masks render as
separate transparent RGBA PNGs so the client can stack them over the base slice
with a CSS opacity slider.
"""

from __future__ import annotations

import io

import numpy as np

AXES: dict[str, int] = {"sagittal": 0, "coronal": 1, "axial": 2}

# Colour-blind-safe qualitative palette; index 0 is reserved for "no label".
LABEL_PALETTE: list[tuple[int, int, int]] = [
    (0, 0, 0),
    (230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48),
    (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60),
    (250, 190, 212), (0, 128, 128), (220, 190, 255), (170, 110, 40),
]


def _axis_index(shape: tuple[int, ...], axis: str) -> int:
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}; expected one of {sorted(AXES)}")
    if len(shape) < 3:
        return 0
    return AXES[axis]


def slice_count(shape: tuple[int, ...], axis: str) -> int:
    if len(shape) < 3:
        return 1
    return int(shape[_axis_index(shape, axis)])


def extract_slice(data: np.ndarray, axis: str, index: int) -> np.ndarray:
    arr = np.asarray(data)
    if arr.ndim == 2:
        return arr
    if arr.ndim > 3:
        # Collapse trailing channels/time: take the first volume.
        arr = arr[..., 0] if arr.shape[-1] <= 4 else arr.reshape(arr.shape[:3])
    ax = _axis_index(arr.shape, axis)
    n = arr.shape[ax]
    idx = int(np.clip(index, 0, n - 1))
    return np.take(arr, idx, axis=ax)


def _normalize(sl: np.ndarray, window: tuple[float, float] | None) -> np.ndarray:
    sl = np.asarray(sl, dtype=np.float64)
    finite = sl[np.isfinite(sl)]
    if window is not None:
        lo, hi = window
    elif finite.size:
        lo, hi = float(np.percentile(finite, 1)), float(np.percentile(finite, 99))
    else:
        lo, hi = 0.0, 1.0
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = float(finite.min()) if finite.size else 0.0
        hi = float(finite.max()) if finite.size else 1.0
    if hi <= lo:
        hi = lo + 1.0
    out = (np.nan_to_num(sl, nan=lo, posinf=hi, neginf=lo) - lo) / (hi - lo)
    return np.clip(out, 0.0, 1.0)


def _to_png(img_array: np.ndarray, mode: str) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(img_array, mode=mode).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _apply_cmap(norm: np.ndarray, cmap: str) -> np.ndarray:
    if cmap in ("gray", "grey"):
        return (norm * 255).astype(np.uint8)
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import colormaps

    table = colormaps[cmap]
    rgba = table(norm)
    return (rgba[..., :3] * 255).astype(np.uint8)


def render_slice_png(
    data: np.ndarray,
    axis: str = "axial",
    index: int = 0,
    cmap: str = "gray",
    window: tuple[float, float] | None = None,
) -> bytes:
    sl = extract_slice(data, axis, index)
    norm = _normalize(sl, window)
    if cmap in ("gray", "grey"):
        return _to_png(_apply_cmap(norm, cmap), "L")
    return _to_png(_apply_cmap(norm, cmap), "RGB")


def render_mask_overlay_png(
    mask: np.ndarray,
    axis: str = "axial",
    index: int = 0,
    alpha: float = 0.55,
    palette: list[tuple[int, int, int]] | None = None,
) -> bytes:
    sl = extract_slice(mask, axis, index)
    labels = np.nan_to_num(np.asarray(sl), nan=0).astype(np.int64)
    colours = palette or LABEL_PALETTE
    h, w = labels.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for label in np.unique(labels):
        if label == 0:
            continue  # background stays fully transparent
        r, g, b = colours[int(label) % len(colours)]
        sel = labels == label
        rgba[sel, 0], rgba[sel, 1], rgba[sel, 2] = r, g, b
        rgba[sel, 3] = int(np.clip(alpha, 0, 1) * 255)
    return _to_png(rgba, "RGBA")


def render_histogram_png(data: np.ndarray, bins: int = 64) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arr = np.asarray(data).ravel()
    arr = arr[np.isfinite(arr)]
    fig, ax = plt.subplots(figsize=(4, 2.4), dpi=120)
    if arr.size:
        ax.hist(arr, bins=bins, color="#3b82f6")
    ax.set_xlabel("intensity")
    ax.set_ylabel("count")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
