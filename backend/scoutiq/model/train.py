"""Train + backtest the v1 valuation model.

- Model: HistGradientBoostingRegressor (handles NaN, strong tabular baseline).
- Intervals: conformalized quantile regression (CQR) for adaptive per-player uncertainty.
- Backtest: strict temporal split configured from the available target seasons.
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
from sklearn.model_selection import StratifiedKFold, train_test_split  # noqa: E402

from scoutiq.model.dataset import build_dataset  # noqa: E402
from scoutiq.model.features import FEATURE_COLS, TARGET  # noqa: E402

ART = Path(__file__).parent / "artifacts"
TRAIN_MAX_TARGET = "2023-24"          # train where next_season <= this (lexicographic works for YYYY-YY)
TEST_SEASONS = ["2024-25", "2025-26"]  # 2025-26 targets are bridged contract cap hits (test-only, never trained)
MODEL_VERSION = "v1-gbm-cqr-lags-dpcal"


def _test_range_label() -> str:
    """e.g. ['2024-25','2025-26'] -> '2024-26' for report/plot titles."""
    start = TEST_SEASONS[0].split("-")[0]
    end = TEST_SEASONS[-1].split("-")[1]
    return f"{start}-{end}"
PRIMARY_ALPHA = 0.20                  # -> 80% prediction interval
CAL_LEVELS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
SEED = 42


def conformal_q(resid: np.ndarray, level: float) -> float:
    """Split-conformal quantile of |residual| for a target coverage `level`."""
    n = len(resid)
    k = min(np.ceil((n + 1) * level) / n, 1.0)
    return float(np.quantile(resid, k, method="higher"))


def decision_oof_cqr_scores(
    train: pd.DataFrame, hgb_params: dict, n_splits: int = 5
) -> np.ndarray:
    """Cross-fitted CQR nonconformity scores for historical contract starts.

    Each score comes from quantile models that did not train on that row. The
    folds are stratified so all 51 known decision points contribute instead of
    the 13 that happen to land in one holdout split.
    """
    decision = train["decision_point"].to_numpy(dtype=bool)
    scores: list[np.ndarray] = []
    folds = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
    for fit_idx, held_idx in folds.split(train, decision):
        held_decision_idx = held_idx[decision[held_idx]]
        if not len(held_decision_idx):
            continue
        Xfit = train.iloc[fit_idx][FEATURE_COLS]
        yfit = train.iloc[fit_idx][TARGET].to_numpy()
        Xheld = train.iloc[held_decision_idx][FEATURE_COLS]
        yheld = train.iloc[held_decision_idx][TARGET].to_numpy()
        lo_model = HistGradientBoostingRegressor(
            loss="quantile", quantile=PRIMARY_ALPHA / 2, **hgb_params
        ).fit(Xfit, yfit)
        hi_model = HistGradientBoostingRegressor(
            loss="quantile", quantile=1 - PRIMARY_ALPHA / 2, **hgb_params
        ).fit(Xfit, yfit)
        scores.append(np.maximum(lo_model.predict(Xheld) - yheld, yheld - hi_model.predict(Xheld)))
    return np.concatenate(scores)


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

    hgb_params = dict(
        max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
        l2_regularization=1.0, random_state=SEED,
    )
    decision_cqr_scores = decision_oof_cqr_scores(train, hgb_params)
    model = HistGradientBoostingRegressor(**hgb_params)
    model.fit(Xpt, ypt)

    # CQR: quantile models give each player their own band; the conformal
    # correction restores the exact-coverage guarantee the raw quantiles lack.
    model_lo = HistGradientBoostingRegressor(loss="quantile", quantile=PRIMARY_ALPHA / 2, **hgb_params)
    model_hi = HistGradientBoostingRegressor(loss="quantile", quantile=1 - PRIMARY_ALPHA / 2, **hgb_params)
    model_lo.fit(Xpt, ypt)
    model_hi.fit(Xpt, ypt)

    qlo_cal, qhi_cal = model_lo.predict(Xcal), model_hi.predict(Xcal)
    cqr_scores = np.maximum(qlo_cal - ycal, ycal - qhi_cal)
    global_cqr_qhat = conformal_q(cqr_scores, 1 - PRIMARY_ALPHA)
    decision_cqr_qhat = conformal_q(decision_cqr_scores, 1 - PRIMARY_ALPHA)
    cqr_qhat = decision_cqr_qhat

    # --- test-set evaluation ---
    pred = model.predict(Xte)
    lo = model_lo.predict(Xte) - cqr_qhat
    hi = model_hi.predict(Xte) + cqr_qhat
    lo, hi = np.minimum(lo, pred), np.maximum(hi, pred)  # guard rare quantile crossing
    half_width = (hi - lo) / 2
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
    # production-season volume — lets the UI gate leaderboards to qualified players
    # (MPG/GP floors) so small-sample flukes don't top the bargain/overpay tables.
    val["gp"] = test["gp"].to_numpy().astype(int)
    val["min_per_g"] = (test["minutes"].to_numpy() / test["gp"].replace(0, np.nan).to_numpy()).round(1)
    val.sort_values("gap_pct", ascending=False).to_csv(ART / "valuations_test.csv", index=False)
    underpaid = val.sort_values("gap_pct", ascending=False).head(8)
    overpaid = val.sort_values("gap_pct").head(8)

    # calibration curve: recalibrate the same quantile models per nominal level
    qlo_te, qhi_te = model_lo.predict(Xte), model_hi.predict(Xte)
    decision_test = test["decision_point"].to_numpy(dtype=bool)
    calib = []
    for lvl in CAL_LEVELS:
        q = conformal_q(decision_cqr_scores, lvl)
        lo_l, hi_l = qlo_te - q, qhi_te + q
        covered = (yte >= np.minimum(lo_l, pred)) & (yte <= np.maximum(hi_l, pred))
        widths = (np.maximum(hi_l, pred) - np.minimum(lo_l, pred)) / 2
        emp = float(np.mean(covered[decision_test]))
        calib.append({
            "nominal": lvl,
            "empirical": round(emp, 3),
            "half_width_pct": round(float(np.mean(widths[decision_test])) * 100, 2),
        })

    # decision-point segmentation: the rows where a valuation model is actionable
    # (target season starts a new Spotrac contract) vs contractually locked rows.
    segments = {}
    dp = decision_test
    for name, mask in (("decision_point", dp), ("mid_contract", ~dp)):
        if mask.sum() < 5:
            segments[name] = {"n": int(mask.sum())}
            continue
        seg_prior = test["prior_pct_cap"].to_numpy()[mask]
        seg_has_prior = ~np.isnan(seg_prior)
        segments[name] = {
            "n": int(mask.sum()),
            "mae_pct_of_cap": round(mean_absolute_error(yte[mask], pred[mask]) * 100, 3),
            "r2": round(r2_score(yte[mask], pred[mask]), 3) if mask.sum() >= 30 else None,
            "interval_80_coverage": round(float(np.mean((yte[mask] >= lo[mask]) & (yte[mask] <= hi[mask]))), 3),
            "persistence_mae_pct": (
                round(mean_absolute_error(yte[mask][seg_has_prior], seg_prior[seg_has_prior]) * 100, 3)
                if seg_has_prior.sum() >= 5 else None
            ),
        }

    # permutation importance (explainability)
    perm = permutation_importance(model, Xte, yte, n_repeats=5, random_state=SEED, n_jobs=-1)
    importance = (
        pd.DataFrame({"feature": FEATURE_COLS, "importance": perm.importances_mean})
        .sort_values("importance", ascending=False).head(12)
    )

    metrics = {
        "model_version": MODEL_VERSION,
        "n_train": int(len(train)), "n_calibration": int(len(Xcal)), "n_test": int(len(test)),
        "interval_calibration": "decision_point_oof_5fold",
        "n_decision_calibration": int(len(decision_cqr_scores)),
        "global_cqr_qhat_pct": round(global_cqr_qhat * 100, 3),
        "decision_cqr_qhat_pct": round(decision_cqr_qhat * 100, 3),
        "test_seasons": TEST_SEASONS,
        "mae_pct_of_cap": round(mae_pct * 100, 3),
        "mae_usd": round(mae_usd),
        "r2": round(r2, 3),
        "interval_80_coverage": round(coverage80, 3),
        "interval_80_half_width_pct": round(float(np.mean(half_width)) * 100, 2),
        "interval_80_half_width_min_pct": round(float(np.min(half_width)) * 100, 2),
        "interval_80_half_width_max_pct": round(float(np.max(half_width)) * 100, 2),
        "naive_mean_baseline_mae_pct": round(naive_mae * 100, 3),
        "persistence_ref_mae_pct_midcontract": round(persistence_mae_mid * 100, 3),
        "n_midcontract": int(has_prior.sum()),
        "segments": segments,
        "calibration": calib,
    }

    _plots(yte, pred, lo, hi, cap_te, calib)
    _write_report(metrics, importance, underpaid, overpaid)
    medians = {c: float(v) for c, v in Xpt.median(numeric_only=True).items() if np.isfinite(v)}
    joblib.dump(
        {
            "model": model,
            "model_lo": model_lo,
            "model_hi": model_hi,
            "cqr_qhat_80": float(cqr_qhat),
            "feature_medians": medians,
            "features": FEATURE_COLS,
            "version": MODEL_VERSION,
        },
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
    ax.set_title(f"Predicted vs Actual — test ({_test_range_label()})")
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
    ax.set_ylabel("Empirical coverage (contract starts)")
    ax.set_title("Decision-point interval calibration")
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
        "# Valuation model — v1 backtest",
        "",
        f"**Model:** `{m['model_version']}` (HistGradientBoosting point model + CQR adaptive intervals "
        "+ lagged-season features)",
        "**What it does:** estimates a player's **production-implied market value** (salary as % of cap) "
        "from on-court production. It is *not* given the player's current salary — so the prediction is "
        "what production says they're worth, and the gap to actual pay is the signal.",
        f"**Framing:** features = production at season *t* → value at *t+1*, strict temporal split (no "
        f"leakage). Train target-seasons ≤ {TRAIN_MAX_TARGET} ({m['n_train']} rows, "
        f"{m['n_calibration']} held out for conformal calibration); test {m['test_seasons']} "
        f"({m['n_test']} rows).",
        f"**Interval calibration:** five-fold out-of-fold scores from "
        f"{m['n_decision_calibration']} historical contract starts. The nominal 80% interval is "
        "calibrated for contract decisions, so all-row coverage may be conservative.",
        "",
        "_Note: the newest test season's actual pay is the per-season contract cap hit (Spotrac-sourced), "
        "since realized box-score salary tables lag a year. This is the same pay figure the live product "
        "compares against, and it is used for evaluation only — never as a training target._",
        "",
        f"## Headline metrics (test {_test_range_label()})",
        "| Metric | Value |",
        "|---|---|",
        f"| MAE | **{m['mae_pct_of_cap']}% of cap** (~${m['mae_usd']:,}) |",
        f"| R² | **{m['r2']}** |",
        f"| Naive (predict mean) MAE | {m['naive_mean_baseline_mae_pct']}% of cap |",
        f"| 80% interval coverage | **{m['interval_80_coverage']}** (target 0.80) |",
        f"| 80% interval half-width | mean ±{m['interval_80_half_width_pct']}% of cap "
        f"(min ±{m['interval_80_half_width_min_pct']}, max ±{m['interval_80_half_width_max_pct']}) — "
        "**adaptive per player** |",
        "",
        "## Decision-point vs mid-contract",
        "Valuation matters where a contract is actually being set. Segments split the test set on "
        "whether the target season starts a new Spotrac contract.",
        "",
        "| Segment | n | MAE (% cap) | R² | 80% coverage | Persistence MAE |",
        "|---|---|---|---|---|---|",
        *[
            f"| {name.replace('_', ' ')} | {s.get('n')} | {s.get('mae_pct_of_cap', '—')} | "
            f"{s.get('r2') if s.get('r2') is not None else '—'} | {s.get('interval_80_coverage', '—')} | "
            f"{s.get('persistence_mae_pct') if s.get('persistence_mae_pct') is not None else '—'} |"
            for name, s in m.get("segments", {}).items()
        ],
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
