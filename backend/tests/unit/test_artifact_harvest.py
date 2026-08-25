from app.services.artifacts import classify_artifact, select_artifact_paths


def test_classification_by_extension():
    assert classify_artifact("segment.py") == "code"
    assert classify_artifact("preview.png") == "figure"
    assert classify_artifact("analysis_summary.md") == "report"
    assert classify_artifact("measurements.json") == "report"
    assert classify_artifact("segmentation.nii.gz") == "output"
    assert classify_artifact("run.log") == "log"


def test_declared_artifacts_are_always_selected():
    files = [{"path": "outputs/weird.dat", "bytes": 10}]
    declared = [{"path": "outputs/weird.dat", "kind": "output"}]
    assert "outputs/weird.dat" in select_artifact_paths(files, declared)


def test_interesting_files_are_selected_even_if_undeclared():
    files = [
        {"path": "segmentation.nii.gz", "bytes": 100},
        {"path": "preview.png", "bytes": 50},
        {"path": "script.py", "bytes": 20},
    ]
    selected = select_artifact_paths(files, [])
    assert {"segmentation.nii.gz", "preview.png", "script.py"} <= selected


def test_staged_inputs_are_not_re_harvested():
    files = [{"path": "data/t1.nii.gz", "bytes": 100}, {"path": "seg.nii.gz", "bytes": 100}]
    selected = select_artifact_paths(files, [])
    assert "data/t1.nii.gz" not in selected, "inputs are already stored; do not duplicate them"
    assert "seg.nii.gz" in selected


def test_declared_input_path_is_still_skipped():
    files = [{"path": "data/t1.nii.gz", "bytes": 100}]
    declared = [{"path": "data/t1.nii.gz", "kind": "output"}]
    assert select_artifact_paths(files, declared) == set()


def test_oversized_files_are_skipped():
    from app.services.artifacts import MAX_ARTIFACT_BYTES

    files = [{"path": "huge.nii.gz", "bytes": MAX_ARTIFACT_BYTES + 1}]
    assert select_artifact_paths(files, []) == set()


def test_junk_is_ignored():
    files = [
        {"path": "__pycache__/x.pyc", "bytes": 10},
        {"path": ".hidden", "bytes": 10},
        {"path": "result.json", "bytes": 10},
    ]
    assert select_artifact_paths(files, []) == {"result.json"}
