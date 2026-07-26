import json

import numpy as np
import pandas as pd
import pytest

from scoutiq.model import spec
from scoutiq.model.experiments import candidates
from scoutiq.model.experiments.candidates import train_calibration_split
from scoutiq.model.experiments.evaluate import DEFAULT_OUT_DIR
from scoutiq.model.experiments.folds import Fold, fold_frames, rolling_origin_folds
from scoutiq.model.experiments.gates import evaluate_gates
from scoutiq.model.experiments.metrics import evaluate_predictions
from scoutiq.model.experiments.runner import run_evaluation
from scoutiq.model.features import FEATURE_COLS, POSITIONS, TARGET
from scoutiq.model.reporting import segment_persistence_metrics


def _season_labels(n: int) -> list[str]:
    return [f"20{10 + i:02d}-{11 + i:02d}" for i in range(n)]


def build_synthetic_dataset(n_seasons: int = 6, rows_per_season: int = 28, seed: int = 0) -> pd.DataFrame:
    """A modeling table shaped like scoutiq.model.dataset.build_dataset(): every
    FEATURE_COLS column, TARGET (weakly correlated with BPM/pts_pg so R^2 is
    finite), prior_pct_cap (some NaN), decision_point, season/next_season, and
    full_name. Deterministic given ``seed``. No database involved.
    """
    rng = np.random.default_rng(seed)
    labels = _season_labels(n_seasons + 1)
    target_seasons = labels[1:]
    prior_of = {labels[i + 1]: labels[i] for i in range(len(labels) - 1)}

    rows = []
    pid = 0
    for ns in target_seasons:
        for _ in range(rows_per_season):
            gp = int(rng.integers(10, 83))
            minutes = float(gp * rng.uniform(12, 34))
            pts_pg = float(rng.uniform(2, 28))
            off_rtg = float(rng.uniform(95, 120))
            def_rtg = float(rng.uniform(95, 120))
            oreb_pct = float(rng.uniform(1, 15))
            dreb_pct = float(rng.uniform(5, 30))
            bpm = float(rng.normal(0, 4))
            obpm = float(rng.normal(0, 3))
            ws = float(rng.uniform(-1, 12))
            lag_gp = int(rng.integers(0, 83))
            lag_pts_pg = float(rng.uniform(2, 28))

            position = str(rng.choice(POSITIONS))
            pos_row = {f"pos_{p}": 1.0 if p == position else 0.0 for p in POSITIONS}

            noise = float(rng.normal(0, 0.02))
            target = float(np.clip(0.08 + 0.012 * bpm + 0.0035 * pts_pg + noise, 0.005, 0.9))

            prior = np.nan if rng.random() < 0.2 else float(rng.uniform(0.01, 0.35))
            decision_point = bool(rng.random() < 0.35)

            row = {
                "age": float(rng.uniform(19, 38)), "gp": gp, "minutes": minutes,
                "pts_pg": pts_pg, "reb_pg": float(rng.uniform(1, 12)), "ast_pg": float(rng.uniform(0.5, 10)),
                "stl_pg": float(rng.uniform(0.2, 2.2)), "blk_pg": float(rng.uniform(0.1, 2.5)),
                "tov_pg": float(rng.uniform(0.3, 3.5)), "fg3m_pg": float(rng.uniform(0, 3.5)),
                "USG_PCT": float(rng.uniform(10, 35)), "TS_PCT": float(rng.uniform(0.45, 0.65)),
                "EFG_PCT": float(rng.uniform(0.4, 0.62)), "PIE": float(rng.uniform(5, 20)),
                "OFF_RATING": off_rtg, "DEF_RATING": def_rtg, "NET_RATING": off_rtg - def_rtg,
                "AST_PCT": float(rng.uniform(5, 35)), "OREB_PCT": oreb_pct, "DREB_PCT": dreb_pct,
                "REB_PCT": oreb_pct + dreb_pct, "TM_TOV_PCT": float(rng.uniform(8, 18)),
                "PACE": float(rng.uniform(95, 105)),
                "BPM": bpm, "OBPM": obpm, "DBPM": bpm - obpm, "VORP": float(rng.uniform(-1, 5)),
                "WS": ws, "WS48": float(ws / max(minutes, 1.0) * 48), "PER": float(rng.uniform(5, 25)),
                "lag_gp": lag_gp, "lag_minutes": float(lag_gp * rng.uniform(10, 34)),
                "lag_pts_pg": lag_pts_pg, "lag_TS_PCT": float(rng.uniform(0.45, 0.65)),
                "lag_BPM": float(rng.normal(0, 4)), "lag_WS": float(rng.uniform(-1, 12)),
                "d_pts_pg": pts_pg - lag_pts_pg, "gp_2yr": gp + lag_gp,
                **pos_row,
                "position": position,
                "prior_pct_cap": prior,
                "decision_point": decision_point,
                "season": prior_of[ns],
                "next_season": ns,
                "full_name": f"Player {pid}",
                "target_cap": float(rng.uniform(120_000_000, 145_000_000)),
                TARGET: target,
            }
            rows.append(row)
            pid += 1

    df = pd.DataFrame(rows)
    assert set(FEATURE_COLS).issubset(df.columns)
    return df


