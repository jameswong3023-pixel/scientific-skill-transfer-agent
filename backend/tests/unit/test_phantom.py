import sys
from pathlib import Path

import numpy as np
import pytest

# scripts/ is repository tooling, not part of the shipped backend image, so the
# module is not importable when this suite is run inside the api container.
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if not (SCRIPTS / "make_phantom.py").exists():  # pragma: no cover - container path
    pytest.skip("scripts/ is not present (running inside the app image)", allow_module_level=True)

sys.path.insert(0, str(SCRIPTS))

from make_phantom import build_phantom  # noqa: E402


def test_shapes_agree():
    t1, labels, bias = build_phantom(size=32)
    assert t1.shape == labels.shape == bias.shape == (32, 32, 32)


def test_four_tissue_classes_present():
    _, labels, _ = build_phantom(size=48)
    assert set(np.unique(labels)) == {0, 1, 2, 3}


def test_background_dominates_the_corners():
    _, labels, _ = build_phantom(size=32)
    assert labels[0, 0, 0] == 0
    assert labels[-1, -1, -1] == 0


def test_bias_field_is_smooth_and_multiplicative():
    _, _, bias = build_phantom(size=32, bias_strength=0.4)
    assert bias.min() > 0, "a multiplicative field must stay positive"
    assert bias.max() / bias.min() > 1.3, "field must actually vary or the task is trivial"
    # Smoothness: neighbouring voxels differ far less than the global range.
    gradient = np.abs(np.diff(bias, axis=0)).max()
    assert gradient < (bias.max() - bias.min()) * 0.2


def test_generation_is_deterministic():
    a, la, _ = build_phantom(size=32, seed=7)
    b, lb, _ = build_phantom(size=32, seed=7)
    assert np.array_equal(la, lb)
    assert np.allclose(a, b)


def test_tissue_intensities_are_ordered_before_bias():
    t1, labels, bias = build_phantom(size=48, noise=0.0, bias_strength=0.0)
    means = [t1[labels == c].mean() for c in (1, 2, 3)]
    assert means[0] < means[1] < means[2], "CSF < grey < white"


def test_bias_field_makes_global_thresholding_insufficient():
    # If a single global threshold could separate the tissues, the experiment
    # would not distinguish a bias-corrected method from a naive one.
    t1, labels, _ = build_phantom(size=48, noise=0.03, bias_strength=0.45)
    wm = t1[labels == 3]
    gm = t1[labels == 2]
    assert np.percentile(wm, 5) < np.percentile(gm, 95), "distributions must overlap"


def test_noise_is_applied():
    clean, labels, _ = build_phantom(size=32, noise=0.0, bias_strength=0.0)
    noisy, _, _ = build_phantom(size=32, noise=0.08, bias_strength=0.0)
    assert noisy[labels == 3].std() > clean[labels == 3].std()


def test_csf_is_not_a_single_concentric_shell():
    """Without the ventricle pockets the phantom is perfectly concentric, and a
    radial rule would solve it without ever looking at an intensity."""
    from scipy import ndimage

    _, labels, _ = build_phantom(size=64)
    _, components = ndimage.label(labels == 1)
    assert components >= 3, (
        f"expected the outer CSF shell plus two ventricle pockets, got {components}"
    )


def test_bias_field_shape_does_not_depend_on_resolution():
    """The field's coefficients must come from a resolution-independent draw.
    Taking them from the main generator made them depend on how many noise
    samples the volume size had already consumed, so the phantom's difficulty
    silently changed with --size."""
    _, _, small = build_phantom(size=32)
    _, _, large = build_phantom(size=64)
    assert abs(float(small.min()) - float(large.min())) < 0.02
    assert abs(float(small.max()) - float(large.max())) < 0.02


def test_bias_correction_measurably_improves_naive_clustering():
    """The premise of the whole experiment: a bias-aware method must beat a
    bias-blind one on this data. If it does not, the A/B comparison measures
    nothing and the phantom is the wrong benchmark."""
    from app.evaluation.metrics import evaluate_segmentation

    t1, labels, bias = build_phantom(size=48, noise=0.03, bias_strength=0.35)

    # Both arms get the same crude intensity-threshold brain mask -- the
    # preprocessing step the sample paper actually describes. Using the true
    # labels as a mask would leak ground truth into the "naive" baseline.
    mask = t1 > np.percentile(t1, 60)

    naive = _cluster_within(t1, mask)
    corrected = _cluster_within(t1 / bias, mask)

    naive_dice = evaluate_segmentation(naive, labels)["mean_dice"]
    corrected_dice = evaluate_segmentation(corrected, labels)["mean_dice"]

    assert corrected_dice > naive_dice + 0.05, (
        f"bias correction gained only {corrected_dice - naive_dice:.3f} "
        f"({naive_dice:.3f} -> {corrected_dice:.3f}); the phantom is too easy"
    )


def _cluster_within(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Three-class 1-D k-means inside ``mask``; everything else is background."""
    out = np.zeros(image.shape, dtype=np.int64)
    out[mask] = _kmeans_1d(image[mask].ravel(), k=3) + 1
    return out


def _kmeans_1d(values: np.ndarray, k: int, iterations: int = 60) -> np.ndarray:
    """Minimal 1-D k-means, deterministic via quantile initialisation.

    Stands in for the obvious thing a bias-blind agent does: cluster intensities
    globally, with no spatial or inhomogeneity term.
    """
    centres = np.percentile(values, np.linspace(5, 95, k)).astype(float)
    assignment = np.zeros(values.shape, dtype=np.int64)
    for _ in range(iterations):
        assignment = np.argmin(np.abs(values[:, None] - centres[None, :]), axis=1)
        moved = 0.0
        for c in range(k):
            member = values[assignment == c]
            if member.size:
                moved = max(moved, abs(float(member.mean()) - centres[c]))
                centres[c] = member.mean()
        if moved < 1e-7:
            break
    # Order clusters by intensity so the darkest cluster comes first.
    return np.argsort(np.argsort(centres))[assignment]


def test_saved_volumes_round_trip_with_matching_geometry(tmp_path):
    """seed_demo uploads exactly these two filenames; the evaluator compares the
    prediction against ground_truth voxel-for-voxel, so geometry must agree."""
    import nibabel as nib

    from make_phantom import save_phantom

    paths = save_phantom(tmp_path, size=32)
    t1 = nib.load(str(paths["t1"]))
    gt = nib.load(str(paths["ground_truth"]))

    assert paths["t1"].name == "t1.nii.gz"
    assert paths["ground_truth"].name == "ground_truth.nii.gz"
    assert t1.shape == gt.shape == (32, 32, 32)
    assert np.allclose(t1.affine, gt.affine)
    assert set(np.unique(np.asarray(gt.dataobj).astype(int))) == {0, 1, 2, 3}
