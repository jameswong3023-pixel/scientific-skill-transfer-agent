"""Synthetic brain-like MRI phantom with known ground truth.

The *generator* is committed rather than the volumes it produces, so the demo
runs with no network access and the repository stays free of large binaries
(`.gitignore` excludes `*.nii.gz` for exactly that reason). Generation is
deterministic for a given seed, so every reviewer gets a byte-identical phantom:

    python scripts/make_phantom.py --out fixtures/phantom

The phantom is deliberately hard in the way the target technique is designed
for: a smooth multiplicative bias field plus Rician-like noise makes tissue
intensity distributions overlap globally, so a single intensity threshold
cannot separate them, while a bias-corrected, neighbourhood-regularised
clustering method can. That is what makes the A/B result meaningful rather than
a coin flip.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

# 0 background, 1 CSF, 2 grey matter, 3 white matter.
# The grey/white gap is deliberately modest (~0.20 on a 0-1 scale), which is
# what a real T1-weighted acquisition looks like. With the original 0.55/0.85
# gap the tissues stayed separable by a single global threshold even under a
# strong bias field, and the experiment had nothing to measure.
TISSUE_INTENSITY = {0: 0.02, 1: 0.28, 2: 0.55, 3: 0.75}
LABEL_NAMES = {0: "background", 1: "csf", 2: "grey_matter", 3: "white_matter"}

# 2 mm isotropic, so per-tissue volumes are a real calculation and not a voxel count.
VOXEL_MM = 2.0


def _ellipsoid(
    shape: tuple[int, int, int],
    centre: tuple[float, float, float],
    radii: tuple[float, float, float],
) -> np.ndarray:
    grids = np.ogrid[tuple(slice(0, s) for s in shape)]
    total = np.zeros(shape, dtype=np.float64)
    for g, c, r in zip(grids, centre, radii, strict=True):
        total = total + ((g - c) / r) ** 2
    return total <= 1.0


def _smooth(volume: np.ndarray, sigma: float) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    return gaussian_filter(volume, sigma=sigma)


def _bias_field(
    shape: tuple[int, int, int],
    brain: np.ndarray,
    strength: float,
    seed: int,
) -> np.ndarray:
    """A smooth multiplicative RF inhomogeneity field.

    Implemented as a low-order polynomial dominated by a diagonal ramp, rather
    than heavily smoothed white noise. Smoothed noise was the first approach and
    it did not work: with sigma = size/5 the field is effectively constant over
    the small, central white-matter core, so white and grey matter were
    multiplied by almost the same factor and one global intensity threshold
    still separated them perfectly. That would have made the A/B comparison
    meaningless, because the naive method a base agent reaches for would already
    have been optimal.

    Three properties fix it, and all three matter:

    1. The field is *low order* across the whole volume, which is also the
       standard model for real RF inhomogeneity: tissue on one side of the head
       is systematically brighter than the same tissue on the other side.
    2. It is normalised over the **brain mask**, not the whole cube, so the
       extremes of the field land on tissue instead of on empty background.
    3. Its coefficients come from a resolution-independent RandomState, so the
       same field shape is produced at every ``size``. Drawing them from the
       main generator made the field depend on how many noise samples had
       already been consumed, i.e. on the volume size, which made the phantom's
       difficulty vary unpredictably with resolution.
    """
    lin = [np.linspace(-1.0, 1.0, s) for s in shape]
    x, y, z = np.meshgrid(*lin, indexing="ij")

    jitter = np.random.RandomState(seed + 1000).uniform(-0.12, 0.12, 6)
    field = (
        (0.62 + jitter[0]) * x
        + (0.45 + jitter[1]) * y
        + (0.38 + jitter[2]) * z
        + (0.25 + jitter[3]) * x * y
        + (0.18 + jitter[4]) * y * z
        + (0.30 + jitter[5]) * (x**2 + y**2 + z**2 - 1.0)
    )

    inside = field[brain]
    lo, hi = float(inside.min()), float(inside.max())
    field = 2.0 * (field - lo) / (hi - lo + 1e-9) - 1.0

    # Outside the brain the polynomial keeps growing; clip so the field cannot
    # drive the multiplicative bias to zero or negative in the background.
    field = np.clip(field, -1.4, 1.4)
    return 1.0 + strength * field


def build_phantom(
    size: int = 64,
    noise: float = 0.03,
    bias_strength: float = 0.35,
    seed: int = 7,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(observed_t1, labels, bias_field)`` for a cubic phantom."""
    rng = np.random.RandomState(seed)
    shape = (size, size, size)
    c = size / 2.0

    labels = np.zeros(shape, dtype=np.uint8)

    # Nested structures: CSF shell, grey matter cortex, white matter core.
    labels[_ellipsoid(shape, (c, c, c), (size * 0.42, size * 0.36, size * 0.40))] = 1
    labels[_ellipsoid(shape, (c, c, c), (size * 0.37, size * 0.31, size * 0.35))] = 2
    labels[_ellipsoid(shape, (c, c, c), (size * 0.26, size * 0.21, size * 0.24))] = 3

    # Ventricle-like CSF pockets inside the white matter make the problem less
    # trivially concentric.
    for offset in (-0.09, 0.09):
        labels[
            _ellipsoid(
                shape,
                (c, c + offset * size, c),
                (size * 0.10, size * 0.045, size * 0.07),
            )
        ] = 1

    clean = np.zeros(shape, dtype=np.float64)
    for label, intensity in TISSUE_INTENSITY.items():
        clean[labels == label] = intensity

    # Slight within-tissue variation: real tissue is not perfectly uniform.
    clean = clean + _smooth(rng.normal(0, 0.02, shape), sigma=2.0) * (labels > 0)

    # Smooth multiplicative bias field, the phenomenon the technique corrects.
    if bias_strength > 0:
        bias = _bias_field(shape, labels > 0, bias_strength, seed)
    else:
        bias = np.ones(shape, dtype=np.float64)

    observed = clean * bias

    # Rician-like noise: magnitude of a complex signal with Gaussian noise.
    if noise > 0:
        real = observed + rng.normal(0, noise, shape)
        imag = rng.normal(0, noise, shape)
        observed = np.sqrt(real**2 + imag**2)

    return observed.astype(np.float32), labels, bias.astype(np.float32)


