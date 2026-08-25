import pytest

from app.services.datasets import validate_dataset_upload
from app.services.papers import UnsupportedUploadError


def test_accepts_scientific_formats():
    for name in ("t1.nii.gz", "stack.tif", "slice.dcm", "img.png", "vol.npy"):
        validate_dataset_upload(name, b"x" * 100)


def test_rejects_executables():
    with pytest.raises(UnsupportedUploadError):
        validate_dataset_upload("evil.exe", b"MZ" + b"x" * 100)


def test_rejects_scripts():
    with pytest.raises(UnsupportedUploadError):
        validate_dataset_upload("payload.py", b"import os")


def test_rejects_empty():
    with pytest.raises(UnsupportedUploadError):
        validate_dataset_upload("t1.nii.gz", b"")


def test_rejects_path_traversal_in_filename():
    with pytest.raises(UnsupportedUploadError):
        validate_dataset_upload("../../etc/passwd.nii.gz", b"x" * 100)


def test_dataset_file_output_never_leaks_storage_keys():
    from app.schemas.dataset import DatasetFileOut

    assert "storage_key" not in DatasetFileOut.model_fields
