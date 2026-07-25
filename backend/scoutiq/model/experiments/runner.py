"""Run the harness: fit each candidate across the rolling-origin folds and
assemble per-season and weighted-aggregate results, then the promotion gates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scoutiq.model.train import SEED
from scoutiq.model.experiments.candidates import Candidate, get_candidate
from scoutiq.model.experiments.folds import Fold, fold_frames, rolling_origin_folds
from scoutiq.model.experiments.gates import evaluate_gates, overall_decision
from scoutiq.model.experiments.metrics import evaluate_predictions

HARNESS_VERSION = "rolling-origin-v1"


def _weighted_calibration(per_season: list[dict]) -> list[dict]:
    if not per_season:
        return []
    levels = [c["nominal"] for c in per_season[0]["calibration"]]
    out = []
    for i, lvl in enumerate(levels):
        emp_num = wid_num = 0.0
        den = 0
        for s in per_season:
            c = s["calibration"][i]
            if c["empirical"] is None:
                continue
            emp_num += c["empirical"] * s["n"]
            wid_num += c["half_width_pct"] * s["n"]
            den += s["n"]
        out.append({"nominal": lvl,
                    "empirical": round(emp_num / den, 3) if den else None,
                    "half_width_pct": round(wid_num / den, 2) if den else None})
    return out


def run_candidate(df: pd.DataFrame, folds: list[Fold], candidate: Candidate, *, seed: int = SEED) -> dict:
    per_season = []
    pool_val, pool_pred, pool_lo, pool_hi, pool_naive = [], [], [], [], []
    for fold in folds:
        train, val = fold_frames(df, fold)
        out = candidate.fit_predict(train, val, seed=seed)
        naive = np.full(len(val), out["train_mean_pct_cap"])
        per_season.append({
            "val_target": fold.val_target,
            "n_train": int(len(train)),
            **evaluate_predictions(val, out["pred"], out["lo"], out["hi"],
                                   naive_pred=naive, calibration=out["calibration"],
                                   feature_cols=candidate.feature_cols),
        })
        pool_val.append(val); pool_pred.append(out["pred"]); pool_lo.append(out["lo"])
        pool_hi.append(out["hi"]); pool_naive.append(naive)

    aggregate = evaluate_predictions(
        pd.concat(pool_val), np.concatenate(pool_pred), np.concatenate(pool_lo),
        np.concatenate(pool_hi), naive_pred=np.concatenate(pool_naive),
        calibration=_weighted_calibration(per_season), feature_cols=candidate.feature_cols,
    ) if per_season else {}

    return {"candidate": candidate.name, "n_features": len(candidate.feature_cols),
            "per_season": per_season, "aggregate": aggregate}


def run_evaluation(df: pd.DataFrame, *, baseline: str = "v1", candidate: str | None = None,
                   min_train_seasons: int = 3, seed: int = SEED) -> dict:
    target_seasons = sorted(df["next_season"].dropna().unique().tolist())
    folds = rolling_origin_folds(target_seasons, min_train_seasons=min_train_seasons)
    baseline_run = run_candidate(df, folds, get_candidate(baseline), seed=seed)
    candidate_run = (run_candidate(df, folds, get_candidate(candidate), seed=seed)
                     if candidate and candidate != baseline else None)
    gates = evaluate_gates(baseline_run, candidate_run, folds)
    decision = overall_decision(gates, candidate_present=candidate_run is not None)
    return {
        "harness_version": HARNESS_VERSION,
        "seed": seed,
        "dataset": {"n_rows": int(len(df)), "target_seasons": target_seasons,
                    "min_train_seasons": min_train_seasons},
        "folds": [{"val_target": f.val_target, "train_targets": list(f.train_targets)} for f in folds],
        "baseline": baseline_run,
        "candidate": candidate_run,
        "promotion_gates": gates,
        "decision": decision,
    }
