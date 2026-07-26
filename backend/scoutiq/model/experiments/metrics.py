"""Per-fold and aggregate metrics for the offline harness.

All money is percent of cap. Decision-point / mid-contract segmentation, the
usable-prior persistence reference, and small-segment handling are delegated to
scoutiq.model.reporting so the harness cannot diverge from the production Model
trust contract. Arbitrary cohorts compose around persistence_reference /
build_segment with a cohort mask.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from scoutiq.model.features import TARGET, primary_position
from scoutiq.model.reporting import build_segment, persistence_reference, segment_persistence_metrics
from scoutiq.model.spec import MIN_SEGMENT_ROWS, core_model_metrics

AGE_BANDS = [(0, 23, "<=23"), (24, 26, "24-26"), (27, 29, "27-29"), (30, 32, "30-32"), (33, 200, "33+")]


def _model_metrics(y, pred, lo, hi, cap) -> dict | None:
    n = len(y)
    if n < MIN_SEGMENT_ROWS:
        return None
    m = core_model_metrics(y, pred, lo, hi)
    m["mae_usd"] = round(float(np.mean(np.abs(y - pred) * cap)))
    m["interval_80_half_width_pct"] = round(float(np.mean((hi - lo) / 2)) * 100, 2)
    return m


def _segment(ref, mask, y, pred, lo, hi, cap) -> dict:
    mm = _model_metrics(y[mask], pred[mask], lo[mask], hi[mask], cap[mask]) if mask.any() else None
    return build_segment(ref, mm)


def _age_band(age: float) -> str:
    if not np.isfinite(age):
        return "unknown"
    for lo_a, hi_a, label in AGE_BANDS:
        if lo_a <= age <= hi_a:
            return label
    return "unknown"


def evaluate_predictions(val: pd.DataFrame, pred, lo, hi, *, naive_pred, calibration, feature_cols) -> dict:
    y = val[TARGET].to_numpy(dtype=float)
    pred = np.asarray(pred, float); lo = np.asarray(lo, float); hi = np.asarray(hi, float)
    naive_pred = np.asarray(naive_pred, float)
    prior = val["prior_pct_cap"].to_numpy(dtype=float)
    decision = val["decision_point"].to_numpy(dtype=bool)
    cap = val["target_cap"].to_numpy(dtype=float)
    n = len(y)

    overall = _model_metrics(y, pred, lo, hi, cap) or {}
    decision_mae = (round(mean_absolute_error(y[decision], pred[decision]) * 100, 3)
                    if decision.sum() >= MIN_SEGMENT_ROWS else None)
    decision_mae_usd = (round(float(np.mean(np.abs(y[decision] - pred[decision]) * cap[decision])))
                        if decision.sum() >= MIN_SEGMENT_ROWS else None)
    decision_mean_prediction_mae = (round(mean_absolute_error(y[decision], naive_pred[decision]) * 100, 3)
                                    if decision.sum() >= MIN_SEGMENT_ROWS else None)

    refs = segment_persistence_metrics(y, prior, decision)
    segments = {
        "decision_point": _segment(refs["decision_point"], decision, y, pred, lo, hi, cap),
        "mid_contract": _segment(refs["mid_contract"], ~decision, y, pred, lo, hi, cap),
    }

    all_mask = np.ones(n, dtype=bool)
    persistence_all = persistence_reference(y, prior, all_mask)
    mean_pred_mae = round(mean_absolute_error(y, naive_pred) * 100, 3) if n else None

    cohorts = {"age_band": {}, "position": {}, "contract_type": {
        "status": "insufficient_evidence",
        "reason": "no trustworthy contract-type labels yet (blocked on #109)",
    }}
    bands = np.array([_age_band(a) for a in val["age"].to_numpy(dtype=float)])
    for band in sorted(set(bands)):
        m = bands == band
        cohorts["age_band"][band] = _segment(persistence_reference(y, prior, m), m, y, pred, lo, hi, cap)
    if "position" in val.columns:
        positions = val["position"].map(primary_position).fillna("unknown").to_numpy()
    else:
        positions = np.array(["unknown"] * n)
    for pos in sorted(set(positions)):
        m = positions == pos
        cohorts["position"][pos] = _segment(persistence_reference(y, prior, m), m, y, pred, lo, hi, cap)

    miss = {c: round(float(val[c].isna().mean()), 3) for c in feature_cols if c in val.columns}

    return {
        "n": n,
        "n_with_prior": persistence_all["n_with_prior"],
        "mae_pct_of_cap": overall.get("mae_pct_of_cap"),
        "mae_usd": overall.get("mae_usd"),
        "r2": overall.get("r2"),
        "decision_mae_pct_of_cap": decision_mae,
        "decision_mae_usd": decision_mae_usd,
        "decision_mean_prediction_mae_pct": decision_mean_prediction_mae,
        "segments": segments,
        "calibration": calibration,
        "references": {
            "mean_prediction_mae_pct": mean_pred_mae,
            "prior_pay_persistence": persistence_all,
        },
        "missingness": {"max_feature_nan_frac": (max(miss.values()) if miss else 0.0), "by_feature": miss},
        "cohorts": cohorts,
    }
