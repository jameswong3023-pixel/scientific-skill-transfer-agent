import io
import zipfile

from app.services.export import build_zip_layout, write_zip


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fixture():
    experiment = Obj(id="e1", task_prompt="Segment the MRI", status="completed",
                     config={"model": "stealth/ox-alpha"})
    runs = [
        Obj(id="r1", arm="base", status="completed",
            totals={"summary": "base summary", "iterations": 3}),
        Obj(id="r2", arm="skill", status="completed",
            totals={"summary": "skill summary", "iterations": 4}),
    ]
    artifacts = {
        "r1": [Obj(path="segmentation.nii.gz", storage_key="k1", kind="output"),
               Obj(path="segment.py", storage_key="k2", kind="code")],
        "r2": [Obj(path="segmentation.nii.gz", storage_key="k3", kind="output")],
    }
    skill = Obj(payload={"name": "BCFCM"}, markdown="# BCFCM", version=1)
    return experiment, runs, artifacts, skill


def _paper():
    return Obj(id="p1", title="A Modified Fuzzy C-Means Algorithm",
               filename="ahmed-et-al-2002.pdf", storage_key="papers/p1/source.pdf",
               sha256="ab" * 32, page_count=9, status="extracted")


def test_layout_matches_the_briefs_structure():
    layout = build_zip_layout(*_fixture(), metrics={"dice_delta": 0.2}, paper=_paper())
    paths = set(layout)
    assert "paper/source.pdf" in paths
    assert "skill/skill.json" in paths
    assert "skill/skill.md" in paths
    assert "base_agent/run.json" in paths
    assert "skill_agent/run.json" in paths
    assert "comparison/metrics.json" in paths


def test_code_and_outputs_are_separated_per_arm():
    layout = build_zip_layout(*_fixture(), metrics={})
    assert "base_agent/generated_code/segment.py" in layout
    assert "base_agent/outputs/segmentation.nii.gz" in layout
    assert "skill_agent/outputs/segmentation.nii.gz" in layout


def test_arms_do_not_collide_despite_identical_filenames():
    layout = build_zip_layout(*_fixture(), metrics={})
    base_key = layout["base_agent/outputs/segmentation.nii.gz"][1]
    skill_key = layout["skill_agent/outputs/segmentation.nii.gz"][1]
    assert base_key != skill_key


def test_experiment_manifest_is_inlined():
    layout = build_zip_layout(*_fixture(), metrics={})
    kind, payload = layout["experiment.json"]
    assert kind == "inline"
    assert b"Segment the MRI" in payload


def test_zip_is_readable():
    layout = {
        "readme.txt": ("inline", b"hello"),
        "nested/data.json": ("inline", b"{}"),
    }
    buf = io.BytesIO()
    for chunk in write_zip(layout, fetch=lambda key: b""):
        buf.write(chunk)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        assert set(zf.namelist()) == {"readme.txt", "nested/data.json"}
        assert zf.read("readme.txt") == b"hello"


def test_missing_object_does_not_break_the_archive():
    layout = {"a.bin": ("storage", "missing-key"), "b.txt": ("inline", b"ok")}

    def fetch(key):
        raise FileNotFoundError(key)

    buf = io.BytesIO()
    for chunk in write_zip(layout, fetch=fetch):
        buf.write(chunk)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        assert "b.txt" in zf.namelist()


def test_a_multi_chunk_archive_is_still_a_valid_archive():
    """Regression: the plan rewound the shared buffer between chunks, which
    restarted `zipfile`'s header offsets at 0 and corrupted every export large
    enough to flush more than once."""
    import random

    from app.services.export import CHUNK_BYTES

    # Random bytes so DEFLATE cannot shrink the fixture back under one chunk.
    payload = random.Random(20260824).randbytes(CHUNK_BYTES // 2)
    layout = {f"outputs/blob{i}.bin": ("inline", payload) for i in range(5)}

    buf = io.BytesIO()
    chunks = 0
    for chunk in write_zip(layout, fetch=lambda key: b""):
        chunks += 1
        buf.write(chunk)
    assert chunks > 1, "fixture must be big enough to stream in several chunks"

    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        assert zf.testzip() is None
        assert set(zf.namelist()) == set(layout)
        assert zf.read("outputs/blob3.bin") == payload


def test_the_source_paper_is_streamed_not_inlined():
    """The PDF is a large object: it must be fetched from storage, not held in
    the API process alongside the segmentation volumes."""
    layout = build_zip_layout(*_fixture(), metrics={}, paper=_paper())
    source, key = layout["paper/source.pdf"]
    assert source == "storage"
    assert key == "papers/p1/source.pdf"


def test_the_original_upload_name_survives_the_rename_to_source_pdf():
    layout = build_zip_layout(*_fixture(), metrics={}, paper=_paper())
    kind, payload = layout["paper/paper.json"]
    assert kind == "inline"
    assert b"ahmed-et-al-2002.pdf" in payload


def test_an_experiment_without_a_paper_still_exports():
    """Both arms can run with no skill at all; that archive just has no paper/."""
    layout = build_zip_layout(*_fixture(), metrics={}, paper=None)
    assert not any(p.startswith("paper/") for p in layout)
    assert "comparison/metrics.json" in layout
