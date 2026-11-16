from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from fakes import FakeDB
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.api.season import LATEST_SEASON, in_progress_season
from scoutiq.models import Player, PlayerSeason, Team

PLAYER_ID = 1630217
FETCHED_AT = datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _player():
    return Player(player_id=PLAYER_ID, full_name="Desmond Bane", position="SG")


def _team():
    return Team(team_id=1610612753, abbreviation="ORL", name="Orlando Magic")


def _row(*, gp=10, minutes=Decimal("325.0"), box=None):
    if box is None:
        box = {"PTS": 220, "REB": 55, "AST": 41, "FGA": 160, "FTA": 50}
    return PlayerSeason(
        player_id=PLAYER_ID,
        season="2026-27",
        team_id=1610612753,
        gp=gp,
        minutes=minutes,
        box=box,
        source="espn",
        source_fetched_at=FETCHED_AT,
    )


def test_in_progress_season_is_after_baseline():
    assert in_progress_season() == "2026-27"


def test_season_to_date_per_game_values():
    client = _client(FakeDB(players=[_player()], teams=[_team()], seasons=[_row()]))

    response = client.get(f"/players/{PLAYER_ID}/season-to-date")

    assert response.status_code == 200
    body = response.json()
    assert body["season"] == "2026-27"
    assert body["valuation_season"] == LATEST_SEASON
    assert body["stats"] == {
        "gp": 10,
        "mpg": 32.5,
        "pts_pg": 22.0,
        "reb_pg": 5.5,
        "ast_pg": 4.1,
        "ts_pct": round(220 / (2 * (160 + 0.44 * 50)), 4),
    }
    assert body["team"]["abbreviation"] == "ORL"
    assert body["source"] == "espn"
    assert body["as_of_utc"] == FETCHED_AT.isoformat()
    assert "in progress" in body["note"]
    assert LATEST_SEASON in body["note"]


def test_season_to_date_without_row_has_no_stats():
    client = _client(FakeDB(players=[_player()], teams=[_team()]))

    body = client.get(f"/players/{PLAYER_ID}/season-to-date").json()

    assert body["stats"] is None
    assert body["team"] is None
    assert body["source"] is None
    assert body["as_of_utc"] is None
    assert body["note"] == "No 2026-27 regular-season stats are on file for this player."


def test_season_to_date_zero_games_treated_as_no_row():
    client = _client(FakeDB(players=[_player()], teams=[_team()], seasons=[_row(gp=0)]))

    body = client.get(f"/players/{PLAYER_ID}/season-to-date").json()

    assert body["stats"] is None
    assert body["note"] == "No 2026-27 regular-season stats are on file for this player."


def test_season_to_date_missing_shooting_inputs_null_ts_only():
    box = {"PTS": 220, "REB": 55, "AST": 41}
    client = _client(FakeDB(players=[_player()], teams=[_team()], seasons=[_row(box=box)]))

    stats = client.get(f"/players/{PLAYER_ID}/season-to-date").json()["stats"]

    assert stats["ts_pct"] is None
    assert stats["pts_pg"] == 22.0
    assert stats["mpg"] == 32.5


def test_season_to_date_unknown_player_404():
    client = _client(FakeDB())

    response = client.get(f"/players/{PLAYER_ID}/season-to-date")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Player {PLAYER_ID} not found."