def test_rolling_origin_folds_out_of_time_and_deterministic():
    seasons = ["2016-17", "2015-16", "2017-18", "2018-19", "2019-20"]
    ordered = sorted(set(seasons))

    folds = rolling_origin_folds(seasons, min_train_seasons=2)
    folds_again = rolling_origin_folds(seasons, min_train_seasons=2)

    assert folds == folds_again
    for i, fold in enumerate(folds, start=2):
        assert fold.val_target > max(fold.train_targets)
        assert fold.val_target not in fold.train_targets
        assert list(fold.train_targets) == ordered[:i]
        assert fold.val_target == ordered[i]


def test_fold_frames_never_leak_future_targets():
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=10, seed=1)
    target_seasons = sorted(df["next_season"].unique())
    folds = rolling_origin_folds(target_seasons, min_train_seasons=3)

    assert folds
    for fold in folds:
        train, val = fold_frames(df, fold)
        assert (train["next_season"] < fold.val_target).all()
        assert set(val["next_season"].unique()) == {fold.val_target}
        assert len(train) > 0
        assert len(val) > 0


def test_calibration_split_is_train_only():
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=10, seed=2)
    target_seasons = sorted(df["next_season"].unique())
    folds = rolling_origin_folds(target_seasons, min_train_seasons=3)
    fold = folds[0]
    train, _ = fold_frames(df, fold)

    pt_idx, cal_idx = train_calibration_split(train, seed=42)

    assert set(cal_idx).issubset(set(train.index))
    assert set(pt_idx).issubset(set(train.index))
    assert set(pt_idx).isdisjoint(set(cal_idx))
    assert (df.loc[cal_idx, "next_season"] < fold.val_target).all()


def test_segments_match_segment_persistence_metrics():
    y = np.array([0.20, 0.18, 0.22, 0.30, 0.05])
    prior = np.array([0.10, 0.15, 0.25, np.nan, np.nan])
    decision = np.array([True, False, False, False, True])
    val = pd.DataFrame({
        TARGET: y,
        "prior_pct_cap": prior,
        "decision_point": decision,
        "age": [25.0, 26.0, 27.0, 28.0, 29.0],
        "position": ["PG", "SG", "SF", "PF", "C"],
        "target_cap": [130_000_000.0] * 5,
    })
    pred = y + np.array([-0.01, -0.01, 0.01, -0.01, 0.01])
    lo, hi = pred - 0.05, pred + 0.05
    naive_pred = np.full(5, float(np.mean(y)))
    calibration = [{"nominal": 0.8, "empirical": 0.8, "half_width_pct": 5.0}]

    result = evaluate_predictions(val, pred, lo, hi, naive_pred=naive_pred,
                                  calibration=calibration, feature_cols=("age",))
    expected = segment_persistence_metrics(y, prior, decision)

    assert result["segments"]["mid_contract"]["n"] == expected["mid_contract"]["n"]
    assert result["segments"]["mid_contract"]["n_with_prior"] == expected["mid_contract"]["n_with_prior"]
    assert result["segments"]["mid_contract"]["persistence_mae_pct"] == expected["mid_contract"]["persistence_mae_pct"]
    assert result["segments"]["decision_point"]["n"] == expected["decision_point"]["n"]
    assert result["segments"]["decision_point"]["n_with_prior"] == expected["decision_point"]["n_with_prior"]
    assert result["segments"]["decision_point"]["persistence_mae_pct"] == expected["decision_point"]["persistence_mae_pct"]
    # row 0 is a decision-point row that carries a prior salary; it must not inflate mid_contract.
    assert result["segments"]["mid_contract"]["n"] == 3


