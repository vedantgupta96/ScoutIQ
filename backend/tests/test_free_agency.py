"""Tests for the free-agency logic module and router.

Pure season/verdict logic is tested directly. The endpoints are tested with the router's
DB-touching helpers monkeypatched — the SQL assembly itself is exercised end-to-end against a
live DB in the smoke script, so these focus on response shaping, sorting, verdict wiring, and
the projected-room / fits-room math.
"""
import scoutiq.api.routers.free_agency as far
from fastapi.testclient import TestClient

from scoutiq.api import free_agency as fa
from scoutiq.api.cap_simulator import SeasonCapData
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.api import rosters
from scoutiq.api.rosters import PlayerSummary
from fakes import FakeScalarResult
from scoutiq.api.valuation import Valuation
from scoutiq.model.roster_fit import CandidateFit
from scoutiq.models import ContractYear, FreeAgentRight, Player, PlayerSeason, Team

LAL_ID = 1610612747


# --------------------------------------------------------------------------- pure logic
def test_expiry_and_entering_season():
    # prev_season now lives in scoutiq.api.season and is covered by test_season.py.
    assert fa.expiry_season("2024-25", 4) == "2027-28"
    assert fa.expiry_season("2025-26", 1) == "2025-26"
    assert fa.expiry_season("2025-26", 0) is None
    assert fa.entering_season("2027-28") == "2028-29"


def test_free_agent_type_and_rfa_estimate():
    assert fa.free_agent_type(True, False) == fa.FA_PLAYER_OPTION
    assert fa.free_agent_type(False, True) == fa.FA_TEAM_OPTION
    assert fa.free_agent_type(False, False) == fa.FA_EXPIRING
    assert fa.rfa_estimate(2) is True
    assert fa.rfa_estimate(4) is False


def test_option_decision_player_option_directions():
    # worth more than the option → decline and test the market
    v = fa.option_decision(30.0, 20.0, fa.FA_PLAYER_OPTION)
    assert v.deciding_party == "player" and v.verdict == "Decline (opt out)" and v.tone == "positive"
    assert v.gap_pct == 10.0
    # worth less → opt in for the guaranteed money
    v = fa.option_decision(10.0, 25.0, fa.FA_PLAYER_OPTION)
    assert v.verdict == "Opt in" and v.tone == "negative"
    # within a cap-point → toss-up
    v = fa.option_decision(20.4, 20.0, fa.FA_PLAYER_OPTION)
    assert v.tone == "neutral" and "Toss-up" in v.verdict


def test_option_decision_team_option_directions():
    v = fa.option_decision(30.0, 20.0, fa.FA_TEAM_OPTION)
    assert v.deciding_party == "team" and v.verdict == "Exercise" and v.tone == "positive"
    v = fa.option_decision(10.0, 25.0, fa.FA_TEAM_OPTION)
    assert v.verdict == "Decline" and v.tone == "negative"


def test_option_decision_handles_missing_value():
    v = fa.option_decision(None, 20.0, fa.FA_TEAM_OPTION)
    assert v.verdict == "No model value" and v.tone == "neutral" and v.gap_pct is None


# --------------------------------------------------------------------------- endpoint fixtures
def _summary(player_id: int, name: str, position: str) -> PlayerSummary:
    return PlayerSummary(
        player_id=player_id, full_name=name, position=position, latest_season="2025-26",
        latest_stats_team=None, current_team=None, current_team_source=None, team_data_note=None,
    )


def _pool_entry(player_id, name, position, fa_type, last_season, *, cap_pct, aav, seasons_played, age):
    return far._PoolEntry(
        player=Player(player_id=player_id, full_name=name, position=position),
        last_year=ContractYear(contract_id=player_id, season=last_season, aav=aav, cap_pct=cap_pct,
                               is_player_option=(fa_type == fa.FA_PLAYER_OPTION),
                               is_team_option=(fa_type == fa.FA_TEAM_OPTION)),
        expiring_season=last_season,
        entering_season="2026-27",
        fa_type=fa_type,
        seasons_played=seasons_played,
        latest_season_row=PlayerSeason(player_id=player_id, season="2025-26", age=age),
    )


CAPS = {
    "2025-26": SeasonCapData("2025-26", 154_647_000, 187_895_000, 195_945_000, 207_824_000),
    "2026-27": SeasonCapData("2026-27", 161_606_000, 196_350_000, 204_762_000, 217_176_000),
}

