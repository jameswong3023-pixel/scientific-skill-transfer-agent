"""Exercises the failure modes the README claims to handle.

Runs inside the api container, because the hostile-code checks need to reach
the sandbox and `sandboxnet` is an internal network with no route from the host:

    docker compose exec -T -e RUN_INTEGRATION=1 api \\
        python -m pytest tests/integration/test_resilience.py -v

DEVIATION FROM PLAN: the plan's version of `test_sandbox_survives_hostile_code`
built a list of hostile programs and then never executed any of them -- it
looped over the list, ignored the code, and asserted the API was healthy. That
passes whether or not the sandbox contains anything, so it proved nothing. This
version actually submits each program to the sandbox and asserts on the verdict.
"""

import io
import os
import uuid

import httpx
import pytest

API = os.getenv("SSTA_API", "http://localhost:8000").rstrip("/")

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 and run inside the api container",
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API, timeout=120.0) as c:
        yield c


# ---------------------------------------------------------------------------
# Upload validation: hostile or malformed user files
# ---------------------------------------------------------------------------

def test_corrupt_pdf_is_rejected_with_a_clear_error(client):
    response = client.post(
        "/api/papers",
        files={"file": ("bad.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
    )
    assert response.status_code == 400
    assert "pdf" in response.json()["detail"].lower()


def test_non_pdf_extension_is_rejected(client):
    response = client.post(
        "/api/papers",
        files={"file": ("paper.docx", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert response.status_code == 400


def test_empty_upload_is_rejected(client):
    response = client.post(
        "/api/papers", files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    )
    assert response.status_code == 400


def test_malformed_image_upload_is_rejected(client):
    dataset = client.post(
        "/api/datasets", json={"name": f"resilience-{uuid.uuid4().hex[:6]}", "modality": "MRI"}
    ).json()
    response = client.post(
        f"/api/datasets/{dataset['id']}/files",
        files={
            "file": ("evil.exe", io.BytesIO(b"MZ" + b"\x00" * 200), "application/octet-stream")
        },
        data={"role": "input"},
    )
    assert response.status_code == 400


def test_path_traversal_in_a_dataset_filename_is_rejected(client):
    dataset = client.post(
        "/api/datasets", json={"name": f"resilience-{uuid.uuid4().hex[:6]}", "modality": "MRI"}
    ).json()
    response = client.post(
        f"/api/datasets/{dataset['id']}/files",
        files={"file": ("../../etc/passwd.nii.gz", io.BytesIO(b"\x1f\x8b"), "application/gzip")},
        data={"role": "input"},
    )
    assert response.status_code == 400


def test_unreadable_volume_reports_a_probe_error_rather_than_crashing(client):
    dataset = client.post(
        "/api/datasets", json={"name": f"resilience-{uuid.uuid4().hex[:6]}", "modality": "MRI"}
    ).json()
    response = client.post(
        f"/api/datasets/{dataset['id']}/files",
        files={"file": ("broken.nii.gz", io.BytesIO(b"\x1f\x8b garbage"), "application/gzip")},
        data={"role": "input"},
    )
    assert response.status_code == 201, "upload succeeds; the probe records the problem"
    metadata = response.json()["file_metadata"]
    assert "unreadable" in metadata or "probe_error" in metadata


def test_missing_experiment_returns_404(client):
    r = client.get("/api/experiments/00000000-0000-0000-0000-000000000000/comparison")
    assert r.status_code == 404


async def test_dataset_with_no_ground_truth_skips_evaluation_instead_of_failing(client):
    """Evaluation is optional. A dataset with no ground_truth file must skip
    scoring and let the run complete, not raise."""
    import uuid as _uuid

    from app.db.models import Experiment
    from app.db.session import AsyncSessionLocal, engine
    from app.services.experiments import evaluate_experiment

    dataset = client.post(
        "/api/datasets", json={"name": f"no-gt-{_uuid.uuid4().hex[:6]}", "modality": "MRI"}
    ).json()
    experiment = client.post(
        "/api/experiments",
        json={"dataset_id": dataset["id"], "task_prompt": "does not matter"},
    ).json()

    try:
        async with AsyncSessionLocal() as session:
            record = await session.get(Experiment, _uuid.UUID(experiment["id"]))
            outcome = await evaluate_experiment(session, record)
    finally:
        # `engine` is a module-level singleton but pytest-asyncio gives each test
        # its own event loop. Leaving an asyncpg connection in the pool binds it
        # to a loop that is about to close, and the next test to touch the engine
        # fails with "Event loop is closed" -- which is how this first showed up,
        # as a failure in test_stack_smoke rather than here.
        await engine.dispose()

    assert outcome == {"evaluated": False, "reason": "no ground truth in dataset"}


# ---------------------------------------------------------------------------
# Sandbox containment: agent-generated code is treated as hostile
# ---------------------------------------------------------------------------

HOSTILE = [
    # (label, code, expect_timeout)
    ("infinite loop", "import time\nwhile True:\n    time.sleep(0.05)", True),
    ("busy spin", "while True:\n    pass", True),
    ("memory bomb", "x = bytearray(50 * 1024**3)", False),
    ("read a host secret", "print(open('/etc/shadow').read())", False),
    ("network egress", "import socket\nsocket.create_connection(('1.1.1.1', 53), 5)", False),
    (
        "reach the model gateway",
        "import socket\nsocket.create_connection(('openrouter.ai', 443), 5)",
        False,
    ),
    ("steal the API key", "import os\nassert os.environ['OPENROUTER_API_KEY']", False),
]


@pytest.mark.parametrize("label,code,expect_timeout", HOSTILE, ids=[h[0] for h in HOSTILE])
async def test_sandbox_contains_hostile_code(client, label, code, expect_timeout):
    from app.sandbox.client import sandbox_client

    run_id = f"resilience-{uuid.uuid4().hex[:8]}"
    result = await sandbox_client.execute(run_id, code=code, timeout_s=15)

    assert not result.ok, f"{label!r} should NOT have succeeded: {result.as_observation()[:400]}"
    if expect_timeout:
        assert result.timed_out, f"{label!r} should have been killed by the wall-clock timeout"
    else:
        assert result.exit_code != 0

    # The failure comes back as an ordinary observation the agent can read and
    # react to. It is never an exception in the worker.
    assert isinstance(result.as_observation(), str)

    # And the service is still up afterwards.
    assert client.get("/api/health").json()["status"] == "ok", f"degraded after {label}"


async def test_sandbox_rejects_a_path_outside_the_run_workspace():
    from app.sandbox.client import sandbox_client

    with pytest.raises(httpx.HTTPStatusError) as exc:
        await sandbox_client.write_file(
            f"resilience-{uuid.uuid4().hex[:8]}", "../../etc/escape.txt", b"x"
        )
    assert exc.value.response.status_code == 400


async def test_sandbox_has_the_prebaked_scientific_stack_and_no_installer():
    """The sandbox has no network by design, so `pip install` cannot work.
    `list_packages` is how the agent discovers what it already has."""
    from app.sandbox.client import sandbox_client

    names = {p["name"].lower() for p in await sandbox_client.packages()}
    assert {"numpy", "scipy", "scikit-image", "nibabel", "simpleitk"} <= names

    run_id = f"resilience-{uuid.uuid4().hex[:8]}"
    install = (
        "import subprocess, sys\n"
        "subprocess.run(\n"
        "    [sys.executable, '-m', 'pip', 'install', 'requests'], check=True, timeout=25\n"
        ")\n"
    )
    result = await sandbox_client.execute(run_id, code=install, timeout_s=40)
    assert not result.ok, "pip install must fail: the sandbox has no route to PyPI"
