"""Shared valuation model + evaluation specification.

Single source of truth for the v1 model hyperparameters, conformal interval
settings, segment thresholds, the reserved final-holdout seasons, and the
conformal-calibration primitives — so the production trainer
(scoutiq.model.train) and the offline experiment harness
(scoutiq.model.experiments) cannot drift apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import StratifiedKFold

from scoutiq.model.features import FEATURE_COLS, TARGET

SEED = 42
PRIMARY_ALPHA = 0.20                       # -> 80% prediction interval
CAL_LEVELS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
HGB_PARAMS = dict(max_iter=500, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0)
MIN_SEGMENT_ROWS = 5                        # below this, model-quality metrics are insufficient
MIN_R2_ROWS = 30                            # below this, R^2 is too unstable to report
FINAL_HOLDOUT_SEASONS = ["2024-25", "2025-26"]  # reserved final-evaluation targets; never a tuning set


def conformal_q(resid: np.ndarray, level: float) -> float:
    """Split-conformal quantile of |residual| for a target coverage `level`."""
    n = len(resid)
    k = min(np.ceil((n + 1) * level) / n, 1.0)
    return float(np.quantile(resid, k, method="higher"))


def decision_oof_cqr_scores(
    train: pd.DataFrame, hgb_params: dict, *,
    feature_cols=FEATURE_COLS, seed: int = SEED, n_splits: int = 5,
) -> np.ndarray:
    """Cross-fitted CQR nonconformity scores for contract-start (decision-point)
    rows. Each score comes from quantile models that did not train on that row,
    stratified so all contract starts contribute. Returns an empty array if the
    fold has no held-out decision points."""
    decision = train["decision_point"].to_numpy(dtype=bool)
    scores: list[np.ndarray] = []
    folds = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for fit_idx, held_idx in folds.split(train, decision):
        held_decision_idx = held_idx[decision[held_idx]]
        if not len(held_decision_idx):
            continue
        cols = list(feature_cols)
        Xfit = train.iloc[fit_idx][cols]
        yfit = train.iloc[fit_idx][TARGET].to_numpy()
        Xheld = train.iloc[held_decision_idx][cols]
        yheld = train.iloc[held_decision_idx][TARGET].to_numpy()
        lo_model = HistGradientBoostingRegressor(loss="quantile", quantile=PRIMARY_ALPHA / 2, **hgb_params).fit(Xfit, yfit)
        hi_model = HistGradientBoostingRegressor(loss="quantile", quantile=1 - PRIMARY_ALPHA / 2, **hgb_params).fit(Xfit, yfit)
        scores.append(np.maximum(lo_model.predict(Xheld) - yheld, yheld - hi_model.predict(Xheld)))
    return np.concatenate(scores) if scores else np.array([])


def core_model_metrics(y_true, pred, lo, hi) -> dict:
    """Shared segment model-quality metrics (mae % of cap, R^2, 80% coverage) used
    by both the production trainer and the offline harness. The caller ensures the
    group is large enough to score (>= MIN_SEGMENT_ROWS)."""
    n = len(y_true)
    return {
        "mae_pct_of_cap": round(mean_absolute_error(y_true, pred) * 100, 3),
        "r2": round(r2_score(y_true, pred), 3) if n >= MIN_R2_ROWS else None,
        "interval_80_coverage": round(float(np.mean((y_true >= lo) & (y_true <= hi))), 3),
    }