# Expiring veteran (UFA), then a rising player option — B outvalues A to test sorting.
POOL = [
    _pool_entry(100, "Expiring Vet", "SF", fa.FA_EXPIRING, "2025-26",
                cap_pct=None, aav=40_000_000, seasons_played=8, age=31),
    _pool_entry(200, "Option Kid", "PG", fa.FA_PLAYER_OPTION, "2026-27",
                cap_pct=0.10, aav=16_000_000, seasons_played=2, age=23),
]
SUMMARIES = {100: _summary(100, "Expiring Vet", "SF"), 200: _summary(200, "Option Kid", "PG")}
def _pred(value_pct, lo_pct, hi_pct):
    return Valuation(
        season="2025-26", value_pct=value_pct, lo_pct=lo_pct, hi_pct=hi_pct,
        actual_usd=None, actual_pct=None, gap_pct=None, salary_cap=None, value_usd=None,
        model_version="test", verdict_label="", verdict_tone="neutral",
        caution_flags=[], caveat=None, stats=None,
    )


PREDS = {
    100: _pred(15.0, 11.0, 19.0),
    200: _pred(18.0, 14.0, 22.0),
}


def _patch_common(monkeypatch, pool=POOL):
    monkeypatch.setattr(far, "_assemble_pool", lambda db, entering, **kw: list(pool))
    monkeypatch.setattr(far, "load_season_caps", lambda db: dict(CAPS))
    monkeypatch.setattr(rosters, "batched_summaries", lambda players, db: dict(SUMMARIES))
    # value by player_id so filtering (e.g. options-only) can't misalign predictions
    monkeypatch.setattr(
        far, "_value_pool",
        lambda db, pool: {e.player.player_id: PREDS[e.player.player_id]
                      for e in pool if e.latest_season_row is not None},
    )


class _FakeDB:
    def __init__(self, *, team=None, roster=(), rights=(), rights_teams=()):
        self._team = team
        self._roster = list(roster)
        self._rights = list(rights)
        self._rights_teams = list(rights_teams)

    def get(self, model, key):
        return self._team if (model is Team and self._team and key == self._team.team_id) else None

    def scalars(self, stmt):
        sql = str(stmt)
        if "FROM free_agent_rights" in sql:
            return FakeScalarResult(self._rights)
        if "FROM teams" in sql:
            return FakeScalarResult(self._rights_teams)
        return FakeScalarResult(self._roster if "current_team_id" in sql else [])


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- board
def test_board_ranks_by_value_and_flags_rfa(monkeypatch):
    _patch_common(monkeypatch)
    body = _client(_FakeDB()).get("/free-agency/board", params={"season": "2026-27"}).json()

    assert body["entering_season"] == "2026-27"
    assert body["total"] == 2
    names = [it["full_name"] for it in body["items"]]
    assert names == ["Option Kid", "Expiring Vet"]  # 18% before 15%

    by_name = {it["full_name"]: it for it in body["items"]}
    assert by_name["Option Kid"]["fa_type"] == "player-option"
    assert by_name["Option Kid"]["rfa_estimate"] is True      # 2 seasons
    assert by_name["Expiring Vet"]["fa_type"] == "expiring"
    assert by_name["Expiring Vet"]["rfa_estimate"] is False   # 8 seasons
    # expiring cap % derived from AAV / expiry-season cap; value_usd applied at entering cap
    assert by_name["Expiring Vet"]["expiring_cap_pct"] == round(40_000_000 / 154_647_000 * 100, 2)
    assert by_name["Option Kid"]["value_usd"] == round(0.18 * 161_606_000)
    assert body["items"][0]["option"] is None  # board omits the verdict block


def test_board_prefers_persisted_status_and_exposes_rights(monkeypatch):
    _patch_common(monkeypatch)
    rights_team = Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")
    right = FreeAgentRight(
        player_id=100,
        entering_season="2026-27",
        rights_team_id=LAL_ID,
        fa_status="rfa",
        bird_rights="early-bird",
        cap_hold_usd=18_500_000,
        qualifying_offer_usd=7_000_000,
        source="spotrac",
    )
    body = _client(
        _FakeDB(rights=[right], rights_teams=[rights_team])
    ).get("/free-agency/board", params={"season": "2026-27"}).json()

    veteran = next(item for item in body["items"] if item["player_id"] == 100)
    assert veteran["rfa_estimate"] is False
    assert veteran["fa_status"] == "rfa"
    assert veteran["fa_status_source"] == "spotrac"
    assert veteran["rights_team"]["abbreviation"] == "LAL"
    assert veteran["bird_rights"] == "early-bird"
    assert veteran["cap_hold_usd"] == 18_500_000
    assert veteran["qualifying_offer_usd"] == 7_000_000


def test_board_rejects_bad_season(monkeypatch):
    _patch_common(monkeypatch)
    resp = _client(_FakeDB()).get("/free-agency/board", params={"season": "20xx"})
    assert resp.status_code == 422


