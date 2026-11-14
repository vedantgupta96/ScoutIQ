"""The completed-season baseline (LATEST_SEASON) bounds every default valuation read path."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from provenance_db import make_session, seed
from scoutiq.api import rosters
from scoutiq.api.routers import data_provenance, free_agency
from scoutiq.api.season import LATEST_SEASON, is_completed_season, next_season
from scoutiq.backtest import panel
from scoutiq.model import publish_valuations as pv
from scoutiq.models import CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX, Player, Team


def _compiled(stmt):
    return stmt.compile(dialect=postgresql.dialect())


def _assert_bounded(stmt):
    compiled = _compiled(stmt)
    assert "player_seasons.season <=" in str(compiled)
    assert LATEST_SEASON in compiled.params.values()


class CapturingDB:
    def __init__(self):
        self.statements = []

    def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(first=lambda: None, all=lambda: [])

    def scalars(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [], first=lambda: None)


def test_is_completed_season():
    assert is_completed_season(LATEST_SEASON)
    assert is_completed_season("2020-21")
    assert not is_completed_season(next_season(LATEST_SEASON))
    assert not is_completed_season("2025-27")
    assert not is_completed_season("bogus")


def test_latest_stats_row_is_bounded():
    db = CapturingDB()
    rosters.latest_stats_row(1, db)
    _assert_bounded(db.statements[0])


def test_batched_summaries_is_bounded():
    db = CapturingDB()
    rosters.batched_summaries([Player(player_id=1, full_name="Test Player")], db)
    _assert_bounded(db.statements[0])


def test_free_agency_pool_statements_are_bounded():
    _assert_bounded(free_agency._latest_stats_rows_stmt([1, 2]))
    _assert_bounded(free_agency._seasons_played_stmt([1, 2]))


def test_publish_refuses_in_progress_season_before_opening_session(monkeypatch):
    def boom():
        raise AssertionError("session must not be opened")

    monkeypatch.setattr(pv, "get_session", boom)
    with pytest.raises(ValueError, match="2026-27"):
        pv.publish(["2026-27"])
    with pytest.raises(ValueError, match="SCO-49"):
        pv.publish([LATEST_SEASON, "2026-27"])


def test_publish_default_drops_seasons_beyond_baseline(monkeypatch):
    class DB:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: ["2024-25", "2025-26", "2026-27"])

    @contextmanager
    def fake_session():
        yield DB()

    built = []
    monkeypatch.setattr(pv, "get_session", fake_session)
    monkeypatch.setattr(pv, "build_season_rows", lambda db, season, at: built.append(season) or [])
    monkeypatch.setattr(pv, "upsert_rows", lambda db, values: None)
    pv.publish()
    assert built == ["2024-25", "2025-26"]


def test_build_panel_player_seasons_statement_is_bounded():
    db = CapturingDB()
    panel.build_panel(db)
    ps = [s for s in db.statements if "FROM player_seasons" in str(_compiled(s))]
    assert len(ps) == 1
    _assert_bounded(ps[0])


def _summary(player, latest_season=None, stats_team=None, current_team=None):
    return rosters._player_summary_from_parts(player, latest_season, stats_team, current_team)


def test_not_on_roster_note():
    player = Player(
        player_id=1, full_name="Test Player",
        current_team_source="nba_api.commonallplayers:2025-26" + CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX,
    )
    team = Team(team_id=10, abbreviation="TST", name="Test Team")
    expected = "Not on a current NBA roster as of the last roster refresh; latest stats-season team is historical."
    assert _summary(player, "2025-26", team).team_data_note == expected
    assert _summary(player).team_data_note == expected


def test_plain_or_missing_source_keeps_existing_note():
    team = Team(team_id=10, abbreviation="TST", name="Test Team")
    for source in (None, "nba_api.commonallplayers:2025-26"):
        player = Player(player_id=1, full_name="Test Player", current_team_source=source)
        assert "has not been loaded" in _summary(player, "2025-26", team).team_data_note


def test_no_completed_season_note_wording():
    player = Player(player_id=1, full_name="Test Player")
    team = Team(team_id=10, abbreviation="TST", name="Test Team")
    note = _summary(player, None, None, team).team_data_note
    assert note == "Current roster team is available, but no completed stats season is loaded for this player."


def test_provenance_caveat_flags_in_progress_season():
    behind = make_session()
    seed(behind, table="player_seasons", rows=[{"id": 1, "player_id": 1, "season": LATEST_SEASON}])
    assert "in-progress season" not in data_provenance._player_seasons(behind).caveat

    ahead = make_session()
    next_label = next_season(LATEST_SEASON)
    seed(ahead, table="player_seasons", rows=[
        {"id": 1, "player_id": 1, "season": LATEST_SEASON},
        {"id": 2, "player_id": 1, "season": next_label},
    ])
    caveat = data_provenance._player_seasons(ahead).caveat
    assert f"{next_label} is an in-progress season" in caveat
    assert f"completed {LATEST_SEASON} baseline" in caveat


def test_main_turns_incomplete_season_into_argparse_error(monkeypatch):
    def boom():
        raise AssertionError("session must not be opened")

    monkeypatch.setattr(pv, "get_session", boom)
    monkeypatch.setattr("sys.argv", ["publish_valuations", "--season", "2026-27"])
    with pytest.raises(SystemExit) as exc:
        pv.main()
    assert exc.value.code == 2


def test_main_does_not_swallow_other_value_errors(monkeypatch):
    class DB:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: ["2025-26"])

    @contextmanager
    def fake_session():
        yield DB()

    def model_failure(db, season, at):
        raise ValueError("model exploded")

    monkeypatch.setattr(pv, "get_session", fake_session)
    monkeypatch.setattr(pv, "build_season_rows", model_failure)
    monkeypatch.setattr("sys.argv", ["publish_valuations"])
    with pytest.raises(ValueError, match="model exploded"):
        pv.main()
