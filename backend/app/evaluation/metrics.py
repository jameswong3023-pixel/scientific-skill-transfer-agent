"""Deterministic segmentation metrics.

Scoring is pure computation — never an LLM judgement — because the whole point
of the experiment is an objective answer to "did the skill help?".

The subtle part is label matching. Neither agent is told our label numbering, so
a perfect segmentation that calls grey matter "2" instead of "1" must not score
zero. Hungarian assignment on the overlap matrix finds the best permutation
before any per-class metric is computed.
"""

from __future__ import annotations

import numpy as np

SHAPE_MISMATCH = "shape_mismatch"


def _as_bool(x: np.ndarray) -> np.ndarray:
    return np.asarray(x).astype(bool)


def dice(a: np.ndarray, b: np.ndarray) -> float:
    a, b = _as_bool(a), _as_bool(b)
    total = a.sum() + b.sum()
    if total == 0:
        return 1.0  # both empty: trivially identical
    return float(2.0 * np.logical_and(a, b).sum() / total)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = _as_bool(a), _as_bool(b)
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(a, b).sum() / union)


def precision_recall(pred: np.ndarray, truth: np.ndarray) -> tuple[float, float]:
    pred, truth = _as_bool(pred), _as_bool(truth)
    tp = float(np.logical_and(pred, truth).sum())
    fp = float(np.logical_and(pred, ~truth).sum())
    fn = float(np.logical_and(~pred, truth).sum())
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if tp == 0 and fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return float(precision), float(recall)


def match_labels(
    pred: np.ndarray, truth: np.ndarray, ignore_label: int | None = 0
) -> dict[int, int]:
    """Best predicted-label -> truth-label assignment by overlap.

    DEVIATION FROM PLAN: `ignore_label` is pinned to itself and excluded from
    the assignment. The plan matched every label including background, which let
    an all-background prediction be "rescued" by relabelling its background as a
    foreground class — `np.zeros(4)` against `[0, 1, 1, 2]` scored 0.33 instead
    of 0.0 (the plan's own
    `test_all_background_prediction_scores_zero_not_crash` caught it). Background
    is the one label whose meaning both sides do agree on, so permuting it is
    never a legitimate relabelling.
    """
    from scipy.optimize import linear_sum_assignment

    pred_labels = [int(x) for x in np.unique(pred)]
    truth_labels = [int(x) for x in np.unique(truth)]

    mapping: dict[int, int] = {}
    if ignore_label is not None:
        if ignore_label in pred_labels:
            pred_labels.remove(ignore_label)
            mapping[int(ignore_label)] = int(ignore_label)
        if ignore_label in truth_labels:
            truth_labels.remove(ignore_label)

    if not pred_labels or not truth_labels:
        return mapping

    overlap = np.zeros((len(pred_labels), len(truth_labels)), dtype=np.int64)
    for i, pl in enumerate(pred_labels):
        pred_mask = pred == pl
        for j, tl in enumerate(truth_labels):
            overlap[i, j] = int(np.logical_and(pred_mask, truth == tl).sum())

    rows, cols = linear_sum_assignment(-overlap)  # maximise overlap
    mapping.update({pred_labels[r]: truth_labels[c] for r, c in zip(rows, cols)})
    return mapping


def remap(pred: np.ndarray, mapping: dict[int, int]) -> np.ndarray:
    out = np.zeros_like(pred)
    for src, dst in mapping.items():
        out[pred == src] = dst
    return out


def volume_error(
    pred: np.ndarray, truth: np.ndarray, label: int, spacing: tuple[float, ...] | None = None
) -> dict[str, float]:
    voxel_volume = float(np.prod(spacing)) if spacing else 1.0
    pred_volume = float((pred == label).sum()) * voxel_volume
    true_volume = float((truth == label).sum()) * voxel_volume
    abs_error = abs(pred_volume - true_volume)
    pct = (
        (abs_error / true_volume * 100.0)
        if true_volume > 0
        else (0.0 if pred_volume == 0 else 100.0)
    )
    return {
        "pred_volume": pred_volume,
        "true_volume": true_volume,
        "abs_error": abs_error,
        "pct_error": pct,
    }


def evaluate_segmentation(
    pred: np.ndarray,
    truth: np.ndarray,
    spacing: tuple[float, ...] | None = None,
    ignore_label: int = 0,
) -> dict:
    pred = np.asarray(pred)
    truth = np.asarray(truth)

    if pred.shape != truth.shape:
        return {
            "error": SHAPE_MISMATCH,
            "detail": f"prediction {pred.shape} vs ground truth {truth.shape}",
            "mean_dice": 0.0,
            "per_class": {},
            "label_mapping": {},
        }

    pred = np.nan_to_num(pred, nan=0).astype(np.int64)
    truth = np.nan_to_num(truth, nan=0).astype(np.int64)

    mapping = match_labels(pred, truth, ignore_label=ignore_label)
    aligned = remap(pred, mapping) if mapping else pred

    per_class: dict[str, dict] = {}
    dices: list[float] = []
    for label in (int(x) for x in np.unique(truth)):
        if label == ignore_label:
            continue
        p_mask = aligned == label
        t_mask = truth == label
        precision, recall = precision_recall(p_mask, t_mask)
        d = dice(p_mask, t_mask)
        dices.append(d)
        per_class[str(label)] = {
            "dice": d,
            "iou": iou(p_mask, t_mask),
            "precision": precision,
            "recall": recall,
            **volume_error(aligned, truth, label, spacing),
        }

    return {
        "error": None,
        "mean_dice": float(np.mean(dices)) if dices else 0.0,
        "mean_iou": (
            float(np.mean([c["iou"] for c in per_class.values()])) if per_class else 0.0
        ),
        "per_class": per_class,
        "label_mapping": {str(k): int(v) for k, v in mapping.items()},
        "n_classes_truth": int(len(per_class)),
        "n_classes_pred": int(len(np.unique(pred))),
    }
