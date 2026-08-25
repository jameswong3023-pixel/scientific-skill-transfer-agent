import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORK_ROOT", str(tmp_path))
    from executor.server import app

    return TestClient(app)


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_packages_lists_the_scientific_stack(client):
    names = {p["name"].lower() for p in client.get("/packages").json()["packages"]}
    assert "numpy" in names


def test_exec_runs_code(client):
    r = client.post("/exec", json={"run_id": "r1", "code": "print(6*7)"})
    body = r.json()
    assert r.status_code == 200
    assert body["exit_code"] == 0
    assert "42" in body["stdout"]


def test_exec_returns_failure_as_200_with_nonzero_exit(client):
    r = client.post("/exec", json={"run_id": "r1", "code": "1/0"})
    assert r.status_code == 200, "a failing script is data, not an HTTP error"
    assert r.json()["exit_code"] != 0
    assert "ZeroDivisionError" in r.json()["stderr"]


def test_write_then_read_round_trip(client):
    payload = base64.b64encode(b"volume-bytes").decode()
    w = client.post("/write", json={"run_id": "r1", "path": "data/in.bin", "content_b64": payload})
    assert w.status_code == 200
    got = client.get("/file", params={"run_id": "r1", "path": "data/in.bin"})
    assert got.content == b"volume-bytes"


def test_write_rejects_traversal(client):
    payload = base64.b64encode(b"x").decode()
    r = client.post("/write", json={"run_id": "r1", "path": "../evil", "content_b64": payload})
    assert r.status_code == 400


def test_files_listing(client):
    client.post("/exec", json={"run_id": "r2", "code": "open('o.txt','w').write('hi')"})
    files = {f["path"] for f in client.get("/files", params={"run_id": "r2"}).json()["files"]}
    assert "o.txt" in files


def test_reset_clears_workspace(client):
    client.post("/exec", json={"run_id": "r3", "code": "open('o.txt','w').write('hi')"})
    client.post("/reset", json={"run_id": "r3"})
    assert client.get("/files", params={"run_id": "r3"}).json()["files"] == []
