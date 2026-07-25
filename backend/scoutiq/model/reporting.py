"""Pure reporting helpers for the valuation backtest.

Kept free of the model, sklearn, and the DB so the population masks and
denominators behind the committed metrics can be unit-tested without training.
"""
from __future__ import annotations

import numpy as np


def persistence_reference(
    y_true: np.ndarray,
    prior_pct_cap: np.ndarray,
    segment_mask: np.ndarray,
) -> dict:
    """Persistence baseline (predict next pay = prior salary) for one segment.

    ``segment_mask`` selects the rows in the segment. The baseline is only
    defined where a prior salary is known, so the MAE is computed on that usable
    subset while the segment size and the usable-subset size are reported
    alongside it -- no hidden minimum-sample gate, so callers can judge the
    sample size from ``n_with_prior`` rather than silently getting ``None``.
    Percent-of-cap, MAE rounded to 3 dp to match ``metrics.json``.
    """
    segment_mask = np.asarray(segment_mask, dtype=bool)
    y_true = np.asarray(y_true, dtype=float)
    prior = np.asarray(prior_pct_cap, dtype=float)

    usable = segment_mask & ~np.isnan(prior)
    if usable.any():
        mae_pct = round(float(np.mean(np.abs(y_true[usable] - prior[usable]))) * 100, 3)
    else:
        mae_pct = None

    return {
        "n": int(segment_mask.sum()),
        "n_with_prior": int(usable.sum()),
        "persistence_mae_pct": mae_pct,
    }


def segment_persistence_metrics(
    y_true: np.ndarray,
    prior_pct_cap: np.ndarray,
    decision_point: np.ndarray,
) -> dict:
    """Persistence reference for both backtest segments from one calculation.

    "Mid-contract" means the target season does **not** start a new contract
    (``decision_point == False``) -- a decision-point row is never counted as
    mid-contract merely because a prior salary exists. Both the segments table
    and the top-level mid-contract fields read from this single result, so their
    populations and MAEs cannot drift apart.
    """
    decision_point = np.asarray(decision_point, dtype=bool)
    return {
        "decision_point": persistence_reference(y_true, prior_pct_cap, decision_point),
        "mid_contract": persistence_reference(y_true, prior_pct_cap, ~decision_point),
    }
