import uuid

import pytest

from app.datasets.staging import stage_dataset
from app.db.models import DatasetFile, DatasetFileRole


class FakeStore:
    def __init__(self):
        self.reads: list[str] = []

    def get_bytes(self, key: str) -> bytes:
        self.reads.append(key)
        return b"payload-" + key.encode()


class FakeSandbox:
    def __init__(self):
        self.written: dict[str, bytes] = {}

    async def write_file(self, run_id, path, data):
        self.written[path] = data


def _file(role: str, name: str) -> DatasetFile:
    return DatasetFile(
        dataset_id=uuid.uuid4(), role=role, filename=name,
        storage_key=f"datasets/x/{role}/{name}", sha256="s", bytes=8,
    )


async def test_input_files_are_staged():
    sb, st = FakeSandbox(), FakeStore()
    files = [_file(DatasetFileRole.INPUT, "t1.nii.gz")]
    manifest = await stage_dataset(sb, "run-1", files, st)
    assert "data/t1.nii.gz" in sb.written
    assert manifest.files[0].path == "data/t1.nii.gz"


async def test_ground_truth_is_never_staged():
    sb, st = FakeSandbox(), FakeStore()
    files = [
        _file(DatasetFileRole.INPUT, "t1.nii.gz"),
        _file(DatasetFileRole.GROUND_TRUTH, "labels.nii.gz"),
    ]
    manifest = await stage_dataset(sb, "run-1", files, st)

    assert "data/t1.nii.gz" in sb.written
    assert not any("labels" in p for p in sb.written), "GROUND TRUTH LEAKED INTO SANDBOX"
    assert manifest.excluded_count == 1
    # It must not even be read out of object storage.
    assert not any("ground_truth" in k for k in st.reads)


async def test_manifest_never_mentions_ground_truth_filenames():
    sb, st = FakeSandbox(), FakeStore()
    files = [
        _file(DatasetFileRole.INPUT, "t1.nii.gz"),
        _file(DatasetFileRole.GROUND_TRUTH, "phantom_truth.nii.gz"),
    ]
    manifest = await stage_dataset(sb, "run-1", files, st)
    blob = repr(manifest)
    assert "phantom_truth" not in blob, "GT filename would hint at the answer"


async def test_aux_files_are_staged():
    sb, st = FakeSandbox(), FakeStore()
    manifest = await stage_dataset(sb, "run-1", [_file(DatasetFileRole.AUX, "readme.txt")], st)
    assert "data/readme.txt" in sb.written
    assert manifest.excluded_count == 0


async def test_empty_input_set_raises():
    sb, st = FakeSandbox(), FakeStore()
    with pytest.raises(ValueError, match="no input files"):
        await stage_dataset(sb, "run-1", [_file(DatasetFileRole.GROUND_TRUTH, "gt.nii.gz")], st)


async def test_plain_string_roles_are_filtered_identically():
    """Rows loaded from Postgres carry plain `str` roles, not StrEnum members.
    The filter must behave the same either way or ground truth could leak.
    """
    sb, st = FakeSandbox(), FakeStore()
    files = [_file("input", "t1.nii.gz"), _file("ground_truth", "labels.nii.gz")]
    manifest = await stage_dataset(sb, "run-1", files, st)
    assert list(sb.written) == ["data/t1.nii.gz"]
    assert manifest.excluded_count == 1
