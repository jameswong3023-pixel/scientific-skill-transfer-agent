"""End-to-end A/B experiment against the real model and the real sandbox.

This is the test that actually answers the project's core question, so it is
also the slowest thing in the repository. Measured on the reference machine:
skill extraction alone was measured at 5m28s against `stealth/ox-alpha`, and a
full two-arm experiment at 9-15 minutes -- so the whole module is 15-25 minutes
of wall clock. It is gated behind an env flag for that reason.

    cd backend
    RUN_E2E=1 SSTA_API=http://localhost:8000 python -m pytest \\
        tests/integration/test_full_experiment.py -v -s
"""

import io
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest

API = os.getenv("SSTA_API", "http://localhost:8000").rstrip("/")
ROOT = Path(__file__).resolve().parents[3]

# Generous, because the upstream model genuinely rate-limits and retries.
EXTRACTION_TIMEOUT = int(os.getenv("E2E_EXTRACTION_TIMEOUT", "1800"))
EXPERIMENT_TIMEOUT = int(os.getenv("E2E_EXPERIMENT_TIMEOUT", "5400"))

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_E2E") != "1",
    reason="set RUN_E2E=1 to run the full experiment (takes 15-25 minutes)",
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API, timeout=httpx.Timeout(600.0, connect=10.0)) as c:
        yield c


def _wait(check, timeout: int, label: str):
    """Poll ``check`` until it returns something truthy, or fail loudly."""
    deadline = time.time() + timeout
    started = time.time()
    while time.time() < deadline:
        value = check()
        if value is not None:
            return value
        time.sleep(10)
        print(f"    ... still waiting for {label} ({int(time.time() - started)}s)", flush=True)
    raise AssertionError(f"timed out after {timeout}s waiting for {label}")


def _phantom_dir() -> Path:
    """The phantom volumes are generated, not committed.

    `.gitignore` excludes *.nii.gz so large binaries stay out of git; the
    deterministic generator is what is committed instead.
    """
    phantom = ROOT / "fixtures" / "phantom"
    if not (phantom / "t1.nii.gz").exists():
        sys.path.insert(0, str(ROOT / "scripts"))
        from make_phantom import save_phantom

        save_phantom(phantom)
    return phantom


def _sample_paper() -> Path:
    paper = ROOT / "fixtures" / "sample_methods_paper.pdf"
    if not paper.exists():
        sys.path.insert(0, str(ROOT / "scripts"))
        from make_sample_paper import build

        build(paper)
    return paper


@pytest.fixture(scope="module")
def experiment_run(client):
    """Runs one complete paper -> skill -> dataset -> A/B experiment.

    Module scoped so the three tests below inspect the same run. The plan
    originally had each test re-fetch `GET /api/experiments` and take element
    zero, which silently depends on list ordering and on nothing else having
    been created in between -- including by a developer clicking around the UI
    while the suite runs.
    """
    # --- paper -------------------------------------------------------------
    paper_path = _sample_paper()
    with paper_path.open("rb") as fh:
        response = client.post(
            "/api/papers", files={"file": (paper_path.name, fh, "application/pdf")}
        )
    response.raise_for_status()
    paper = response.json()
    assert paper["page_count"] >= 3

    # --- skill -------------------------------------------------------------
    client.post(f"/api/papers/{paper['id']}/extract").raise_for_status()

    def extracted():
        status = client.get(f"/api/papers/{paper['id']}").json()
        if status["status"] == "failed":
            raise AssertionError(f"extraction failed: {status.get('error')}")
        if status["status"] != "extracted":
            return None
        return client.get(f"/api/papers/{paper['id']}/skill").json()

    skill = _wait(extracted, EXTRACTION_TIMEOUT, "skill extraction")

    # --- dataset -----------------------------------------------------------
    phantom = _phantom_dir()
    dataset = client.post(
        "/api/datasets",
        json={"name": f"e2e-{uuid.uuid4().hex[:8]}", "modality": "MRI"},
    )
    dataset.raise_for_status()
    dataset = dataset.json()

    for filename, role in (("t1.nii.gz", "input"), ("ground_truth.nii.gz", "ground_truth")):
        with (phantom / filename).open("rb") as fh:
            client.post(
                f"/api/datasets/{dataset['id']}/files",
                files={"file": (filename, fh, "application/gzip")},
                data={"role": role},
            ).raise_for_status()

    # --- experiment --------------------------------------------------------
    experiment = client.post(
        "/api/experiments",
        json={
            "dataset_id": dataset["id"],
            "task_prompt": (
                "Segment the MRI into background, CSF, grey matter and white matter. "
                "Save segmentation.nii.gz (integer labels, same shape and affine as the "
                "input), measurements.json with per-tissue volumes in mm^3, preview.png "
                "and analysis_summary.md."
            ),
            "paper_id": paper["id"],
            "skill_version_id": skill["id"],
        },
    )
    experiment.raise_for_status()
    experiment = experiment.json()
    client.post(f"/api/experiments/{experiment['id']}/run").raise_for_status()

    def finished():
        body = client.get(f"/api/experiments/{experiment['id']}/comparison").json()
        return body if body["experiment"]["status"] in ("completed", "failed") else None

    comparison = _wait(finished, EXPERIMENT_TIMEOUT, "experiment completion")
    return {"paper": paper, "skill": skill, "experiment": experiment, "comparison": comparison}


