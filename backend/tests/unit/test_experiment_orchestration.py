from app.services.experiments import (
    find_prediction_artifact,
    system_metrics_for,
)


class FakeArtifact:
    def __init__(self, path, kind="output", metadata=None):
        self.path = path
        self.kind = kind
        self.artifact_metadata = metadata or {}


def test_prefers_an_artifact_named_like_a_segmentation():
    artifacts = [
        FakeArtifact("preview.png", "figure"),
        FakeArtifact("segmentation.nii.gz"),
        FakeArtifact("bias_field.nii.gz"),
    ]
    assert find_prediction_artifact(artifacts).path == "segmentation.nii.gz"


def test_ignores_figures_and_reports():
    artifacts = [FakeArtifact("preview.png", "figure"), FakeArtifact("summary.md", "report")]
    assert find_prediction_artifact(artifacts) is None


def test_falls_back_to_the_only_volume_output():
    artifacts = [FakeArtifact("result_volume.nii.gz")]
    assert find_prediction_artifact(artifacts).path == "result_volume.nii.gz"


def test_bias_field_is_not_mistaken_for_a_segmentation():
    artifacts = [FakeArtifact("bias_field.nii.gz"), FakeArtifact("labels.nii.gz")]
    assert find_prediction_artifact(artifacts).path == "labels.nii.gz"


def test_a_brain_mask_does_not_outrank_the_segmentation():
    """Regression, from a real skill-arm run that wrote both.

    "mask" is a weaker hint than "segmentation", so ranking has to be ordered
    rather than first-match. The comparison view mirrors this ranking; when the
    two disagreed, the page drew a binary brain mask next to a four-class Dice
    of 0.9948 and nothing looked wrong.
    """
    artifacts = [
        FakeArtifact("bcfcm_out.npy"),
        FakeArtifact("bias_field.nii.gz"),
        FakeArtifact("brainmask.npy"),
        FakeArtifact("centroids.npy"),
        FakeArtifact("corrected_image.nii.gz"),
        FakeArtifact("memberships.npy"),
        FakeArtifact("segmentation.nii.gz"),
    ]
    assert find_prediction_artifact(artifacts).path == "segmentation.nii.gz"


def test_the_scored_artifact_is_named_on_the_result(monkeypatch):
    """`prediction_artifact` is a contract, not a debug field: the comparison
    view reads it to decide which volume to draw, so that the picture and the
    Dice score below it always describe the same file."""
    from app.services import experiments

    monkeypatch.setattr(
        experiments.store, "get_bytes", lambda key: (_ for _ in ()).throw(OSError("nope"))
    )
    artifacts = [FakeArtifact("brainmask.npy"), FakeArtifact("segmentation.nii.gz")]
    for a in artifacts:
        a.storage_key = f"runs/r1/{a.path}"

    scores = experiments._score_run_prediction(artifacts, truth_data=None, spacing=None)
    assert scores["prediction_artifact"] == "segmentation.nii.gz"


def test_system_metrics_capture_the_comparable_dimensions():
    result = {
        "iterations": 4, "executions": 6, "failed_executions": 2,
        "usage": {"total_tokens": 12345, "cost": 0.0},
    }
    metrics = system_metrics_for(result, duration_s=42.5)
    keys = {m[0] for m in metrics}
    assert {"agent_steps", "code_executions", "failed_executions",
            "runtime_seconds", "total_tokens", "cost"} <= keys
    assert dict(metrics)["failed_executions"] == 2
    assert dict(metrics)["runtime_seconds"] == 42.5
