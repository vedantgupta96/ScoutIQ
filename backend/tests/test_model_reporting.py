import json
from pathlib import Path

import numpy as np

from scoutiq.model.reporting import midcontract_persistence_reference

ARTIFACTS = Path(__file__).resolve().parents[1] / "scoutiq" / "model" / "artifacts"
METRICS = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))
REPORT = (ARTIFACTS / "report.md").read_text(encoding="utf-8")


def test_helper_counts_and_persistence_on_mixed_fixture():
    # A: decision-point WITH prior (excluded). B, C: usable mid-contract. D: mid-contract missing
    # prior (counted, not usable). E: decision-point missing prior (excluded).
    y_true = np.array([0.20, 0.18, 0.20, 0.30, 0.05])
    prior = np.array([0.10, 0.15, 0.25, np.nan, np.nan])
    decision_point = np.array([True, False, False, False, True])

    result = midcontract_persistence_reference(y_true, prior, decision_point)

    assert result["n_midcontract"] == 3
    assert result["n_midcontract_with_prior"] == 2
    # MAE over B, C: mean(|0.18-0.15|, |0.20-0.25|) = 0.04 -> 4.0% of cap
    assert result["persistence_mae_pct"] == 4.0


def test_decision_point_row_with_prior_never_counts_as_midcontract():
    # The exact bug: a decision-point row carrying a prior salary must not inflate the mid-contract
    # population or bias the persistence MAE.
    y_true = np.array([0.20, 0.18])
    prior = np.array([0.10, 0.15])
    decision_point = np.array([True, False])

    result = midcontract_persistence_reference(y_true, prior, decision_point)

    assert result["n_midcontract"] == 1
    assert result["n_midcontract_with_prior"] == 1
    assert result["persistence_mae_pct"] == round(abs(0.18 - 0.15) * 100, 3)


def test_no_usable_prior_yields_null_mae():
    y_true = np.array([0.20, 0.30])
    prior = np.array([np.nan, np.nan])
    decision_point = np.array([False, False])

    result = midcontract_persistence_reference(y_true, prior, decision_point)

    assert result["n_midcontract"] == 2
    assert result["n_midcontract_with_prior"] == 0
    assert result["persistence_mae_pct"] is None


def test_committed_top_level_agrees_with_segment_population():
    # The top-level mid-contract metric must track segments.mid_contract so the two denominators
    # cannot drift apart again.
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
