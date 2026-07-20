"""Unit tests for the Trade Lab balance layer (fairness meter + per-side grade).

Covers docs/08 Phase 1: even trades read even with mirror grades, lopsided trades
point to the right side and grade the loser down, low model coverage widens the even
band and flags low confidence, and the needle stays monotonic in the differential."""
from scoutiq.api.trade_assets import (
    FAIRNESS_LOPSIDED_PCT_OF_CAP,
    trade_balance,
)

CAP = 160_000_000


def _balance(a_in, a_out, b_in, b_out, *, valued=4, selected=4):
    """Symmetric, fully-valued call by default (coverage kept high)."""
    return trade_balance(
        a_value_in_usd=a_in, a_value_out_usd=a_out,
        b_value_in_usd=b_in, b_value_out_usd=b_out,
        salary_cap=CAP,
        a_valued=valued, a_selected=selected,
        b_valued=valued, b_selected=selected,
    )


def test_even_trade_is_even_with_mirror_grades():
    # Both sides net roughly zero.
    b = _balance(10_000_000, 10_000_000, 10_000_000, 10_000_000)
    assert b.fairness_tier == "even"
    assert b.fairness_pct == 50.0
    assert b.net_usd == 0
    assert b.team_a_grade == b.team_b_grade == "C"
    assert b.low_confidence is False


def test_lopsided_toward_a_grades_b_down_and_points_left_of_center():
    # A gains +$16M (10% of cap) net, B loses the same.
    b = _balance(20_000_000, 4_000_000, 4_000_000, 20_000_000)
    assert b.fairness_tier == "lopsided-a"
    assert b.net_usd == 16_000_000
    assert b.fairness_pct == 100.0            # beyond the lopsided band, clamped
    assert b.team_a_grade == "A"
    assert b.team_b_grade == "F"
    assert "Team A" in b.fairness_label


def test_favors_b_is_within_lopsided_band():
    # B nets +$6M (3.75% of cap): past even, short of lopsided.
    b = _balance(2_000_000, 8_000_000, 8_000_000, 2_000_000)
    assert b.fairness_tier == "favors-b"
    assert b.net_usd == -6_000_000
    assert b.fairness_pct < 50.0
    assert b.team_b_grade in {"A", "B"} and b.team_a_grade in {"D", "F"}


def test_needle_is_monotonic_in_differential():
    small = _balance(11_000_000, 10_000_000, 10_000_000, 11_000_000)   # A +1M
    big = _balance(15_000_000, 10_000_000, 10_000_000, 15_000_000)     # A +5M
    assert big.fairness_pct > small.fairness_pct >= 50.0


def test_low_coverage_widens_even_band_and_flags_confidence():
    # A nets +$5M (3.125% of cap) — normally "favors-a" — but only 1 of 4 players valued.
    b = _balance(15_000_000, 10_000_000, 10_000_000, 15_000_000, valued=1, selected=4)
    assert b.low_confidence is True
    assert b.fairness_tier == "even"          # widened band swallows a marginal edge
    assert any("low confidence" in r for r in b.reasons)


def test_no_selection_is_low_confidence_even():
    b = _balance(0, 0, 0, 0, valued=0, selected=0)
    assert b.low_confidence is True
    assert b.fairness_tier == "even"
    assert b.net_usd == 0


def test_lopsided_threshold_boundary_is_exact():
    # Exactly the lopsided % of cap should read favors, not lopsided (strict >).
    edge = int(FAIRNESS_LOPSIDED_PCT_OF_CAP / 100 * CAP)   # 8% of cap
    b = _balance(10_000_000 + edge, 10_000_000, 10_000_000, 10_000_000 + edge)
    assert b.fairness_tier == "favors-a"
    assert b.fairness_pct == 100.0


def test_coverage_is_reported_per_side():
    b = _balance(12_000_000, 10_000_000, 10_000_000, 12_000_000, valued=3, selected=4)
    assert b.coverage == {"a_valued": 3, "a_selected": 4, "b_valued": 3, "b_selected": 4}
