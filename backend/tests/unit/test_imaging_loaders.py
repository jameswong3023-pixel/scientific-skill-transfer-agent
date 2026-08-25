import numpy as np
import pytest

from app.imaging.loaders import (
    UnreadableImageError,
    describe,
    load_volume,
    register_adapter,
)


def _nifti_bytes(tmp_path, shape=(8, 9, 10)):
    import nibabel as nib

    arr = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    img = nib.Nifti1Image(arr, affine=np.diag([1.5, 1.5, 3.0, 1.0]))
    p = tmp_path / "v.nii.gz"
    nib.save(img, str(p))
    return p


def test_loads_nifti_with_shape_and_spacing(tmp_path):
    p = _nifti_bytes(tmp_path)
    vol = load_volume(p, "v.nii.gz")
    assert vol.data.shape == (8, 9, 10)
    assert vol.meta.ndim == 3
    assert vol.meta.spacing == pytest.approx((1.5, 1.5, 3.0))
    assert vol.meta.modality == "nifti"


def test_loads_png(tmp_path):
    from PIL import Image

    p = tmp_path / "i.png"
    Image.fromarray(np.zeros((16, 24), dtype=np.uint8)).save(p)
    vol = load_volume(p, "i.png")
    assert vol.data.shape[:2] == (16, 24)
    assert vol.meta.modality == "image"


def test_loads_tiff_stack(tmp_path):
    import tifffile

    p = tmp_path / "s.tif"
    tifffile.imwrite(str(p), np.zeros((5, 12, 13), dtype=np.uint16))
    vol = load_volume(p, "s.tif")
    assert vol.data.shape == (5, 12, 13)
    assert vol.meta.modality == "tiff"


def test_describe_returns_metadata_without_loading_everything(tmp_path):
    p = _nifti_bytes(tmp_path)
    d = describe(p, "v.nii.gz")
    assert d["shape"] == [8, 9, 10]
    assert d["ndim"] == 3
    assert "value_range" in d and "dtype" in d


def test_unknown_extension_raises_typed_error(tmp_path):
    p = tmp_path / "x.weird"
    p.write_bytes(b"nonsense")
    with pytest.raises(UnreadableImageError):
        load_volume(p, "x.weird")


def test_corrupt_file_raises_typed_error(tmp_path):
    p = tmp_path / "bad.nii.gz"
    p.write_bytes(b"not a nifti at all")
    with pytest.raises(UnreadableImageError):
        load_volume(p, "bad.nii.gz")


def test_new_modality_registers_without_touching_core(tmp_path):
    def fake_adapter(path, filename):
        from app.imaging.loaders import LoadedVolume, VolumeMeta

        arr = np.ones((2, 2))
        return LoadedVolume(
            data=arr,
            meta=VolumeMeta(
                shape=(2, 2), ndim=2, dtype="float64", spacing=None,
                modality="fake", value_range=(1.0, 1.0), extra={},
            ),
        )

    register_adapter((".fake",), fake_adapter)
    p = tmp_path / "x.fake"
    p.write_bytes(b"")
    assert load_volume(p, "x.fake").meta.modality == "fake"
