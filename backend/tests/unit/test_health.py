from fastapi.testclient import TestClient

from app.main import app


def test_liveness_needs_no_dependencies():
    with TestClient(app) as client:
        r = client.get("/api/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_openapi_exposes_health():
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
        assert "/api/health/live" in spec["paths"]


def test_cors_allows_frontend_origin():
    with TestClient(app) as client:
        r = client.get("/api/health/live", headers={"Origin": "http://localhost:3000"})
        assert r.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000")