def test_small_segment_keeps_population_and_persistence():
    rng = np.random.default_rng(3)
    n_mid, n_decision = 2, 6
    n = n_mid + n_decision
    decision = np.array([True] * n_decision + [False] * n_mid)
    y = rng.uniform(0.05, 0.3, n)
    prior = rng.uniform(0.05, 0.3, n)
    prior[rng.random(n) < 0.3] = np.nan
    val = pd.DataFrame({
        TARGET: y,
        "prior_pct_cap": prior,
        "decision_point": decision,
        "age": rng.uniform(20, 35, n),
        "position": rng.choice(["PG", "SG", "SF", "PF", "C"], n),
        "target_cap": rng.uniform(120_000_000, 145_000_000, n),
    })
    pred = y + rng.normal(0, 0.01, n)
    lo, hi = pred - 0.05, pred + 0.05
    naive_pred = np.full(n, float(np.mean(y)))
    calibration = [{"nominal": 0.8, "empirical": 0.8, "half_width_pct": 5.0}]

    result = evaluate_predictions(val, pred, lo, hi, naive_pred=naive_pred,
                                  calibration=calibration, feature_cols=("age",))

    mid = result["segments"]["mid_contract"]
    assert {"n", "n_with_prior", "persistence_mae_pct"}.issubset(mid.keys())
    assert "mae_pct_of_cap" not in mid


def test_run_evaluation_deterministic_for_fixed_dataset_and_seed(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 40)
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=28, seed=0)

    r1 = run_evaluation(df, seed=42)
    r2 = run_evaluation(df, seed=42)

    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    assert len(r1["baseline"]["per_season"]) == len(r1["folds"])
    assert r1["decision"] == "baseline_only"
    assert r1["baseline"]["aggregate"]["n"] == sum(s["n"] for s in r1["baseline"]["per_season"])


def test_promotion_gates_present_and_leakage_passes(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 40)
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=28, seed=0)

    r1 = run_evaluation(df, seed=42)
    gate_ids = {g["id"] for g in r1["promotion_gates"]}
    required = {
        "no_leakage", "decision_mae_vs_v1", "decision_interval_coverage", "cohort_reporting",
        "methodology_documentation", "pct_of_cap_unit", "graceful_degradation_adr_0001",
        "artifact_report_diff_and_decision",
    }
    assert required.issubset(gate_ids)

    by_id = {g["id"]: g for g in r1["promotion_gates"]}
    assert by_id["no_leakage"]["status"] == "pass"
    assert by_id["pct_of_cap_unit"]["status"] == "pass"


def test_candidate_comparison_without_touching_production(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 40)
    out_existed = DEFAULT_OUT_DIR.exists()
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=28, seed=0)

    r = run_evaluation(df, candidate="current_season", seed=42)

    assert r["candidate"] is not None
    assert r["candidate"]["candidate"] == "current_season"
    assert len(r["baseline"]["per_season"]) == len(r["folds"])
    assert len(r["candidate"]["per_season"]) == len(r["folds"])

    gates_by_id = {g["id"]: g for g in r["promotion_gates"]}
    assert gates_by_id["decision_mae_vs_v1"]["status"] in {"pass", "fail"}
    assert r["decision"] in {"promote", "do_not_promote", "insufficient_evidence"}
    assert DEFAULT_OUT_DIR.exists() == out_existed  # run_evaluation writes nothing


