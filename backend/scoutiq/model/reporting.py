"""Pure reporting helpers for the valuation backtest.

Kept free of the model, sklearn, and the DB so the population masks and
denominators behind the committed metrics can be unit-tested without training.
"""
from __future__ import annotations

import numpy as np


def midcontract_persistence_reference(
    y_true: np.ndarray,
    prior_pct_cap: np.ndarray,
    decision_point: np.ndarray,
) -> dict:
    """Persistence baseline restricted to the true mid-contract population.

    "Mid-contract" means the target season does **not** start a new contract
    (``decision_point == False``) -- the exact population the segment table uses.
    A decision-point row is never counted as mid-contract merely because a prior
    salary exists.

    The persistence baseline (predict next pay = the player's prior salary) is
    only defined where a prior salary is known, so the MAE is computed on that
    usable subset while the total mid-contract count is reported alongside it.
    Both denominators come from here so the top-level metric and the
    ``segments.mid_contract`` population cannot drift apart.

    Returns percent-of-cap values rounded to 3 dp to match ``metrics.json``.
    """
    decision_point = np.asarray(decision_point, dtype=bool)
    y_true = np.asarray(y_true, dtype=float)
    prior = np.asarray(prior_pct_cap, dtype=float)

    midcontract = ~decision_point
    usable = midcontract & ~np.isnan(prior)

    if usable.any():
        mae_pct = round(float(np.mean(np.abs(y_true[usable] - prior[usable]))) * 100, 3)
    else:
        mae_pct = None

    return {
        "n_midcontract": int(midcontract.sum()),
        "n_midcontract_with_prior": int(usable.sum()),
        "persistence_mae_pct": mae_pct,
    }
