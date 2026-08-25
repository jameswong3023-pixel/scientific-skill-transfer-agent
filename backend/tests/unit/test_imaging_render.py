import io

import numpy as np
import pytest
from PIL import Image

from app.imaging.render import (
    AXES,
    extract_slice,
    render_histogram_png,
    render_mask_overlay_png,
    render_slice_png,
    slice_count,
)


@pytest.fixture
def vol():
    return np.random.RandomState(0).rand(10, 12, 14).astype(np.float32)


def test_axis_names_map_to_dimensions():
    assert set(AXES) == {"axial", "coronal", "sagittal"}


def test_slice_count_per_axis(vol):
    assert slice_count(vol.shape, "sagittal") == 10
    assert slice_count(vol.shape, "coronal") == 12
    assert slice_count(vol.shape, "axial") == 14


def test_extract_slice_is_2d(vol):
    s = extract_slice(vol, "axial", 3)
    assert s.ndim == 2
    assert s.shape == (10, 12)


def test_index_is_clamped_not_crashed(vol):
    assert extract_slice(vol, "axial", 9999).ndim == 2
    assert extract_slice(vol, "axial", -5).ndim == 2


def test_render_returns_valid_png(vol):
    png = render_slice_png(vol, "axial", 7)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(png))
    assert img.size == (12, 10)  # PIL is (w, h); slice is (10, 12)


def test_2d_image_renders_at_index_zero():
    png = render_slice_png(np.zeros((16, 20), dtype=np.uint8), "axial", 0)
    assert Image.open(io.BytesIO(png)).size == (20, 16)


def test_mask_overlay_is_rgba_with_transparent_background():
    mask = np.zeros((8, 8, 3), dtype=np.uint8)
    mask[2:5, 2:5, 1] = 2
    png = render_mask_overlay_png(mask, "axial", 1)
    img = Image.open(io.BytesIO(png))
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0, "label 0 must be fully transparent"
    assert img.getpixel((3, 3))[3] > 0, "labelled voxel must be visible"


def test_distinct_labels_get_distinct_colours():
    mask = np.zeros((4, 6), dtype=np.uint8)
    mask[0, 0] = 1
    mask[0, 1] = 2
    mask[0, 2] = 3
    img = Image.open(io.BytesIO(render_mask_overlay_png(mask, "axial", 0)))
    colours = {img.getpixel((x, 0))[:3] for x in (0, 1, 2)}
    assert len(colours) == 3


def test_constant_image_does_not_divide_by_zero():
    png = render_slice_png(np.full((6, 6), 5.0), "axial", 0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_nan_values_are_survivable():
    arr = np.full((6, 6), np.nan)
    arr[0, 0] = 1.0
    assert render_slice_png(arr, "axial", 0)[:8] == b"\x89PNG\r\n\x1a\n"


def test_histogram_renders():
    assert render_histogram_png(np.random.rand(500))[:8] == b"\x89PNG\r\n\x1a\n"