def test_v1_calibration_method_selection(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 30)
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=28, seed=0)
    target_seasons = sorted(df["next_season"].unique())
    folds = rolling_origin_folds(target_seasons, min_train_seasons=3)
    train, val = fold_frames(df, folds[0])
    assert int(train["decision_point"].to_numpy(dtype=bool).sum()) >= 10

    result = candidates.v1_candidate().fit_predict(train, val, seed=42)
    assert result["calibration_method"] == "decision_point_oof"

    tiny_train = train.copy()
    tiny_train["decision_point"] = False
    tiny_train.loc[tiny_train.index[:3], "decision_point"] = True
    assert int(tiny_train["decision_point"].to_numpy(dtype=bool).sum()) < 10

    fallback = candidates.v1_candidate().fit_predict(tiny_train, val, seed=42)
    assert fallback["calibration_method"] == "global_split_conformal"


def test_develop_mode_reserves_final_holdout(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 30)
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=20, seed=5)
    target_seasons = sorted(df["next_season"].unique())
    holdout = target_seasons[-2:]

    result = run_evaluation(df, seed=42, mode="develop", holdout_seasons=holdout)

    assert result["final_holdout_seasons"] == holdout
    assert result["folds"]
    for fold in result["folds"]:
        assert fold["val_target"] not in holdout
        assert not (set(fold["train_targets"]) & set(holdout))


def test_final_mode_validates_on_holdout(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 30)
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=20, seed=5)
    target_seasons = sorted(df["next_season"].unique())
    holdout = target_seasons[-2:]

    result = run_evaluation(df, seed=42, mode="final", holdout_seasons=holdout)

    val_targets = {f["val_target"] for f in result["folds"]}
    assert val_targets == set(holdout)
    for fold in result["folds"]:
        assert all(t < fold["val_target"] for t in fold["train_targets"])


def _minimal_run(candidate_name, decision_mae, mean_ref=None, persist=None,
                 calibration_method="decision_point_oof", coverage=0.8):
    return {
        "candidate": candidate_name,
        "aggregate": {
            "decision_mae_pct_of_cap": decision_mae,
            "decision_mean_prediction_mae_pct": mean_ref,
            "calibration_method": calibration_method,
            "segments": {"decision_point": {"persistence_mae_pct": persist, "interval_80_coverage": coverage}},
        },
    }


def test_gate_requires_strict_improvement():
    folds = [Fold(("2011-12",), "2012-13")]

    def _status(c, b, mean, persist):
        baseline_run = _minimal_run("v1", b)
        candidate_run = _minimal_run("current_season", c, mean_ref=mean, persist=persist)
        gates = evaluate_gates(baseline_run, candidate_run, folds)
        return next(g for g in gates if g["id"] == "decision_mae_vs_v1")["status"]

    assert _status(3.0, 3.0, mean=2.5, persist=4.0) == "fail"
    assert _status(2.9, 3.0, mean=2.5, persist=4.0) == "fail"
    assert _status(2.9, 3.0, mean=None, persist=4.0) == "insufficient_evidence"
    assert _status(2.9, 3.0, mean=2.5, persist=None) == "insufficient_evidence"
    assert _status(2.0, 3.0, mean=2.5, persist=4.0) == "pass"


def test_coverage_gate_requires_production_calibration():
    folds = [Fold(("2011-12",), "2012-13")]
    baseline_run = _minimal_run("v1", 3.0, mean_ref=2.5, persist=4.0)

    fallback_candidate = _minimal_run("current_season", 2.0, mean_ref=2.5, persist=4.0,
                                      calibration_method="global_split_conformal", coverage=0.80)
    gates_fallback = evaluate_gates(baseline_run, fallback_candidate, folds)
    cov_gate = next(g for g in gates_fallback if g["id"] == "decision_interval_coverage")
    assert cov_gate["status"] == "insufficient_evidence"

    oof_candidate = _minimal_run("current_season", 2.0, mean_ref=2.5, persist=4.0,
                                 calibration_method="decision_point_oof", coverage=0.80)
    gates_oof = evaluate_gates(baseline_run, oof_candidate, folds)
    cov_gate2 = next(g for g in gates_oof if g["id"] == "decision_interval_coverage")
    assert cov_gate2["status"] == "pass"


