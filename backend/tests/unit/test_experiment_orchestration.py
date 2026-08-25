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
