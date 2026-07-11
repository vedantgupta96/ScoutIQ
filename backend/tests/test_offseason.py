import pytest
from pydantic import ValidationError

from scoutiq.api.cap_simulator import ContractYear, SeasonCapData
from scoutiq.api.main import app
from scoutiq.api.offseason import PlannedContract, apply_plan
from scoutiq.api.routers import offseason as offseason_router
from scoutiq.api.routers.offseason import OffseasonPlanRequest, ProposedContractRequest
from scoutiq.model.roster_fit import build_fit_context
from scoutiq.models import Player, Team


CAPS = [
    SeasonCapData("2026-27", 100, 120, 130, 140),
    SeasonCapData("2027-28", 105, 125, 135, 145, is_projected=True),
]


def _year(season: str, cap_hit: int) -> ContractYear:
    cap = next(row for row in CAPS if row.season == season)
    return ContractYear(
        season=season,
        cap_hit_usd=cap_hit,
        cap_hit_pct=round(cap_hit / cap.salary_cap * 100, 2),
        is_guaranteed=True,
        is_player_option=False,
        is_team_option=False,
        salary_cap=cap.salary_cap,
        tax_line=cap.tax_line,
        first_apron=cap.first_apron,
        second_apron=cap.second_apron,
        is_projected_cap=cap.is_projected,
    )


def test_apply_plan_replaces_existing_hit_and_tracks_apron_change():
    baseline = {
        "2026-27": {1: 80, 2: 30},
        "2027-28": {1: 75, 2: 25},
    }
    contracts = [
        PlannedContract(
            player_id=2,
            years=[_year("2026-27", 55), _year("2027-28", 55)],
        )
    ]

    result = apply_plan(CAPS, baseline, contracts, set())

    assert result[0].baseline_payroll_usd == 110
    assert result[0].payroll_after_usd == 135  # 80 + 55, not 80 + 30 + 55
    assert result[0].payroll_delta_usd == 25
    assert result[0].baseline_roster_count == result[0].roster_count_after == 2
    assert result[0].tier_before == "below-tax"
    assert result[0].tier_after == "first-apron"
    assert result[0].crosses_a_line is True
    assert result[1].is_projected_cap is True


def test_apply_plan_removes_option_player_across_horizon():
    baseline = {
        "2026-27": {1: 80, 2: 30},
        "2027-28": {1: 75, 2: 25},
    }

    result = apply_plan(CAPS, baseline, [], {2})

    assert [row.payroll_after_usd for row in result] == [80, 75]
    assert [row.roster_count_after for row in result] == [1, 1]
    assert result[0].room_to_cap_after == 20


def test_plan_request_rejects_conflicting_moves_and_short_horizon():
    contract = ProposedContractRequest(player_id=7, aav_pct=20, years=4)

    with pytest.raises(ValidationError, match="both a proposed contract and an option decline"):
        OffseasonPlanRequest(
            team_id=1,
            start_season="2026-27",
            horizon=4,
            contracts=[contract],
            option_declines=[7],
        )

    with pytest.raises(ValidationError, match="cannot exceed the plan horizon"):
        OffseasonPlanRequest(
            team_id=1,
            start_season="2026-27",
            horizon=3,
            contracts=[contract],
        )


def test_offseason_plan_route_is_registered():
    assert "/offseason/plan" in app.openapi()["paths"]


def test_build_offseason_plan_prices_proposed_signing(monkeypatch):
    team = Team(team_id=1, abbreviation="TST", name="Test Team")
    roster_player = Player(player_id=10, full_name="Roster Player", current_team_id=1)
    target = Player(player_id=20, full_name="Target Player", current_team_id=2)

    class ScalarResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeDB:
        def get(self, model, key):
            return team if model is Team and key == team.team_id else None

        def scalars(self, statement):
            sql = str(statement)
            if "WHERE players.current_team_id" in sql:
                return ScalarResult([roster_player])
            return ScalarResult([target])

    monkeypatch.setattr(
        offseason_router,
        "_season_caps",
        lambda db: {cap.season: cap for cap in CAPS},
    )
    monkeypatch.setattr(
        offseason_router,
        "team_cap_hits",
        lambda db, ids, season: ({10: 110 if season == "2026-27" else 100}, {10: "contract"}),
    )
    monkeypatch.setattr(
        offseason_router,
        "_valuations",
        lambda db, players, season: {20: {"value_pct": 25.0, "lo_pct": 20.0, "hi_pct": 30.0}},
    )
    monkeypatch.setattr(
        offseason_router,
        "load_fit_context",
        lambda db, season: build_fit_context([]),
    )

    response = offseason_router.build_offseason_plan(
        OffseasonPlanRequest(
            team_id=1,
            start_season="2026-27",
            horizon=2,
            contracts=[ProposedContractRequest(player_id=20, aav_pct=20, years=2)],
        ),
        FakeDB(),
    )

    assert response.moves[0].kind == "signing"
    assert response.moves[0].value_gap_pct == 5.0
    assert response.seasons[0].baseline_payroll_usd == 110
    assert response.seasons[0].payroll_after_usd == 130
    assert response.seasons[0].tier_after == "first-apron"
    assert response.needs_before.roster_player_count == 1
    assert response.needs_after.roster_player_count == 2
