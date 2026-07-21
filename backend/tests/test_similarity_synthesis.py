"""Tests for the comp-synthesis pure logic in scoutiq.model.similarity."""
from scoutiq.model.similarity import synthesize_comps


def test_fewer_than_three_returns_none():
    assert synthesize_comps([10.0, 12.0], 11.0) is None
    assert synthesize_comps([], 11.0) is None
    assert synthesize_comps([-5.0, 10.0], 11.0) is None


def test_exactly_three_uses_min_max_band():
    result = synthesize_comps([8.0, 10.0, 14.0], 10.0)

    assert result.n_comps == 3
    assert result.market_low_pct == 8.0
    assert result.market_high_pct == 14.0
    assert result.market_median_pct == 10.0


def test_four_or_more_uses_percentile_band():
    # sorted: [8, 10, 12, 20] -> 25th pct idx=0.75 -> 8 + 0.75*(10-8) = 9.5
    # 75th pct idx=2.25 -> 12 + 0.25*(20-12) = 14.0
    result = synthesize_comps([20.0, 8.0, 12.0, 10.0], 12.0)

    assert result.n_comps == 4
    assert result.market_low_pct == 9.5
    assert result.market_high_pct == 14.0
    assert result.market_median_pct == 11.0


def test_model_value_below_band_clamps_up_to_low():
    result = synthesize_comps([8.0, 10.0, 14.0], 2.0)

    assert result.suggested_pct == result.market_low_pct == 8.0


def test_model_value_above_band_clamps_down_to_high():
    result = synthesize_comps([8.0, 10.0, 14.0], 30.0)

    assert result.suggested_pct == result.market_high_pct == 14.0


def test_model_value_inside_band_suggested_equals_model_value():
    result = synthesize_comps([8.0, 10.0, 14.0], 11.0)

    assert result.suggested_pct == 11.0


def test_model_value_none_suggested_equals_median():
    result = synthesize_comps([8.0, 10.0, 14.0], None)

    assert result.model_value_pct is None
    assert result.suggested_pct == result.market_median_pct == 10.0
