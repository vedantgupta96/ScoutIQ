"""Unit tests for the offline rationale-coverage classifier."""
from scoutiq.etl.check_rationale_coverage import _classify


def test_classify_ready_needs_both_signals():
    assert _classify(has_scout=True, has_val=True) == "ready"


def test_classify_load_managed_is_scouted_without_valuation():
    assert _classify(has_scout=True, has_val=False) == "load_managed"


def test_classify_no_scout_coverage_is_valued_without_scouting():
    assert _classify(has_scout=False, has_val=True) == "no_scout_coverage"


def test_classify_no_coverage_when_neither_signal_present():
    assert _classify(has_scout=False, has_val=False) == "no_coverage"