def save_phantom(out_dir: Path, **kwargs) -> dict[str, Path]:
    """Write the phantom to ``out_dir`` and return the paths written.

    ``t1.nii.gz`` and ``ground_truth.nii.gz`` are the exact filenames
    ``scripts/seed_demo.py`` uploads with roles ``input`` and ``ground_truth``.
    """
    import nibabel as nib

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t1, labels, bias = build_phantom(**kwargs)

    affine = np.diag([VOXEL_MM, VOXEL_MM, VOXEL_MM, 1.0])

    paths = {
        "t1": out_dir / "t1.nii.gz",
        "ground_truth": out_dir / "ground_truth.nii.gz",
        "bias": out_dir / "true_bias_field.nii.gz",
    }
    nib.save(nib.Nifti1Image(t1, affine), str(paths["t1"]))
    nib.save(nib.Nifti1Image(labels, affine), str(paths["ground_truth"]))
    nib.save(nib.Nifti1Image(bias, affine), str(paths["bias"]))

    voxel_volume = VOXEL_MM**3
    summary = {
        LABEL_NAMES[label]: float((labels == label).sum()) * voxel_volume
        for label in sorted(TISSUE_INTENSITY)
    }
    paths["volumes"] = out_dir / "true_volumes.json"
    paths["volumes"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic MRI phantom")
    parser.add_argument("--out", default="fixtures/phantom", type=Path)
    parser.add_argument("--size", default=64, type=int)
    parser.add_argument("--noise", default=0.03, type=float)
    parser.add_argument("--bias", default=0.35, type=float, dest="bias_strength")
    args = parser.parse_args()

    paths = save_phantom(
        args.out, size=args.size, noise=args.noise, bias_strength=args.bias_strength
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