def test_decision_segment_reports_interval_width_and_dollars():
    rng = np.random.default_rng(11)
    n_mid, n_decision = 2, 6
    n = n_mid + n_decision
    decision = np.array([True] * n_decision + [False] * n_mid)
    y = rng.uniform(0.05, 0.3, n)
    prior = rng.uniform(0.05, 0.3, n)
    prior[rng.random(n) < 0.3] = np.nan
    val = pd.DataFrame({
        TARGET: y,
        "prior_pct_cap": prior,
        "decision_point": decision,
        "age": rng.uniform(20, 35, n),
        "position": rng.choice(["PG", "SG", "SF", "PF", "C"], n),
        "target_cap": rng.uniform(120_000_000, 145_000_000, n),
    })
    pred = y + rng.normal(0, 0.01, n)
    lo, hi = pred - 0.05, pred + 0.05
    naive_pred = np.full(n, float(np.mean(y)))
    calibration = [{"nominal": 0.8, "empirical": 0.8, "half_width_pct": 5.0}]

    result = evaluate_predictions(val, pred, lo, hi, naive_pred=naive_pred,
                                  calibration=calibration, feature_cols=("age",))

    dp = result["segments"]["decision_point"]
    assert "interval_80_half_width_pct" in dp
    assert "mae_usd" in dp
    assert result["decision_mean_prediction_mae_pct"] is not None


def test_cli_baseline_restricted_to_v1():
    from scoutiq.model.experiments.evaluate import build_parser

    args = build_parser().parse_args(["--baseline", "v1"])
    assert args.baseline == "v1"

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--baseline", "current_season"])


def test_candidate_calibration_curve_is_decision_point(monkeypatch):
    monkeypatch.setitem(spec.HGB_PARAMS, "max_iter", 30)
    df = build_synthetic_dataset(n_seasons=6, rows_per_season=28, seed=0)
    target_seasons = sorted(df["next_season"].unique())
    folds = rolling_origin_folds(target_seasons, min_train_seasons=3)
    train, val = fold_frames(df, folds[0])
    val = val.copy()
    val["decision_point"] = False

    result = candidates.v1_candidate().fit_predict(train, val, seed=42)

    assert result["calibration"]
    assert all(c["empirical"] is None for c in result["calibration"])


def test_dollar_mae_reported():
    rng = np.random.default_rng(7)
    n_mid, n_decision = 2, 6
    n = n_mid + n_decision
    decision = np.array([True] * n_decision + [False] * n_mid)
    y = rng.uniform(0.05, 0.3, n)
    prior = rng.uniform(0.05, 0.3, n)
    prior[rng.random(n) < 0.3] = np.nan
    val = pd.DataFrame({
        TARGET: y,
        "prior_pct_cap": prior,
        "decision_point": decision,
        "age": rng.uniform(20, 35, n),
        "position": rng.choice(["PG", "SG", "SF", "PF", "C"], n),
        "target_cap": rng.uniform(120_000_000, 145_000_000, n),
    })
    pred = y + rng.normal(0, 0.01, n)
    lo, hi = pred - 0.05, pred + 0.05
    naive_pred = np.full(n, float(np.mean(y)))
    calibration = [{"nominal": 0.8, "empirical": 0.8, "half_width_pct": 5.0}]

    result = evaluate_predictions(val, pred, lo, hi, naive_pred=naive_pred,
                                  calibration=calibration, feature_cols=("age",))

    assert isinstance(result["mae_usd"], (int, float))
    dp = result["segments"]["decision_point"]
    assert "mae_usd" in dp and isinstance(dp["mae_usd"], (int, float))
    mid = result["segments"]["mid_contract"]
    assert "mae_usd" not in mid
