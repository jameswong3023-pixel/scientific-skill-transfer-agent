from fastapi.testclient import TestClient

from app.main import app


def test_every_expected_route_is_registered():
    with TestClient(app) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    expected = {
        "/api/health",
        "/api/papers",
        "/api/papers/{paper_id}",
        "/api/papers/{paper_id}/extract",
        "/api/papers/{paper_id}/skill",
        "/api/datasets",
        "/api/datasets/{dataset_id}/files",
        "/api/datasets/files/{file_id}/slice",
        "/api/experiments",
        "/api/experiments/{experiment_id}/run",
        "/api/experiments/{experiment_id}/comparison",
        "/api/experiments/{experiment_id}/download",
        "/api/experiments/{experiment_id}/events",
        "/api/artifacts/{artifact_id}",
        "/api/artifacts/{artifact_id}/slice",
        "/api/artifacts/{artifact_id}/overlay",
        "/api/conversations",
        "/api/conversations/{conversation_id}/messages",
        "/api/runs/{run_id}/events",
    }
    assert expected <= paths, f"missing routes: {expected - paths}"
