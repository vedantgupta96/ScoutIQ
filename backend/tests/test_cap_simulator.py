import pytest

from scoutiq.api.cap_simulator import (
    SeasonCapData,
    apron_outlook,
    build_season_sequence,
    classify_tier,
    simulate,
)


def _cap_data():
    return SeasonCapData(
        season="2025-26",
        salary_cap=154_647_000,
        tax_line=187_895_000,
        first_apron=195_945_000,
        second_apron=207_824_000,
    )


def _caps():
    return {
        "2024-25": SeasonCapData(
            season="2024-25",
            salary_cap=100_000_000,
            tax_line=120_000_000,
            first_apron=130_000_000,
            second_apron=140_000_000,
        )
    }


def test_season_sequence_flags_projected_future_caps():
    seasons = build_season_sequence("2024-25", 2, _caps())

    assert seasons[0].season == "2024-25"
    assert seasons[0].salary_cap == 100_000_000
    assert seasons[0].is_projected is False
    assert seasons[1].season == "2025-26"
    assert seasons[1].salary_cap == 104_500_000
    assert seasons[1].is_projected is True


def test_simulate_infers_guaranteed_non_option_years():
    result = simulate(
        player_id=1,
        player_name="Desmond Bane",
        aav_pct=20.0,
        years=4,
        guaranteed_years=None,
        player_option_years=1,
        team_option_years=1,
        start_season="2024-25",
        cap_by_season=_caps(),
    )

    assert [y.is_guaranteed for y in result.years] == [True, True, False, False]
    assert [y.is_player_option for y in result.years] == [False, False, True, False]
    assert [y.is_team_option for y in result.years] == [False, False, False, True]
    assert result.assumptions["standalone_contract_only"] is True


def test_simulate_rejects_too_many_option_and_guarantee_years():
    with pytest.raises(ValueError):
        simulate(
            player_id=1,
            player_name="Desmond Bane",
            aav_pct=20.0,
            years=2,
            guaranteed_years=2,
            player_option_years=1,
            team_option_years=0,
            start_season="2024-25",
            cap_by_season=_caps(),
        )


def test_simulate_calculates_valuation_gap_and_interval():
    result = simulate(
        player_id=1,
        player_name="Desmond Bane",
        aav_pct=20.0,
        years=1,
        guaranteed_years=None,
        player_option_years=0,
        team_option_years=0,
        start_season="2024-25",
        cap_by_season=_caps(),
        valuation={
            "value_pct": 23.5,
            "lo_pct": 18.1,
            "hi_pct": 28.9,
            "model_version": "v0-gbm-conformal",
        },
    )

    assert result.proposed_aav_usd == 20_000_000
    assert result.value_usd == 23_500_000
    assert result.value_gap_pct == 3.5
    assert result.lo_pct == 18.1
    assert result.hi_pct == 28.9
    assert result.model_version == "v0-gbm-conformal"


def test_classify_tier_buckets_each_band():
    cap = _cap_data()
    bands = (cap.tax_line, cap.first_apron, cap.second_apron)
    assert classify_tier(100_000_000, *bands) == "below-tax"
    assert classify_tier(cap.tax_line, *bands) == "taxpayer"
    assert classify_tier(cap.first_apron, *bands) == "first-apron"
    assert classify_tier(cap.second_apron + 1, *bands) == "second-apron"


def test_classify_tier_ignores_unknown_thresholds():
    # Pre-CBA seasons can have null apron lines; payroll should fall back to below-tax.
    assert classify_tier(300_000_000, None, None, None) == "below-tax"


def test_apron_outlook_overlay_crosses_into_first_apron():
    cap = _cap_data()
    # Team is a taxpayer just under the first apron; a $12M deal pushes it over (but
    # stays under the second apron at 207.8M).
    outlook = apron_outlook(
        team_id=1610612763,
        team_name="Memphis Grizzlies",
        season="2025-26",
        existing_payroll_usd=190_000_000,
        replaces_existing_usd=0,
        proposed_cap_hit_usd=12_000_000,
        cap_data=cap,
    )

    assert outlook.tier_before == "taxpayer"
    assert outlook.tier_after == "first-apron"
    assert outlook.crosses_a_line is True
    assert outlook.payroll_after_usd == 202_000_000
    assert outlook.room_to_first_apron_after == cap.first_apron - 202_000_000  # negative = over
    assert any("Hard-capped at the first apron" in c for c in outlook.consequences)


def test_apron_outlook_nets_out_existing_salary_on_resign():
    cap = _cap_data()
    # Re-signing: the player's current $30M figure is replaced, not stacked on top.
    outlook = apron_outlook(
        team_id=1610612763,
        team_name="Memphis Grizzlies",
        season="2025-26",
        existing_payroll_usd=190_000_000,
        replaces_existing_usd=30_000_000,
        proposed_cap_hit_usd=35_000_000,
        cap_data=cap,
    )

    # 190M - 30M (old) + 35M (new) = 195M, still a hair under the first apron.
    assert outlook.payroll_after_usd == 195_000_000
    assert outlook.tier_after == "taxpayer"
    assert outlook.crosses_a_line is False