def test_board_rejects_bad_type(monkeypatch):
    _patch_common(monkeypatch)
    resp = _client(_FakeDB()).get("/free-agency/board", params={"type": "waived"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- options
def test_options_attaches_verdict(monkeypatch):
    _patch_common(monkeypatch)
    body = _client(_FakeDB()).get("/free-agency/options", params={"season": "2026-27"}).json()

    # only the option year survives; the straight-expiring vet is filtered out
    assert body["total"] == 1
    kid = body["items"][0]
    assert kid["full_name"] == "Option Kid"
    opt = kid["option"]
    # value 18% vs option 10% → player worth more → decline
    assert opt["deciding_party"] == "player"
    assert opt["verdict"] == "Decline (opt out)"
    assert opt["gap_pct"] == 8.0


# --------------------------------------------------------------------------- team targets
def test_team_targets_room_and_fit(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(rosters, "team_cap_hits", lambda db, ids, season: ({1: 50_000_000, 2: 30_000_000}, {}))
    team = Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")
    fake = _FakeDB(team=team, roster=[Player(player_id=1, current_team_id=LAL_ID)])

    body = _client(fake).get(f"/free-agency/teams/{LAL_ID}/targets", params={"season": "2026-27"}).json()

    assert body["team"]["abbreviation"] == "LAL"
    ctx = body["cap_context"]
    assert ctx["contract_payroll_usd"] == 80_000_000
    assert ctx["incomplete_roster_spots"] == 10
    assert ctx["committed_payroll_usd"] > 80_000_000
    assert ctx["room_to_cap"] == 161_606_000 - ctx["committed_payroll_usd"]
    # both targets' model value is well under the ~$81M of room → both fit
    assert all(t["fits_room"] is True for t in body["targets"])
    assert body["committed_player_count"] == 2
    assert body["needs"]["roster_player_count"] == 2


def test_team_targets_include_hold_without_double_counting_contracted_player(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        rosters,
        "team_cap_hits",
        lambda db, ids, season: ({1: 50_000_000, 2: 30_000_000}, {}),
    )
    team = Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")
    rights = [
        FreeAgentRight(
            player_id=1,
            entering_season="2026-27",
            rights_team_id=LAL_ID,
            cap_hold_usd=20_000_000,
        ),
        FreeAgentRight(
            player_id=99,
            entering_season="2026-27",
            rights_team_id=LAL_ID,
            cap_hold_usd=10_000_000,
        ),
    ]
    fake = _FakeDB(
        team=team,
        roster=[Player(player_id=1, current_team_id=LAL_ID)],
        rights=rights,
    )

    body = _client(fake).get(
        f"/free-agency/teams/{LAL_ID}/targets",
        params={"season": "2026-27"},
    ).json()

    context = body["cap_context"]
    assert context["contract_payroll_usd"] == 80_000_000
    assert context["cap_holds_usd"] == 10_000_000
    assert context["incomplete_roster_spots"] == 9


def test_team_targets_fit_sort_and_staged_roster_overrides(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        rosters,
        "team_cap_hits",
        lambda db, ids, season: ({1: 50_000_000, 2: 30_000_000}, {}),
    )
    monkeypatch.setattr(
        far,
        "score_candidate",
        lambda context, roster, player_id: CandidateFit(
            player_id=player_id,
            fit_score=90.0 if player_id == 100 else 10.0,
            confidence="medium",
            fills=[],
            reasons=["fixture"],
        ),
    )
    team = Team(team_id=LAL_ID, abbreviation="LAL", name="Los Angeles Lakers")
    fake = _FakeDB(team=team, roster=[Player(player_id=1, current_team_id=LAL_ID)])

    body = _client(fake).get(
        f"/free-agency/teams/{LAL_ID}/targets",
        params={"season": "2026-27", "sort": "fit", "add": "200", "remove": "1"},
    ).json()

    assert [target["player_id"] for target in body["targets"]] == [100]
    assert body["targets"][0]["fit"]["fit_score"] == 90.0
    assert body["needs"]["roster_player_count"] == 2  # {2, 200}


def test_team_targets_unknown_team_404(monkeypatch):
    _patch_common(monkeypatch)
    resp = _client(_FakeDB(team=None)).get(f"/free-agency/teams/{LAL_ID}/targets")
    assert resp.status_code == 404


class _EmptyDB:
    """All queries come back empty — exercises the real pool assembly, not a mock."""

    def scalars(self, stmt):
        return FakeScalarResult([])

    def execute(self, stmt):
        return FakeScalarResult([])

    def get(self, model, key):
        return None


def test_board_runs_real_pool_assembly_without_mocks(monkeypatch):
    """Regression: #77 removed free_agency.prev_season while the router still called
    fa.prev_season — every FA endpoint 500'd, unseen because tests mocked _assemble_pool."""
    monkeypatch.setattr(far, "load_season_caps", lambda db: dict(CAPS))

    response = _client(_EmptyDB()).get("/free-agency/board", params={"season": "2026-27"})

    assert response.status_code == 200
    assert response.json()["items"] == []
