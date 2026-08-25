"""One-command demo: paper -> skill -> dataset -> A/B experiment.

Drives the public HTTP API rather than importing internals, so a successful run
is genuine end-to-end evidence that the product works.

    python scripts/seed_demo.py            # launch and return immediately
    python scripts/seed_demo.py --wait     # block until the comparison is scored

If the API is published on a port other than 8000 -- on Windows, Hyper-V often
reserves 8000 -- point the script at it:

    SSTA_API=http://localhost:8200 python scripts/seed_demo.py --wait
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = os.getenv("SSTA_API", "http://localhost:8000").rstrip("/")
UI = os.getenv("SSTA_UI", "http://localhost:3000").rstrip("/")

# The filename matters. `find_prediction_artifact` in app/services/experiments.py
# ranks candidate outputs by name and rejects anything that looks like a bias
# field, preview or overlay, so the task must name the label map explicitly or a
# perfectly good segmentation goes unscored.
TASK = (
    "Segment the provided MRI volume into its tissue classes (background, cerebrospinal "
    "fluid, grey matter, and white matter) and calculate the volume of each tissue type in "
    "cubic millimetres.\n\n"
    "Produce these files:\n"
    "  - segmentation.nii.gz : the label volume, same shape and affine as the input,\n"
    "                          integer labels 0=background 1=CSF 2=grey matter 3=white matter\n"
    "  - measurements.json   : the volume of each tissue class in mm^3\n"
    "  - preview.png         : a mid-axial slice with the segmentation overlaid\n"
    "  - analysis_summary.md : what you did, the parameters you used, and your confidence"
)


def wait_for_api(client: httpx.Client, timeout: float = 180.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            body = client.get(f"{API}/api/health").json()
            if body.get("status") == "ok":
                print(f"API healthy at {API}")
                return
            last = str(body)
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        print(f"  waiting for the API ... {last}")
        time.sleep(3)
    raise SystemExit(f"API at {API} did not become healthy in time (last: {last})")


def ensure_phantom() -> Path:
    """Generate the phantom if it is not on disk.

    The generator is committed, not the volumes: `.gitignore` excludes *.nii.gz
    so that large binaries stay out of git. Generation is deterministic, so
    every machine produces the same phantom.
    """
    phantom_dir = ROOT / "fixtures" / "phantom"
    if not (phantom_dir / "t1.nii.gz").exists():
        print("Generating the synthetic phantom ...")
        sys.path.insert(0, str(ROOT / "scripts"))
        from make_phantom import save_phantom

        save_phantom(phantom_dir)
    return phantom_dir


def ensure_paper() -> Path:
    """Prefer a real paper the user dropped in; otherwise build the sample."""
    user_paper = ROOT / "fixtures" / "paper.pdf"
    if user_paper.exists():
        print(f"Using your paper: {user_paper.name}")
        return user_paper

    sample = ROOT / "fixtures" / "sample_methods_paper.pdf"
    if not sample.exists():
        sys.path.insert(0, str(ROOT / "scripts"))
        from make_sample_paper import build

        build(sample)
    print(f"Using the bundled sample paper: {sample.name}")
    return sample


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait", action="store_true", help="block until the experiment finishes"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5400,
        help="seconds to wait for the experiment when --wait is given",
    )
    parser.add_argument(
        "--extract-timeout",
        type=int,
        default=1800,
        help="seconds to wait for skill extraction",
    )
    args = parser.parse_args()

    # Long read timeout: uploading a volume and starting a job are both quick,
    # but the health probe touches Postgres, Redis and MinIO on a cold stack.
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        wait_for_api(client)

        # 1. Paper ----------------------------------------------------------
        paper_path = ensure_paper()
        print("\n[1/4] Uploading the paper ...")
        with paper_path.open("rb") as fh:
            response = client.post(
                f"{API}/api/papers",
                files={"file": (paper_path.name, fh, "application/pdf")},
            )
        response.raise_for_status()
        paper = response.json()
        print(f"      paper {paper['id']} ({paper['page_count']} pages)")

        # 2. Skill ----------------------------------------------------------
        # Measured: a real extraction against stealth/ox-alpha took 5m28s for the
        # bundled 4-page sample. The model is slow under load, and the graph runs
        # a validation and repair loop on top of the extraction call.
        print("\n[2/4] Extracting the skill (measured at 5-8 minutes) ...")
        started = time.time()
        client.post(f"{API}/api/papers/{paper['id']}/extract").raise_for_status()

        skill = None
        deadline = time.time() + args.extract_timeout
        while time.time() < deadline:
            time.sleep(10)
            status = client.get(f"{API}/api/papers/{paper['id']}").json()
            if status["status"] == "extracted":
                skill = client.get(f"{API}/api/papers/{paper['id']}/skill").json()
                break
            if status["status"] == "failed":
                raise SystemExit(f"extraction failed: {status.get('error')}")
            print(f"      status: {status['status']} ... ({_mmss(time.time() - started)})")

        if skill is None:
            raise SystemExit("skill extraction timed out")

        validation = skill.get("validation") or {}
        payload = skill["payload"]
        print(
            f"      extracted '{payload['name']}' in {_mmss(time.time() - started)} -- "
            f"{len(payload.get('algorithm_steps', []))} steps, "
            f"{len(payload.get('parameters', []))} parameters, "
            f"{validation.get('verified_quotes', 0)} verified quotes, "
            f"{validation.get('unverified_quotes', 0)} unverified"
        )

        # 3. Dataset -- note the roles --------------------------------------
        print("\n[3/4] Creating the dataset ...")
        phantom_dir = ensure_phantom()
        dataset = client.post(
            f"{API}/api/datasets",
            json={
                "name": "Synthetic brain phantom (bias field)",
                "modality": "MRI",
                "description": (
                    "64^3 T1-like phantom, 2 mm isotropic, with a smooth multiplicative "
                    "bias field and Rician noise. Generated by scripts/make_phantom.py."
                ),
            },
        )
        dataset.raise_for_status()
        dataset = dataset.json()

        for filename, role in (
            ("t1.nii.gz", "input"),
            ("ground_truth.nii.gz", "ground_truth"),
        ):
            with (phantom_dir / filename).open("rb") as fh:
                uploaded = client.post(
                    f"{API}/api/datasets/{dataset['id']}/files",
                    files={"file": (filename, fh, "application/gzip")},
                    data={"role": role},
                )
            uploaded.raise_for_status()
            print(f"      {filename} -> role={role}")
        print("      ground_truth is withheld from both sandboxes; only the")
        print("      evaluator reads it, and only after both runs finish.")

        # 4. Experiment ------------------------------------------------------
        print("\n[4/4] Launching the A/B experiment ...")
        experiment = client.post(
            f"{API}/api/experiments",
            json={
                "dataset_id": dataset["id"],
                "task_prompt": TASK,
                "paper_id": paper["id"],
                "skill_version_id": skill["id"],
            },
        )
        experiment.raise_for_status()
        experiment = experiment.json()
        client.post(f"{API}/api/experiments/{experiment['id']}/run").raise_for_status()

        url = f"{UI}/experiments/{experiment['id']}"
        print(f"\n  Watch it live: {url}\n")

        if not args.wait:
            return

        print("  Both arms run concurrently. Measured wall clock: 9-15 minutes.")
        started = time.time()
        deadline = started + args.timeout
        while time.time() < deadline:
            time.sleep(15)
            comparison = client.get(
                f"{API}/api/experiments/{experiment['id']}/comparison"
            ).json()
            status = comparison["experiment"]["status"]
            if status in ("completed", "failed"):
                _report(comparison, url, time.time() - started)
                return
            arms = ", ".join(f"{r['arm']}={r['status']}" for r in comparison["runs"])
            print(f"      {status} [{arms}] ... ({_mmss(time.time() - started)})")

        print("Timed out waiting; the experiment is still running. Watch it at:")
        print(f"  {url}")


def _report(comparison: dict, url: str, elapsed: float) -> None:
    quality = (comparison.get("metrics") or {}).get("quality") or {}
    system = (comparison.get("metrics") or {}).get("system") or {}

    print("\n=== RESULT ===")
    print(f"  status                        : {comparison['experiment']['status']}")
    print(f"  wall clock                    : {_mmss(elapsed)}")

    base = (quality.get("base") or {}).get("mean_dice", {}).get("value")
    skilled = (quality.get("skill") or {}).get("mean_dice", {}).get("value")
    print(f"  Base agent mean Dice          : {base}")
    print(f"  Skill-enabled agent mean Dice : {skilled}")
    if base is not None and skilled is not None:
        print(f"  Difference                    : {skilled - base:+.4f}")
    else:
        print("  (no quality metrics -- the dataset had no ground_truth file, or")
        print("   neither run produced a scorable segmentation artifact)")

    for arm in ("base", "skill"):
        stats = system.get(arm) or {}
        parts = [
            f"{key}={(stats.get(key) or {}).get('value')}"
            for key in (
                "agent_steps",
                "code_executions",
                "failed_executions",
                "runtime_seconds",
                "total_tokens",
                "cost",
            )
            if key in stats
        ]
        if parts:
            print(f"  {arm:>5} arm system metrics    : " + "  ".join(parts))

    for run in comparison.get("runs", []):
        if run.get("error"):
            print(f"  {run['arm']} arm error: {run['error']}")

    print(f"  {url}")


if __name__ == "__main__":
    main()
