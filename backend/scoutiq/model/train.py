"""Train + backtest the v0 valuation model.

- Model: HistGradientBoostingRegressor (handles NaN, strong tabular baseline).
- Intervals: split-conformal (a calibration slice of the training data gives a marginal coverage
  guarantee — the honest way to attach uncertainty).
- Backtest: strict temporal split. Train on target seasons <= 2022-23, test on 2023-24 & 2024-25.
- Reports: MAE in % of cap and in $, R^2, a persistence baseline, and a calibration table/curve
  (nominal vs. empirical coverage) — calibration is the credibility centerpiece.

Usage:  python -m scoutiq.model.train
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import mean_absolute_error, r2_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from scoutiq.model.dataset import build_dataset  # noqa: E402
from scoutiq.model.features import FEATURE_COLS, TARGET  # noqa: E402

ART = Path(__file__).parent / "artifacts"
TRAIN_MAX_TARGET = "2022-23"          # train where next_season <= this (lexicographic works for YYYY-YY)
TEST_SEASONS = ["2023-24", "2024-25"]
MODEL_VERSION = "v0-gbm-conformal"
PRIMARY_ALPHA = 0.20                  # -> 80% prediction interval
CAL_LEVELS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
SEED = 42


def conformal_q(resid: np.ndarray, level: float) -> float:
    """Split-conformal quantile of |residual| for a target coverage `level`."""
    n = len(resid)
    k = min(np.ceil((n + 1) * level) / n, 1.0)
    return float(np.quantile(resid, k, method="higher"))


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    df = build_dataset()

    train = df[df["next_season"] <= TRAIN_MAX_TARGET]
    test = df[df["next_season"].isin(TEST_SEASONS)]
    Xtr, ytr = train[FEATURE_COLS], train[TARGET].to_numpy()
    Xte, yte = test[FEATURE_COLS], test[TARGET].to_numpy()
    cap_te = test["target_cap"].to_numpy()

    # proper-train / calibration split for conformal
    Xpt, Xcal, ypt, ycal = train_test_split(Xtr, ytr, test_size=0.25, random_state=SEED)

    model = HistGradientBoostingRegressor(
        max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
        l2_regularization=1.0, random_state=SEED,
    )
    model.fit(Xpt, ypt)

    cal_resid = np.abs(ycal - model.predict(Xcal))
    qhat = conformal_q(cal_resid, 1 - PRIMARY_ALPHA)

    # --- test-set evaluation ---
    pred = model.predict(Xte)
    lo, hi = pred - qhat, pred + qhat
    mae_pct = mean_absolute_error(yte, pred)
    mae_usd = float(np.mean(np.abs(yte - pred) * cap_te))
    r2 = r2_score(yte, pred)
    coverage80 = float(np.mean((yte >= lo) & (yte <= hi)))

    # naive baseline: predict the training-mean %cap (what "no model" looks like). The model should
    # crush this — that gap is how much production explains pay.
    naive = float(np.mean(ytr))
    naive_mae = mean_absolute_error(yte, np.full_like(yte, naive))

    # honest reference: a persistence baseline using CURRENT salary (which we deliberately exclude as a
    # feature) is hard to beat on mid-contract players — pay is contractually sticky, not a production
    # signal. We report it so the trade-off is explicit, not hidden.
    prior = test["prior_pct_cap"].to_numpy()
    has_prior = ~np.isnan(prior)
    persistence_mae_mid = mean_absolute_error(yte[has_prior], prior[has_prior])

    # actionable output: production-implied value vs actual pay (next season).
    # gap > 0  => model values them above their pay (bargain);  gap < 0 => overpaid.
    val = test[["full_name", "next_season"]].copy()
    val["actual_pct"] = (yte * 100).round(2)
    val["value_pct"] = (pred * 100).round(2)
    val["gap_pct"] = ((pred - yte) * 100).round(2)
    val.sort_values("gap_pct", ascending=False).to_csv(ART / "valuations_test.csv", index=False)
    underpaid = val.sort_values("gap_pct", ascending=False).head(8)
    overpaid = val.sort_values("gap_pct").head(8)

    # calibration curve: nominal vs empirical coverage
    calib = []
    for lvl in CAL_LEVELS:
        q = conformal_q(cal_resid, lvl)
        emp = float(np.mean(np.abs(yte - pred) <= q))
        calib.append({"nominal": lvl, "empirical": round(emp, 3), "half_width_pct": round(q * 100, 2)})

    # permutation importance (explainability)
    perm = permutation_importance(model, Xte, yte, n_repeats=5, random_state=SEED, n_jobs=-1)
    importance = (
        pd.DataFrame({"feature": FEATURE_COLS, "importance": perm.importances_mean})
        .sort_values("importance", ascending=False).head(12)
    )

    metrics = {
        "model_version": MODEL_VERSION,
        "n_train": int(len(train)), "n_calibration": int(len(Xcal)), "n_test": int(len(test)),
        "test_seasons": TEST_SEASONS,
        "mae_pct_of_cap": round(mae_pct * 100, 3),
        "mae_usd": round(mae_usd),
        "r2": round(r2, 3),
        "interval_80_coverage": round(coverage80, 3),
        "interval_80_half_width_pct": round(qhat * 100, 2),
        "naive_mean_baseline_mae_pct": round(naive_mae * 100, 3),
        "persistence_ref_mae_pct_midcontract": round(persistence_mae_mid * 100, 3),
        "n_midcontract": int(has_prior.sum()),
        "calibration": calib,
    }

    _plots(yte, pred, lo, hi, cap_te, calib)
    _write_report(metrics, importance, underpaid, overpaid)
    joblib.dump(
        {"model": model, "qhat_80": qhat, "features": FEATURE_COLS, "version": MODEL_VERSION},
        ART / "model.joblib",
    )
    (ART / "metrics.json").write_text(json.dumps(metrics, indent=2))

    print(json.dumps({k: v for k, v in metrics.items() if k != "calibration"}, indent=2))
    print("\ncalibration (nominal -> empirical coverage):")
    for c in calib:
        print(f"  {c['nominal']:.2f} -> {c['empirical']:.3f}  (±{c['half_width_pct']}% cap)")
    print("\nmost underpaid (value > pay):")
    for r in underpaid.head(5).itertuples():
        print(f"  {r.full_name:24} {r.next_season}  value {r.value_pct:>5}%  pay {r.actual_pct:>5}%  gap {r.gap_pct:+.1f}")
    print("most overpaid (pay > value):")
    for r in overpaid.head(5).itertuples():
        print(f"  {r.full_name:24} {r.next_season}  value {r.value_pct:>5}%  pay {r.actual_pct:>5}%  gap {r.gap_pct:+.1f}")
    print(f"\nartifacts written to {ART}")


def _plots(yte, pred, lo, hi, cap_te, calib) -> None:
    # predicted vs actual (% of cap)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(yte * 100, pred * 100, s=10, alpha=0.4)
    lim = max((yte * 100).max(), (pred * 100).max()) * 1.05
    ax.plot([0, lim], [0, lim], "r--", lw=1)
    ax.set_xlabel("Actual salary (% of cap)")
    ax.set_ylabel("Predicted (% of cap)")
    ax.set_title("Predicted vs Actual — test (2023-25)")
    fig.tight_layout()
    fig.savefig(ART / "pred_vs_actual.png", dpi=120)
    plt.close(fig)

    # calibration curve (nominal vs empirical)
    fig, ax = plt.subplots(figsize=(5, 5))
    noms = [c["nominal"] for c in calib]
    emps = [c["empirical"] for c in calib]
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="ideal")
    ax.plot(noms, emps, "o-", label="conformal")
    ax.set_xlabel("Nominal coverage")
    ax.set_ylabel("Empirical coverage (test)")
    ax.set_title("Interval calibration")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ART / "coverage_curve.png", dpi=120)
    plt.close(fig)


def _val_table(rows: pd.DataFrame) -> list[str]:
    out = ["| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |", "|---|---|---|---|---|"]
    out += [
        f"| {r.full_name} | {r.next_season} | {r.value_pct} | {r.actual_pct} | {r.gap_pct:+} |"
        for r in rows.itertuples()
    ]
    return out


def _write_report(metrics: dict, importance: pd.DataFrame, underpaid: pd.DataFrame, overpaid: pd.DataFrame) -> None:
    m = metrics
    lines = [
        "# Valuation model — v0 backtest",
        "",
        f"**Model:** `{m['model_version']}` (HistGradientBoosting + split-conformal intervals)  ",
        "**What it does:** estimates a player's **production-implied market value** (salary as % of cap) "
        "from on-court production. It is *not* given the player's current salary — so the prediction is "
        "what production says they're worth, and the gap to actual pay is the signal.  ",
        f"**Framing:** features = production at season *t* → value at *t+1*, strict temporal split (no "
        f"leakage). Train target-seasons ≤ {TRAIN_MAX_TARGET} ({m['n_train']} rows, "
        f"{m['n_calibration']} held out for conformal calibration); test {m['test_seasons']} "
        f"({m['n_test']} rows).",
        "",
        "## Headline metrics (test 2023-25)",
        "| Metric | Value |",
        "|---|---|",
        f"| MAE | **{m['mae_pct_of_cap']}% of cap** (~${m['mae_usd']:,}) |",
        f"| R² | **{m['r2']}** |",
        f"| Naive (predict mean) MAE | {m['naive_mean_baseline_mae_pct']}% of cap |",
        f"| 80% interval coverage | **{m['interval_80_coverage']}** (target 0.80) |",
        f"| 80% interval half-width | ±{m['interval_80_half_width_pct']}% of cap |",
        "",
        f"Production alone explains **R²={m['r2']}** of pay and cuts error to "
        f"{m['mae_pct_of_cap']}% vs {m['naive_mean_baseline_mae_pct']}% for a mean-predictor — i.e. how "
        "much salary is driven by production.",
        "",
        "## Honest caveat: salary stickiness",
        f"A persistence reference (predict next pay = *current* salary, which we deliberately **exclude** "
        f"as a feature) scores {m['persistence_ref_mae_pct_midcontract']}% MAE on the "
        f"{m['n_midcontract']} mid-contract test players — better than this model on those rows. That's "
        "expected: their pay is contractually locked, not a production signal. We exclude current salary "
        "on purpose so the model answers *worth*, not *what's already on the books*. The v1 upgrade "
        "(contract-AAV target via Spotrac) evaluates at contract-decision points directly.",
        "",
        "## Bargains & overpays (test set)",
        "Largest gaps between production-implied value and actual pay — the actionable output.",
        "",
        "**Most underpaid (production worth more than pay):**",
        *_val_table(underpaid),
        "",
        "**Most overpaid (paid more than production implies):**",
        *_val_table(overpaid),
        "",
        "## Interval calibration",
        "Conformal intervals are well-calibrated when empirical ≈ nominal.",
        "",
        "| Nominal | Empirical | ± half-width (% cap) |",
        "|---|---|---|",
        *[f"| {c['nominal']:.2f} | {c['empirical']:.3f} | {c['half_width_pct']} |" for c in m["calibration"]],
        "",
        "![calibration](coverage_curve.png)",
        "![predicted vs actual](pred_vs_actual.png)",
        "",
        "## Top features (permutation importance)",
        "| Feature | Importance |",
        "|---|---|",
        *[f"| {r.feature} | {r.importance:.4f} |" for r in importance.itertuples()],
        "",
    ]
    (ART / "report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
