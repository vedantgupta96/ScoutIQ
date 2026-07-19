"""End-to-end /trades/analyze scenarios with draft picks: legality escalation,
ownership enforcement, and asset-ledger consistency (mirrors the live verification
battery recorded in docs/06)."""
import pytest
from fastapi.testclient import TestClient

from scoutiq.api.cap_simulator import SeasonCapData
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.api.routers import trades as trades_router
from scoutiq.model.roster_fit import build_fit_context
from scoutiq.models import DraftPick, Team

from tests.test_trades import _workspace


class FakePicksDB:
    """Session fake serving draft_picks queries; contracts/valuations degrade to empty."""

    def __init__(self, picks: list[DraftPick], teams: list[Team]):
        self.picks = picks
        self.teams = {t.team_id: t for t in teams}

    class _Result:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

        def first(self):
            return self.values[0] if self.values else None

    def get(self, model, key):
        if model is Team:
            return self.teams.get(key)
        return None

    def scalars(self, stmt):
        sql = str(stmt)
        if "min(draft_picks.draft_year)" in sql:
            years = [p.draft_year for p in self.picks]
            return self._Result([min(years)] if years else [])
        if "draft_picks" in sql:
            if "draft_picks.id IN" in sql:
                # analyze fetches the moving picks by id; emulate IN by returning all
                return self._Result(self.picks)
            if "draft_picks.round" in sql:
                return self._Result([p for p in self.picks if p.round == 1])
            return self._Result(self.picks)
        if "FROM teams" in sql:
            return self._Result(list(self.teams.values()))
        return self._Result([])

    def execute(self, stmt):
        return self._Result([])


def _pick(pick_id, year, owner, origin=None, protected_top=None):
    return DraftPick(
        id=pick_id, draft_year=year, round=1,
        original_team_id=origin or owner, current_team_id=owner,
        protected_top=protected_top, swap_rights_team_id=None,
        converts_to=None, source="spotrac",
    )


TEAMS = [Team(team_id=1, abbreviation="AAA", name="Team A"),
         Team(team_id=2, abbreviation="BBB", name="Team B")]

WINDOW = list(range(2027, 2034))


def _roster_workspace(team_id, traded_pid):
    """15-standard-player workspace (roster-valid) whose first player is the traded id."""
    ws = _full_workspace(team_id, standard_count=15, cap_hit=10_000_000)
    ws.players[0].player_id = traded_pid
    return ws


def _analyze(monkeypatch, db, a_picks=None, b_picks=None):
    cap = SeasonCapData("2026-27", 160_000_000, 190_000_000, 200_000_000, 210_000_000,
                        is_projected=True)
    monkeypatch.setattr(trades_router, "load_season_caps", lambda db_: {cap.season: cap})
    monkeypatch.setattr(trades_router, "cap_for", lambda season, caps: cap)
    monkeypatch.setattr(
        trades_router, "_load_trade_workspaces",
        lambda db_, ids, season, **kw: {1: _roster_workspace(1, 10), 2: _roster_workspace(2, 20)},
    )
    monkeypatch.setattr(trades_router, "_selected_values", lambda db_, ids: {})
    monkeypatch.setattr(trades_router, "load_fit_context", lambda db_, season: build_fit_context([]))
    app.dependency_overrides[get_db] = lambda: db
    try:
        return TestClient(app).post("/trades/analyze", json={
            "season": "2026-27", "team_a_id": 1, "team_b_id": 2,
            "team_a_sends": [10], "team_b_sends": [20],
            "team_a_sends_picks": a_picks or [], "team_b_sends_picks": b_picks or [],
        })
    finally:
        app.dependency_overrides.clear()


def test_stepien_fail_escalates_overall_verdict(monkeypatch):
    # Team A owns only 2027 + 2028 firsts; sending 2027 leaves 2028 alone -> gap at 2029/2030? No:
    # sending 2027 leaves {2028}; missing 2029..2033 are consecutive -> fail.
    db = FakePicksDB([_pick(1, 2027, owner=1), _pick(2, 2028, owner=1)], TEAMS)
    response = _analyze(monkeypatch, db, a_picks=[1])

    body = response.json()
    assert body["team_a"]["pick_legality"]["status"] == "fail"
    assert body["overall_status"] == "modeled-noncompliant"
    assert "Stepien" in body["team_a"]["pick_legality"]["reasons"][0]


def test_alternating_firsts_pass_stepien(monkeypatch):
    picks = [_pick(i, year, owner=1) for i, year in enumerate(WINDOW, start=1)]
    db = FakePicksDB(picks, TEAMS)
    # send 2027, 2029, 2031, 2033 -> every other year still covered
    response = _analyze(monkeypatch, db, a_picks=[1, 3, 5, 7])

    body = response.json()
    assert body["team_a"]["pick_legality"]["status"] == "pass"
    # salary side both pass at equal salaries, so overall stays compliant
    assert body["overall_status"] == "modeled-compliant"


