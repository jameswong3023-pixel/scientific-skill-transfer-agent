import numpy as np
import pytest

from app.evaluation.metrics import (
    dice,
    evaluate_segmentation,
    iou,
    match_labels,
    precision_recall,
    remap,
    volume_error,
)


def test_dice_of_identical_masks_is_one():
    a = np.array([[1, 1], [0, 0]], dtype=bool)
    assert dice(a, a) == pytest.approx(1.0)


def test_dice_of_disjoint_masks_is_zero():
    a = np.array([[1, 0], [0, 0]], dtype=bool)
    b = np.array([[0, 1], [0, 0]], dtype=bool)
    assert dice(a, b) == pytest.approx(0.0)


def test_dice_half_overlap():
    a = np.array([1, 1, 1, 1], dtype=bool)
    b = np.array([1, 1, 0, 0], dtype=bool)
    assert dice(a, b) == pytest.approx(2 * 2 / (4 + 2))


def test_two_empty_masks_are_perfectly_equal():
    empty = np.zeros(4, dtype=bool)
    assert dice(empty, empty) == pytest.approx(1.0)
    assert iou(empty, empty) == pytest.approx(1.0)


def test_iou_matches_hand_calculation():
    a = np.array([1, 1, 0, 0], dtype=bool)
    b = np.array([1, 0, 1, 0], dtype=bool)
    assert iou(a, b) == pytest.approx(1 / 3)


def test_precision_and_recall():
    pred = np.array([1, 1, 1, 0], dtype=bool)
    truth = np.array([1, 1, 0, 0], dtype=bool)
    p, r = precision_recall(pred, truth)
    assert p == pytest.approx(2 / 3)
    assert r == pytest.approx(1.0)


def test_label_matching_handles_permuted_class_numbering():
    # The agent has no way to know our label convention; a perfect segmentation
    # with swapped numbers must score 1.0, not 0.0.
    truth = np.array([0, 0, 1, 1, 2, 2])
    pred = np.array([0, 0, 2, 2, 1, 1])
    mapping = match_labels(pred, truth)
    assert mapping[2] == 1
    assert mapping[1] == 2
    assert np.array_equal(remap(pred, mapping), truth)


def test_identity_mapping_when_labels_already_agree():
    truth = np.array([0, 1, 1, 2])
    assert match_labels(truth, truth)[1] == 1


def test_volume_error_uses_voxel_spacing():
    pred = np.array([[1, 1], [0, 0]])
    truth = np.array([[1, 0], [0, 0]])
    result = volume_error(pred, truth, label=1, spacing=(2.0, 2.0))
    assert result["pred_volume"] == pytest.approx(2 * 4.0)
    assert result["true_volume"] == pytest.approx(1 * 4.0)
    assert result["pct_error"] == pytest.approx(100.0)


def test_evaluate_segmentation_reports_per_class_and_mean():
    truth = np.array([0, 0, 1, 1, 2, 2])
    pred = np.array([0, 0, 1, 1, 2, 2])
    out = evaluate_segmentation(pred, truth)
    assert out["mean_dice"] == pytest.approx(1.0)
    assert out["per_class"]["1"]["dice"] == pytest.approx(1.0)
    assert "2" in out["per_class"]


def test_evaluate_scores_a_permuted_segmentation_correctly():
    truth = np.array([0, 0, 1, 1, 2, 2])
    pred = np.array([0, 0, 2, 2, 1, 1])
    out = evaluate_segmentation(pred, truth)
    assert out["mean_dice"] == pytest.approx(1.0)
    assert out["label_mapping"]


def test_shape_mismatch_is_reported_not_raised():
    out = evaluate_segmentation(np.zeros((4, 4)), np.zeros((5, 5)))
    assert out["error"] == "shape_mismatch"
    assert out["mean_dice"] == 0.0


def test_background_is_excluded_from_the_mean():
    truth = np.array([0, 0, 0, 1])
    pred = np.array([0, 0, 0, 1])
    out = evaluate_segmentation(pred, truth, ignore_label=0)
    assert "0" not in out["per_class"]


def test_all_background_prediction_scores_zero_not_crash():
    truth = np.array([0, 1, 1, 2])
    pred = np.zeros(4, dtype=int)
    out = evaluate_segmentation(pred, truth)
    assert out["mean_dice"] == pytest.approx(0.0)


def test_float_masks_are_accepted():
    a = np.array([1.0, 1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0, 0.0])
    assert 0.0 < dice(a.astype(bool), b.astype(bool)) < 1.0
