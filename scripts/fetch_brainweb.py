"""Fetch a small BrainWeb simulated brain MRI sample.

BrainWeb (McGill BIC) serves volumes through a CGI form as raw byte data.
This script requests a T1 volume plus the discrete tissue phantom that serves
as ground truth, and converts both to NIfTI.

The data is NOT redistributed in this repository. If the fetch fails -- the site
is down, the network blocks it, or the form changes -- use the committed
synthetic phantom instead:

    python scripts/make_phantom.py --out fixtures/phantom

The decoding and request-building logic is unit tested; the download itself is
not, because a test that depends on a third-party CGI endpoint is a flaky test.
The offline path is the one the demo relies on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

BRAINWEB_URL = "https://brainweb.bic.mni.mcgill.ca/cgi/brainweb1"
DEFAULT_SHAPE = (181, 217, 181)  # 1mm isotropic ICBM space

# BrainWeb's discrete phantom labels, collapsed to the four classes we score.
# Everything the evaluator does not model becomes background: the Hungarian
# label matcher in app/evaluation/metrics.py assigns predicted classes to truth
# classes, so leaving skull or fat in the truth volume would invent classes that
# no agent could reasonably be asked to produce.
PHANTOM_LABEL_MAP = {
    0: 0,  # background
    1: 1,  # CSF
    2: 2,  # grey matter
    3: 3,  # white matter
    4: 0,  # fat
    5: 0,  # muscle/skin
    6: 0,  # skin
    7: 0,  # skull
    8: 0,  # glial matter -> background for our 4-class task
    9: 0,  # connective
    10: 0,  # dura / other
}


def rawb_to_array(data: bytes, shape: tuple[int, int, int] = DEFAULT_SHAPE) -> np.ndarray:
    expected = shape[0] * shape[1] * shape[2]
    if len(data) != expected:
        raise ValueError(
            f"unexpected payload size: got {len(data)} bytes, expected {expected} "
            f"for shape {shape}"
        )
    # BrainWeb writes z-fastest; reshape then transpose into (x, y, z).
    return np.frombuffer(data, dtype=np.uint8).reshape(shape[::-1]).transpose(2, 1, 0)


def collapse_labels(phantom: np.ndarray) -> np.ndarray:
    """Map BrainWeb's 11 tissue classes onto our four, without mutating input."""
    mapped = np.zeros(phantom.shape, dtype=np.uint8)
    for source, target in PHANTOM_LABEL_MAP.items():
        if target:
            mapped[phantom == source] = target
    return mapped


def build_request(modality: str, noise: int, rf: int) -> dict[str, str]:
    if modality == "phantom":
        return {
            "do_download_alias": "phantom_1.0mm_normal_crisp",
            "format_value": "raw_byte",
            "zip_value": "none",
            "download_for_real": "[Start download!]",
        }
    return {
        "do_download_alias": f"{modality}+ICBM+normal+1mm+pn{noise}+rf{rf}",
        "format_value": "raw_byte",
        "zip_value": "none",
        "noise_value": str(noise),
        "rf_value": str(rf),
        "download_for_real": "[Start download!]",
    }


def _download(body: dict[str, str], timeout: float = 300.0) -> bytes:
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post(BRAINWEB_URL, data=body)
        response.raise_for_status()
        return response.content


def fetch(out_dir: Path, noise: int = 3, rf: int = 20) -> dict[str, Path]:
    import nibabel as nib

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    affine = np.diag([1.0, 1.0, 1.0, 1.0])
    written: dict[str, Path] = {}

    print(f"Requesting T1 (pn{noise}, rf{rf}) ...")
    t1 = rawb_to_array(_download(build_request("t1", noise, rf)))
    t1_path = out_dir / "t1.nii.gz"
    nib.save(nib.Nifti1Image(t1.astype(np.float32), affine), str(t1_path))
    written["t1"] = t1_path

    print("Requesting discrete tissue phantom (ground truth) ...")
    phantom = rawb_to_array(_download(build_request("phantom", 0, 0)))
    gt_path = out_dir / "ground_truth.nii.gz"
    nib.save(nib.Nifti1Image(collapse_labels(phantom), affine), str(gt_path))
    written["ground_truth"] = gt_path

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch BrainWeb sample volumes")
    parser.add_argument("--out", default="data/brainweb", type=Path)
    parser.add_argument("--noise", default=3, type=int, help="percent noise, e.g. 3")
    parser.add_argument("--rf", default=20, type=int, help="intensity non-uniformity, e.g. 20")
    args = parser.parse_args()

    try:
        for name, path in fetch(args.out, args.noise, args.rf).items():
            print(f"{name}: {path}")
    except Exception as exc:
        print(f"\nBrainWeb fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "\nFall back to the committed synthetic phantom:\n"
            "  python scripts/make_phantom.py --out fixtures/phantom",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
