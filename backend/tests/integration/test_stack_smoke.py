import os
import uuid

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.storage.s3 import store

# Matching on the compose service hostname rather than the substring
# "postgres": the unit-test conftest points DATABASE_URL at a closed loopback
# port whose driver name also contains "postgres", which would otherwise let
# these run -- and fail -- outside the stack.
pytestmark = pytest.mark.skipif(
    "@postgres:" not in os.getenv("DATABASE_URL", ""),
    reason="integration test requires the compose stack (run: make test-integration)",
)


async def test_database_has_every_domain_table():
    expected = {
        "users", "workspaces", "papers", "paper_pages", "skills", "skill_versions",
        "datasets", "dataset_files", "experiments", "runs", "agent_steps",
        "tool_calls", "artifacts", "metrics", "conversations", "messages",
    }
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            )
            actual = {r[0] for r in rows}
        assert expected <= actual, f"missing: {expected - actual}"
    finally:
        # pytest-asyncio gives each test its own event loop, but `engine` is a
        # module-level singleton whose pool outlives this one. A later test that
        # drives the app through TestClient runs on a different loop, finds those
        # pooled asyncpg connections bound to a dead loop, and the health check
        # silently reports database=False. Disposing here keeps the pool from
        # crossing loop boundaries.
        await engine.dispose()


def test_object_storage_round_trip():
    store.ensure_bucket()
    key = f"test/{uuid.uuid4()}.bin"
    payload = b"scientific-skill-transfer"
    result = store.put_bytes(key, payload, "application/octet-stream")
    assert result.bytes == len(payload)
    assert store.get_bytes(key) == payload
    assert key in store.list_prefix("test/")
    store.delete(key)
    assert not store.exists(key)


def test_health_endpoint_reports_all_dependencies_up():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["database"] is True
    assert body["redis"] is True
    assert body["storage"] is True
    assert body["status"] == "ok"
