"""The papers router must actually be mounted on the app.

Plan 03 Task 6 Step 6 is a one-line edit to `main.py`; without a test it is the
kind of step that silently regresses when someone reorders imports.
"""

from fastapi.testclient import TestClient

from app.main import app


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_paper_routes_are_mounted():
    paths = _paths()
    for expected in (
        "/api/papers",
        "/api/papers/{paper_id}",
        "/api/papers/{paper_id}/pages/{page_number}",
        "/api/papers/{paper_id}/pages/{page_number}/text",
        "/api/papers/{paper_id}/skill",
    ):
        assert expected in paths, f"{expected} is not registered on the app"


def test_health_route_still_mounted():
    assert any(p.startswith("/health") or p == "/api/health" for p in _paths())


def test_upload_rejects_a_non_pdf_with_400():
    """Rejection happens before any DB or object-store call, so this is a true
    unit test: no stack required, and no network touched."""
    with TestClient(app) as client:
        resp = client.post(
            "/api/papers",
            files={"file": ("notes.pdf", b"PK\x03\x04 this is a zip", "application/pdf")},
        )
    assert resp.status_code == 400
    assert "not a PDF" in resp.json()["detail"]


def test_upload_rejects_a_bad_extension_with_400():
    with TestClient(app) as client:
        resp = client.post(
            "/api/papers",
            files={"file": ("paper.docx", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"]