def test_skill_extraction_produced_a_grounded_skill(experiment_run):
    skill = experiment_run["skill"]
    payload = skill["payload"]
    validation = skill["validation"]

    assert len(payload["algorithm_steps"]) >= 3, "a procedure needs steps to be a procedure"
    assert payload["name"], "the skill must be named"

    # Provenance is the point: every non-inferred field carries a verbatim quote
    # that must actually appear on the page it claims. A skill with zero verified
    # quotes is indistinguishable from the model's prior knowledge.
    print(
        f"\n  skill '{payload['name']}': {len(payload['algorithm_steps'])} steps, "
        f"{len(payload['parameters'])} parameters, "
        f"{validation.get('verified_quotes')} verified / "
        f"{validation.get('unverified_quotes')} unverified quotes"
    )
    assert validation.get("verified_quotes", 0) >= 1


def test_both_arms_ran_and_were_scored(experiment_run):
    comparison = experiment_run["comparison"]
    assert comparison["experiment"]["status"] == "completed"

    runs = {r["arm"]: r for r in comparison["runs"]}
    assert set(runs) == {"base", "skill"}, "both arms must exist"

    for arm, run in runs.items():
        assert run["status"] == "completed", f"{arm} arm failed: {run['error']}"
        artifacts = comparison["artifacts"].get(run["id"], [])
        assert artifacts, f"{arm} arm produced no artifacts"
        assert any(a["kind"] == "code" for a in artifacts), f"{arm} arm wrote no code"

    quality = comparison["metrics"]["quality"]
    for arm in ("base", "skill"):
        dice = quality.get(arm, {}).get("mean_dice", {}).get("value")
        assert dice is not None, f"{arm} arm was not scored"
        assert 0.0 <= dice <= 1.0

    system = comparison["metrics"]["system"]
    for arm in ("base", "skill"):
        assert system[arm]["code_executions"]["value"] >= 1, (
            f"{arm} arm never executed code -- it must compute, not just describe"
        )

    print(
        f"\n  base mean Dice  = {quality['base']['mean_dice']['value']:.4f}"
        f"\n  skill mean Dice = {quality['skill']['mean_dice']['value']:.4f}"
        f"\n  delta           = "
        f"{quality['skill']['mean_dice']['value'] - quality['base']['mean_dice']['value']:+.4f}"
    )


def test_ground_truth_never_entered_a_sandbox(experiment_run):
    """The experiment is only valid if neither agent could see the labels."""
    comparison = experiment_run["comparison"]
    for run in comparison["runs"]:
        for artifact in comparison["artifacts"].get(run["id"], []):
            assert "ground_truth" not in artifact["path"].lower(), (
                f"ground truth leaked into the {run['arm']} arm: {artifact['path']}"
            )


def test_zip_export_is_a_valid_archive(client, experiment_run):
    experiment_id = experiment_run["experiment"]["id"]
    response = client.get(f"/api/experiments/{experiment_id}/download")
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
        assert "experiment.json" in names
        assert "comparison/metrics.json" in names
        assert "skill/skill.json" in names
        assert any(n.startswith("base_agent/") for n in names)
        assert any(n.startswith("skill_agent/") for n in names)
        assert not any("ground_truth" in n.lower() for n in names)
        assert zf.testzip() is None, "archive is corrupt"
