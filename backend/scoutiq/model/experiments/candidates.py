"""Model candidates for the offline harness.

A candidate is the v1 fitting pipeline (HistGradientBoosting point model + CQR
adaptive intervals) restricted to a feature set. Fitting and conformal
calibration for a fold use only that fold's training rows. Interval calibration
mirrors production v1 — decision-point cross-fitted conformal scores when the
fold has enough contract starts — with a train-only split-conformal fallback and
the method recorded so coverage is never mislabeled. Never loads/writes model.joblib.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split

from scoutiq.model.features import FEATURE_COLS, LAG_FEATURES, TARGET
from scoutiq.model.spec import (
    CAL_LEVELS, HGB_PARAMS, PRIMARY_ALPHA, SEED, conformal_q, decision_oof_cqr_scores,
)

# Enough contract starts to cross-fit decision-point calibration (>= n_splits per class).
MIN_DECISION_FOR_OOF = 10


def train_calibration_split(train: pd.DataFrame, seed: int = SEED, test_size: float = 0.25):
    """Split the training index into (proper_train_idx, calibration_idx). Both are
    drawn only from ``train`` rows, so calibration never uses future data."""
    idx = np.asarray(train.index)
    return train_test_split(idx, test_size=test_size, random_state=seed)


@dataclass(frozen=True)
class Candidate:
    name: str
    feature_cols: tuple[str, ...]

    def fit_predict(self, train: pd.DataFrame, val: pd.DataFrame, *, seed: int = SEED,
                    alpha: float = PRIMARY_ALPHA) -> dict:
        cols = list(self.feature_cols)
        params = dict(HGB_PARAMS, random_state=seed)
        pt_idx, cal_idx = train_calibration_split(train, seed)
        Xpt, ypt = train.loc[pt_idx, cols], train.loc[pt_idx, TARGET].to_numpy()
        Xcal, ycal = train.loc[cal_idx, cols], train.loc[cal_idx, TARGET].to_numpy()

        point = HistGradientBoostingRegressor(**params).fit(Xpt, ypt)
        lo_m = HistGradientBoostingRegressor(loss="quantile", quantile=alpha / 2, **params).fit(Xpt, ypt)
        hi_m = HistGradientBoostingRegressor(loss="quantile", quantile=1 - alpha / 2, **params).fit(Xpt, ypt)

        # Interval calibration: decision-point cross-fitted conformal when the fold has enough
        # contract starts (production v1's method), else train-only split-conformal.
        n_decision = int(train["decision_point"].to_numpy(dtype=bool).sum())
        scores = np.array([])
        calibration_method = "global_split_conformal"
        if n_decision >= MIN_DECISION_FOR_OOF:
            scores = decision_oof_cqr_scores(train, params, feature_cols=cols, seed=seed)
            if len(scores):
                calibration_method = "decision_point_oof"
        if len(scores) == 0:
            scores = np.maximum(lo_m.predict(Xcal) - ycal, ycal - hi_m.predict(Xcal))
            calibration_method = "global_split_conformal"

        Xval = val[cols]
        pred = point.predict(Xval)
        qlo, qhi = lo_m.predict(Xval), hi_m.predict(Xval)
        yval = val[TARGET].to_numpy()

        q80 = conformal_q(scores, 1 - alpha)
        lo = np.minimum(qlo - q80, pred)
        hi = np.maximum(qhi + q80, pred)

        dmask = val["decision_point"].to_numpy(dtype=bool)
        yv_d, qlo_d, qhi_d, pred_d = yval[dmask], qlo[dmask], qhi[dmask], pred[dmask]

        calibration = []
        for lvl in CAL_LEVELS:
            q = conformal_q(scores, lvl)
            lo_l = np.minimum(qlo_d - q, pred_d)
            hi_l = np.maximum(qhi_d + q, pred_d)
            covered = (yv_d >= lo_l) & (yv_d <= hi_l)
            calibration.append({
                "nominal": lvl,
                "empirical": round(float(np.mean(covered)), 3) if len(yv_d) else None,
                "half_width_pct": round(float(np.mean((hi_l - lo_l) / 2)) * 100, 2) if len(yv_d) else None,
            })

        return {"pred": pred, "lo": lo, "hi": hi, "calibration": calibration,
                "calibration_method": calibration_method,
                "train_mean_pct_cap": float(np.mean(train[TARGET].to_numpy()))}


def v1_candidate() -> Candidate:
    return Candidate("v1", tuple(FEATURE_COLS))


def current_season_candidate() -> Candidate:
    """Ablation baseline: v1 pipeline without the multi-season lag block."""
    lag = set(LAG_FEATURES)
    return Candidate("current_season", tuple(c for c in FEATURE_COLS if c not in lag))


CANDIDATES = {"v1": v1_candidate, "current_season": current_season_candidate}


def get_candidate(name: str) -> Candidate:
    if name not in CANDIDATES:
        raise KeyError(f"unknown candidate '{name}'; choices: {sorted(CANDIDATES)}")
    return CANDIDATES[name]()
