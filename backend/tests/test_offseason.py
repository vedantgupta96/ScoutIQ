import pytest
from pydantic import ValidationError

from scoutiq.api.cap_simulator import ContractYear, SeasonCapData
from scoutiq.api.main import app
from scoutiq.api.offseason import PlannedContract, apply_plan, incomplete_roster_charge, zero_year_minimum
from scoutiq.api.routers import offseason as offseason_router
from scoutiq.api.routers.offseason import OffseasonPlanRequest, ProposedContractRequest
from scoutiq.api.valuation import Valuation
from scoutiq.model.roster_fit import build_fit_context
from scoutiq.models import FreeAgentRight, Player, Team


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

    assert result[0].baseline_payroll_usd == 120  # includes ten minimum-roster charges
    assert result[0].payroll_after_usd == 145  # 80 + 55 + ten minimum-roster charges
    assert result[0].payroll_delta_usd == 25
    assert result[0].baseline_roster_count == result[0].roster_count_after == 2
    assert result[0].tier_before == "taxpayer"
    assert result[0].tier_after == "second-apron"
    assert result[0].crosses_a_line is True
    assert result[1].is_projected_cap is True


def test_apply_plan_removes_option_player_across_horizon():
    baseline = {
        "2026-27": {1: 80, 2: 30},
        "2027-28": {1: 75, 2: 25},
    }

    result = apply_plan(CAPS, baseline, [], {2})

    assert [row.payroll_after_usd for row in result] == [91, 86]
    assert [row.roster_count_after for row in result] == [1, 1]
    assert result[0].room_to_cap_after == 9


def test_zero_year_minimum_and_incomplete_roster_charge():
    assert zero_year_minimum(140_588_000) == 1_157_153
    assert zero_year_minimum(154_647_000) == 1_272_870
    assert incomplete_roster_charge(154_647_000, 12) == (0, 0)
    assert incomplete_roster_charge(154_647_000, 10) == (2_545_740, 2)


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

    with pytest.raises(ValidationError, match="proposed contract and renounced rights"):
        OffseasonPlanRequest(
            team_id=1,
            start_season="2026-27",
            contracts=[contract],
            renounced_rights=[7],
        )


def test_apply_plan_renounces_hold_and_adds_missing_slot_charge():
    caps = [SeasonCapData("2025-26", 154_647_000, 180_000_000, 190_000_000, 200_000_000)]
    baseline = {"2025-26": {pid: 1_000_000 for pid in range(1, 12)}}
    result = apply_plan(caps, baseline, [], set(), {"2025-26": {20: 8_000_000}}, {20})[0]
    assert result.baseline_cap_holds_usd == 8_000_000
    assert result.baseline_incomplete_roster_charges_usd == 0
    assert result.cap_holds_after_usd == 0
    assert result.incomplete_roster_charges_after_usd == 1_272_870
    assert result.baseline_roster_count == result.roster_count_after == 11


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
            if "FROM free_agent_rights" in sql:
                return ScalarResult([])
            if "WHERE players.current_team_id" in sql:
                return ScalarResult([roster_player])
            return ScalarResult([target])

    monkeypatch.setattr(
        offseason_router,
        "load_season_caps",
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
        lambda db, players, season: {
            20: Valuation(
                season=season, value_pct=25.0, lo_pct=20.0, hi_pct=30.0,
                actual_usd=None, actual_pct=None, gap_pct=None, salary_cap=None, value_usd=None,
                model_version="test", verdict_label="", verdict_tone="neutral",
                caution_flags=[], caveat=None, stats=None,
            )
        },
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
    assert response.seasons[0].baseline_payroll_usd == 121
    assert response.seasons[0].payroll_after_usd == 140
    assert response.seasons[0].tier_after == "second-apron"
    assert response.needs_before.roster_player_count == 1
    assert response.needs_after.roster_player_count == 2


def test_plan_batches_horizon_holds_and_resigning_replaces_hold(monkeypatch):
    team = Team(team_id=1, abbreviation="TST", name="Test Team")
    rights_player = Player(player_id=20, full_name="Rights Player", current_team_id=2)
    rights = [
        FreeAgentRight(
            player_id=20,
            entering_season="2026-27",
            rights_team_id=1,
            fa_status="rfa",
            bird_rights="bird",
            cap_hold_usd=30,
            source="spotrac",
        ),
        FreeAgentRight(
            player_id=20,
            entering_season="2027-28",
            rights_team_id=1,
            fa_status="ufa",
            bird_rights="bird",
            cap_hold_usd=40,
            source="spotrac",
        ),
    ]

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
            if "FROM free_agent_rights" in sql:
                return ScalarResult(rights)
            if "WHERE players.current_team_id" in sql:
                return ScalarResult([])
            if "FROM players" in sql:
                return ScalarResult([rights_player])
            return ScalarResult([])

    monkeypatch.setattr(
        offseason_router,
        "load_season_caps",
        lambda db: {cap.season: cap for cap in CAPS},
    )
    monkeypatch.setattr(
        offseason_router,
        "team_cap_hits",
        lambda db, ids, season: ({}, {}),
    )
    monkeypatch.setattr(
        offseason_router,
        "_valuations",
        lambda db, players, season: {},
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
            contracts=[
                ProposedContractRequest(player_id=20, aav_pct=20, years=2)
            ],
        ),
        FakeDB(),
    )

    assert response.moves[0].kind == "re-sign"
    assert [season.baseline_cap_holds_usd for season in response.seasons] == [30, 40]
    assert [season.cap_holds_after_usd for season in response.seasons] == [0, 0]
    assert [season.contract_payroll_after_usd for season in response.seasons] == [20, 21]
    assert [right.player_id for right in response.rights] == [20]
    assert response.rights[0].retained is False