def test_protected_outgoing_escalates_to_needs_review(monkeypatch):
    picks = [_pick(i, year, owner=1) for i, year in enumerate(WINDOW, start=1)]
    picks[0] = _pick(1, 2027, owner=1, origin=2, protected_top=14)  # incoming pick, protected
    db = FakePicksDB(picks, TEAMS)
    response = _analyze(monkeypatch, db, a_picks=[1])

    body = response.json()
    assert body["team_a"]["pick_legality"]["status"] == "needs-review"
    assert body["overall_status"] == "needs-review"


def test_sending_unowned_pick_is_rejected(monkeypatch):
    db = FakePicksDB([_pick(1, 2027, owner=2)], TEAMS)  # owned by team B
    response = _analyze(monkeypatch, db, a_picks=[1])

    assert response.status_code == 422
    assert "not owned" in response.json()["detail"]


def test_asset_ledger_is_internally_consistent_and_mirrored(monkeypatch):
    picks = [_pick(i, year, owner=1) for i, year in enumerate(WINDOW, start=1)]
    db = FakePicksDB(picks, TEAMS)
    body = _analyze(monkeypatch, db, a_picks=[2]).json()

    for side in ("team_a", "team_b"):
        assets = body[side]["assets"]
        assert assets["net_usd"] == (
            assets["player_surplus_received_usd"] + assets["picks_received_usd"]
            - assets["player_surplus_sent_usd"] - assets["picks_sent_usd"]
        )
    assert [p["pick_id"] for p in body["team_a"]["picks_outgoing"]] == \
           [p["pick_id"] for p in body["team_b"]["picks_incoming"]]
    assert body["team_a"]["assets"]["picks_sent_usd"] == body["team_b"]["assets"]["picks_received_usd"]


def _full_workspace(team_id, standard_count, two_way_count=0, cap_hit=10_000_000):
    """Workspace with N standard players + M two-way players, all with positive cap hits."""
    from scoutiq.api.routers.trades import TradeCapContext, TradeTeamWorkspace, TradeWorkspacePlayer
    from scoutiq.api.rosters import TeamSummary
    players = []
    pid = team_id * 100
    for _ in range(standard_count):
        players.append(TradeWorkspacePlayer(player_id=pid, full_name=f"P{pid}", position="G",
                                            cap_hit_usd=cap_hit, salary_pct=1.0, pay_source="contract",
                                            is_two_way=False))
        pid += 1
    for _ in range(two_way_count):
        players.append(TradeWorkspacePlayer(player_id=pid, full_name=f"TW{pid}", position="G",
                                            cap_hit_usd=100_000, salary_pct=0.1, pay_source="contract",
                                            is_two_way=True))
        pid += 1
    cap = TradeCapContext(salary_cap=160_000_000, tax_line=190_000_000,
                          first_apron=200_000_000, second_apron=210_000_000)
    return TradeTeamWorkspace(
        team=TeamSummary(team_id=team_id, abbreviation=f"T{team_id}", name=f"Team {team_id}"),
        season="2026-27", is_projected_cap=True, cap_context=cap,
        payroll_before_usd=standard_count * cap_hit, tier_before="below-tax",
        roster_count=len(players), players=players, caveat="test",
    )


def test_roster_count_warning_escalates_salary_compliant_trade(monkeypatch):
    """A 1-for-2 that salary-matches but pushes a 15-man roster to 16 → needs-review."""
    from scoutiq.api.cap_simulator import SeasonCapData
    cap = SeasonCapData("2026-27", 160_000_000, 190_000_000, 200_000_000, 210_000_000, is_projected=True)
    ws_a = _full_workspace(1, standard_count=15, two_way_count=1, cap_hit=20_000_000)
    ws_b = _full_workspace(2, standard_count=15, cap_hit=10_000_000)
    monkeypatch.setattr(trades_router, "load_season_caps", lambda db_: {cap.season: cap})
    monkeypatch.setattr(trades_router, "cap_for", lambda season, caps: cap)
    monkeypatch.setattr(trades_router, "_load_trade_workspaces",
                        lambda db_, ids, season, **kw: {1: ws_a, 2: ws_b})
    monkeypatch.setattr(trades_router, "_selected_values", lambda db_, ids: {})
    monkeypatch.setattr(trades_router, "load_fit_context", lambda db_, season: build_fit_context([]))
    app.dependency_overrides[get_db] = lambda: FakePicksDB([], TEAMS)

    a_send = [ws_a.players[0].player_id]            # 1 player, $20M
    b_send = [p.player_id for p in ws_b.players[:2]]  # 2 players, $20M total → salary matches
    try:
        body = TestClient(app).post("/trades/analyze", json={
            "season": "2026-27", "team_a_id": 1, "team_b_id": 2,
            "team_a_sends": a_send, "team_b_sends": b_send,
        }).json()
    finally:
        app.dependency_overrides.clear()

    a = body["team_a"]
    assert a["salary_match"]["status"] == "pass"          # salary is fine
    rl = a["roster_legality"]
    assert rl["status"] == "needs-review"                 # 15 → 16 standard
    assert rl["standard_before"] == 15 and rl["standard_after"] == 16 and rl["net_change"] == 1
    assert rl["two_way_count"] == 1                        # two-way excluded from the count
    assert body["overall_status"] == "needs-review"       # roster escalates the whole trade
