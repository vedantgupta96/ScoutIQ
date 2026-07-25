"""Model candidates for the offline harness.

A candidate is the v1 fitting pipeline (HistGradientBoosting point model + CQR
adaptive intervals) restricted to a feature set. Fitting and conformal
calibration for a fold use only that fold's training rows (all with a target
strictly before the validation target), so nothing downstream leaks. This module
never loads or writes production model.joblib.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split

from scoutiq.model.features import FEATURE_COLS, LAG_FEATURES, TARGET
from scoutiq.model.train import PRIMARY_ALPHA, SEED, conformal_q

# v1 production hyperparameters (mirror scoutiq.model.train.main); kept here so the
# harness reproduces the baseline without importing production training internals.
V1_HGB_PARAMS = dict(max_iter=500, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0)
CAL_LEVELS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]


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
        """Fit on ``train``, predict on ``val``. Returns point predictions, an 80%
        interval, a per-level conformal calibration table, and the naive train-mean
        reference — all computed with train-only data."""
        cols = list(self.feature_cols)
        pt_idx, cal_idx = train_calibration_split(train, seed)
        Xpt, ypt = train.loc[pt_idx, cols], train.loc[pt_idx, TARGET].to_numpy()
        Xcal, ycal = train.loc[cal_idx, cols], train.loc[cal_idx, TARGET].to_numpy()

        params = dict(V1_HGB_PARAMS, random_state=seed)
        point = HistGradientBoostingRegressor(**params).fit(Xpt, ypt)
        lo_m = HistGradientBoostingRegressor(loss="quantile", quantile=alpha / 2, **params).fit(Xpt, ypt)
        hi_m = HistGradientBoostingRegressor(loss="quantile", quantile=1 - alpha / 2, **params).fit(Xpt, ypt)

        cqr_scores = np.maximum(lo_m.predict(Xcal) - ycal, ycal - hi_m.predict(Xcal))

        Xval = val[cols]
        pred = point.predict(Xval)
        qlo, qhi = lo_m.predict(Xval), hi_m.predict(Xval)
        yval = val[TARGET].to_numpy()

        q80 = conformal_q(cqr_scores, 1 - alpha)
        lo = np.minimum(qlo - q80, pred)
        hi = np.maximum(qhi + q80, pred)

        calibration = []
        for lvl in CAL_LEVELS:
            q = conformal_q(cqr_scores, lvl)
            lo_l = np.minimum(qlo - q, pred)
            hi_l = np.maximum(qhi + q, pred)
            covered = (yval >= lo_l) & (yval <= hi_l)
            calibration.append({
                "nominal": lvl,
                "empirical": round(float(np.mean(covered)), 3) if len(yval) else None,
                "half_width_pct": round(float(np.mean((hi_l - lo_l) / 2)) * 100, 2) if len(yval) else None,
            })

        return {"pred": pred, "lo": lo, "hi": hi, "calibration": calibration,
                "train_mean_pct_cap": float(np.mean(train[TARGET].to_numpy()))}


def v1_candidate() -> Candidate:
    return Candidate("v1", tuple(FEATURE_COLS))


def current_season_candidate() -> Candidate:
    """Ablation baseline: v1 pipeline without the multi-season lag block. A real,
    no-new-data candidate the harness can compare against v1."""
    lag = set(LAG_FEATURES)
    return Candidate("current_season", tuple(c for c in FEATURE_COLS if c not in lag))


CANDIDATES = {"v1": v1_candidate, "current_season": current_season_candidate}


def get_candidate(name: str) -> Candidate:
    if name not in CANDIDATES:
        raise KeyError(f"unknown candidate '{name}'; choices: {sorted(CANDIDATES)}")
    return CANDIDATES[name]()
