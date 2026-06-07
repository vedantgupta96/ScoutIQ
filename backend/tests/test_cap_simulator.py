import pytest

from scoutiq.api.cap_simulator import SeasonCapData, build_season_sequence, simulate


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
