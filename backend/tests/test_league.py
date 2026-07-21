"""Tests for the league cap-landscape router.

Collaborators (rosters.team_cap_hits, value_players) are monkeypatched so the test
exercises response shaping, tier classification, and sort/aggregate math without a
live DB or model.
"""
import scoutiq.api.routers.league as league
from fastapi.testclient import TestClient

from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from fakes import FakeDB
from scoutiq.models import CapConstants, Player, Team

CAP_ROW = CapConstants(
    season="2025-26",
    salary_cap=154_647_000,
    tax_line=187_895_000,
    first_apron=195_945_000,
    second_apron=207_824_000,
)

TEAM_A = Team(team_id=1, abbreviation="AAA", name="Team A")
TEAM_B = Team(team_id=2, abbreviation="BBB", name="Team B")

PLAYERS = [
    Player(player_id=101, current_team_id=1),
    Player(player_id=102, current_team_id=1),
    Player(player_id=201, current_team_id=2),
    Player(player_id=202, current_team_id=2),
]

CAP_HITS = {101: 20_000_000, 102: 10_000_000, 201: 120_000_000, 202: 76_000_000}


class _Val:
    def __init__(self, value_usd):
        self.value_usd = value_usd


VALS = {
    (101, "2025-26"): _Val(25_000_000),
    (102, "2025-26"): _Val(5_000_000),
    (201, "2025-26"): _Val(100_000_000),
    (202, "2025-26"): _Val(70_000_000),
}


def _patch_common(monkeypatch, cap_hits=CAP_HITS, vals=VALS):
    monkeypatch.setattr(league.rosters, "team_cap_hits", lambda db, ids, season: (dict(cap_hits), {}))
    monkeypatch.setattr(league, "value_players", lambda db, targets: dict(vals))


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _fake_db(*, next_season_players=(102, 202)):
    return FakeDB(
        players=PLAYERS,
        teams=[TEAM_A, TEAM_B],
        caps=[CAP_ROW],
        on_execute=lambda sql: (
            [(pid,) for pid in next_season_players] if "contract_years" in sql else None
        ),
    )


def test_league_cap_landscape_tiers_and_sums(monkeypatch):
    _patch_common(monkeypatch)
    body = _client(_fake_db()).get("/league/cap-landscape", params={"season": "2025-26"}).json()

    by_abbr = {row["team"]["abbreviation"]: row for row in body["teams"]}
    team_a = by_abbr["AAA"]
    team_b = by_abbr["BBB"]

    assert team_a["total_payroll_usd"] == 30_000_000
    assert team_a["tier"] == "below-tax"
    assert team_a["room_to_cap_usd"] == 154_647_000 - 30_000_000
    assert team_a["room_to_cap_usd"] > 0
    assert team_a["surplus_usd"] == 30_000_000 - 30_000_000
    # player 101 has no next-season contract-year -> expiring
    assert team_a["expiring_usd"] == 20_000_000

    assert team_b["total_payroll_usd"] == 196_000_000
    assert team_b["tier"] == "first-apron"
    assert team_b["surplus_usd"] == 170_000_000 - 196_000_000
    # player 201 has no next-season contract-year -> expiring
    assert team_b["expiring_usd"] == 120_000_000

    assert body["tier_counts"] == {
        "below-tax": 1,
        "taxpayer": 0,
        "first-apron": 1,
        "second-apron": 0,
    }
    assert body["teams_with_cap_room"] == 1
    assert body["league_expiring_usd"] == 20_000_000 + 120_000_000
    assert body["team_count"] == 2

    assert [row["team"]["abbreviation"] for row in body["teams"]] == ["BBB", "AAA"]


def test_league_cap_landscape_rejects_bad_season(monkeypatch):
    _patch_common(monkeypatch)
    resp = _client(_fake_db()).get("/league/cap-landscape", params={"season": "2026"})
    assert resp.status_code == 422


def test_league_cap_landscape_missing_cap_row_degrades_gracefully(monkeypatch):
    _patch_common(monkeypatch)
    fake = FakeDB(
        players=PLAYERS,
        teams=[TEAM_A, TEAM_B],
        caps=[],
        on_execute=lambda sql: (
            [(pid,) for pid in (102, 202)] if "contract_years" in sql else None
        ),
    )
    body = _client(fake).get("/league/cap-landscape", params={"season": "2025-26"}).json()

    assert body["context"]["salary_cap"] is None
    assert body["context"]["tax_line"] is None
    for row in body["teams"]:
        assert row["room_to_cap_usd"] is None
        assert row["payroll_pct"] is None
        assert row["tier"] == "below-tax"
    assert body["teams_with_cap_room"] == 0
