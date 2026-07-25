import json
from pathlib import Path

import numpy as np

from scoutiq.model.reporting import persistence_reference, segment_persistence_metrics

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
    # consumer can judge the sample size. This is the edge the two old implementations disagreed on.
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
    # mid-contract MAE excludes the decision-point row (prior 0.10):
    assert both["mid_contract"]["persistence_mae_pct"] == round(
        float(np.mean([abs(0.18 - 0.15), abs(0.22 - 0.25)])) * 100, 3
    )


def test_top_level_and_segment_share_one_calculation():
    # Mirrors train.py's wiring: segments.mid_contract AND the top-level mid-contract fields are read
    # from the SAME segment_persistence_metrics result, so they cannot drift apart within a run.
    y_true = np.array([0.20, 0.18, 0.22, 0.30])
    prior = np.array([0.10, 0.15, 0.25, np.nan])
    decision_point = np.array([True, False, False, False])

    both = segment_persistence_metrics(y_true, prior, decision_point)
    mid = both["mid_contract"]

    # concrete values: mid-contract = rows 1,2,3; usable = rows 1,2; MAE = mean(0.03, 0.03) = 3.0
    assert mid["n"] == 3
    assert mid["n_with_prior"] == 2
    assert mid["persistence_mae_pct"] == 3.0

    # top-level fields and the segment table both read from `mid` -> identical by construction
    assert mid["n"] == both["mid_contract"]["n"]
    assert mid["persistence_mae_pct"] == both["mid_contract"]["persistence_mae_pct"]
    assert mid["n_with_prior"] <= mid["n"]


def test_committed_top_level_agrees_with_segment_population():
    # Regression guard on the committed artifact: the top-level mid-contract metric must equal the
    # segments.mid_contract population it is derived from.
    mid = METRICS["segments"]["mid_contract"]
    assert METRICS["n_midcontract"] == mid["n"]
    assert METRICS["persistence_ref_mae_pct_midcontract"] == mid["persistence_mae_pct"]
    assert METRICS["n_midcontract_with_prior"] <= METRICS["n_midcontract"]


def test_committed_metrics_use_corrected_population():
    assert METRICS["n_midcontract"] == 577
    assert METRICS["n_midcontract_with_prior"] == 562
    assert METRICS["persistence_ref_mae_pct_midcontract"] == 1.212


def test_report_prose_does_not_mislabel_decision_point_rows():
    # The old prose called 762 rows "mid-contract" because they carried a prior salary.
    assert "762 mid-contract" not in REPORT
    assert "577" in REPORT and "562" in REPORT and "1.212" in REPORT
