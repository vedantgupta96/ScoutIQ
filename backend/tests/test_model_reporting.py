import json
from pathlib import Path

import numpy as np

from scoutiq.model.reporting import (
    build_segment,
    persistence_reference,
    segment_persistence_metrics,
)

ARTIFACTS = Path(__file__).resolve().parents[1] / "scoutiq" / "model" / "artifacts"
METRICS = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))
REPORT = (ARTIFACTS / "report.md").read_text(encoding="utf-8")


def test_persistence_reference_counts_and_mae_on_fixture():
    # segment_mask selects mid-contract rows (decision_point == False).
    # A: decision-point WITH prior (excluded). B, C: usable mid-contract.
    # D: mid-contract missing prior (counted, not usable). E: decision-point missing prior (excluded).
    y_true = np.array([0.20, 0.18, 0.20, 0.30, 0.05])
    prior = np.array([0.10, 0.15, 0.25, np.nan, np.nan])
    decision_point = np.array([True, False, False, False, True])

    ref = persistence_reference(y_true, prior, ~decision_point)

    assert ref["n"] == 3
    assert ref["n_with_prior"] == 2
    # MAE over B, C: mean(|0.18-0.15|, |0.20-0.25|) = 0.04 -> 4.0% of cap
    assert ref["persistence_mae_pct"] == 4.0


def test_persistence_reference_reports_mae_from_a_single_usable_row():
    # No hidden minimum-sample gate: one usable row yields an MAE, with n_with_prior exposed so a
    # consumer can judge the sample size.
    ref = persistence_reference(
        np.array([0.20, 0.30]), np.array([0.14, np.nan]), np.array([True, True])
    )

    assert ref["n"] == 2
    assert ref["n_with_prior"] == 1
    assert ref["persistence_mae_pct"] == round(abs(0.20 - 0.14) * 100, 3)


def test_persistence_reference_null_mae_without_usable_prior():
    ref = persistence_reference(
        np.array([0.20, 0.30]), np.array([np.nan, np.nan]), np.array([True, True])
    )

    assert ref["n"] == 2
    assert ref["n_with_prior"] == 0
    assert ref["persistence_mae_pct"] is None


def test_segment_metrics_never_label_decision_point_rows_midcontract():
    # A decision-point row carrying a prior salary must not inflate the mid-contract population or
    # bias its persistence MAE -- the exact bug (#107).
    y_true = np.array([0.20, 0.18, 0.22])
    prior = np.array([0.10, 0.15, 0.25])
    decision_point = np.array([True, False, False])

    both = segment_persistence_metrics(y_true, prior, decision_point)

    assert both["mid_contract"]["n"] == 2
    assert both["mid_contract"]["n_with_prior"] == 2
    assert both["decision_point"]["n"] == 1
    assert both["mid_contract"]["persistence_mae_pct"] == round(
        float(np.mean([abs(0.18 - 0.15), abs(0.22 - 0.25)])) * 100, 3
    )


def test_build_segment_orders_counts_then_model_metrics_then_persistence():
    ref = {"n": 100, "n_with_prior": 80, "persistence_mae_pct": 1.5}

    seg = build_segment(
        ref, {"mae_pct_of_cap": 2.6, "r2": 0.8, "interval_80_coverage": 0.87}
    )

    assert list(seg.keys()) == [
        "n", "n_with_prior", "mae_pct_of_cap", "r2", "interval_80_coverage", "persistence_mae_pct",
    ]
    assert seg["n"] == 100
    assert seg["n_with_prior"] == 80
    assert seg["persistence_mae_pct"] == 1.5


def test_small_segment_keeps_population_and_persistence_fields():
    # Assembly branch for a segment with fewer than five rows: MAE/R^2/coverage are omitted (too few
    # rows to score), but n, n_with_prior, and persistence_mae_pct still come from the shared result,
    # so the segment cannot diverge from the top-level mid-contract fields.
    y_true = np.array([0.20, 0.18, 0.22])          # 1 decision-point, 2 mid-contract (<5)
    prior = np.array([0.10, 0.15, 0.25])
    decision_point = np.array([True, False, False])

    persistence = segment_persistence_metrics(y_true, prior, decision_point)
    mid_ref = persistence["mid_contract"]

    seg = build_segment(mid_ref, None)  # <5 rows -> no model metrics

    assert seg == {
        "n": 2,
        "n_with_prior": 2,
        "persistence_mae_pct": mid_ref["persistence_mae_pct"],
    }
    assert "mae_pct_of_cap" not in seg
    # top-level mid-contract fields read from the SAME ref -> identical even though the segment was
    # too small to score:
    assert mid_ref["n"] == seg["n"]
    assert mid_ref["n_with_prior"] == seg["n_with_prior"]
    assert mid_ref["persistence_mae_pct"] == seg["persistence_mae_pct"]


def test_committed_top_level_agrees_with_segment_population():
    # Regression guard on the committed artifact: the top-level mid-contract fields must equal the
    # segments.mid_contract population they are derived from -- all three, not just n.
    mid = METRICS["segments"]["mid_contract"]
    assert METRICS["n_midcontract"] == mid["n"]
    assert METRICS["n_midcontract_with_prior"] == mid["n_with_prior"]
    assert METRICS["persistence_ref_mae_pct_midcontract"] == mid["persistence_mae_pct"]


def test_committed_segments_expose_usable_prior_counts():
    assert METRICS["segments"]["decision_point"]["n_with_prior"] == 200
    assert METRICS["segments"]["mid_contract"]["n_with_prior"] == 562


def test_committed_metrics_use_corrected_population():
    assert METRICS["n_midcontract"] == 577
    assert METRICS["n_midcontract_with_prior"] == 562
    assert METRICS["persistence_ref_mae_pct_midcontract"] == 1.212


def test_report_prose_does_not_mislabel_decision_point_rows():
    # The old prose called 762 rows "mid-contract" because they carried a prior salary.
    assert "762 mid-contract" not in REPORT
    assert "577" in REPORT and "562" in REPORT and "1.212" in REPORT
