import uuid

from app.storage.s3 import (
    artifact_key,
    dataset_file_key,
    paper_key,
    paper_page_key,
    sha256_bytes,
)


def test_sha256_is_stable_and_hex():
    h = sha256_bytes(b"hello")
    assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert len(h) == 64


def test_keys_are_namespaced_by_entity():
    pid = uuid.uuid4()
    assert paper_key(pid, "a.pdf") == f"papers/{pid}/source.pdf"
    assert paper_page_key(pid, 3) == f"papers/{pid}/pages/003.png"


def test_ground_truth_files_get_a_separate_prefix():
    did = uuid.uuid4()
    inp = dataset_file_key(did, "input", "t1.nii.gz")
    gt = dataset_file_key(did, "ground_truth", "labels.nii.gz")
    assert inp == f"datasets/{did}/input/t1.nii.gz"
    assert gt == f"datasets/{did}/ground_truth/labels.nii.gz"
    # A prefix listing of inputs must never surface ground truth.
    assert not gt.startswith(f"datasets/{did}/input/")


def test_artifact_key_scoped_by_run():
    rid = uuid.uuid4()
    assert artifact_key(rid, "outputs/seg.nii.gz") == f"runs/{rid}/outputs/seg.nii.gz"


def test_artifact_key_rejects_traversal():
    rid = uuid.uuid4()
    for bad in ("../escape", "a/../../b", "/abs/path"):
        try:
            artifact_key(rid, bad)
        except ValueError:
            continue
        raise AssertionError(f"traversal not rejected: {bad}")


def test_dataset_file_key_rejects_traversal():
    did = uuid.uuid4()
    for bad in ("../../etc/passwd", "/abs.nii.gz"):
        try:
            dataset_file_key(did, "input", bad)
        except ValueError:
            continue
        raise AssertionError(f"traversal not rejected: {bad}")
