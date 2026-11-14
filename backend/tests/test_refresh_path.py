"""Offline tests for the data-refresh path: load_stats merge, roster reconciliation, coverage tool."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from scoutiq.etl import check_refresh_coverage as cc
from scoutiq.etl import load_current_rosters as lcr
from scoutiq.etl import load_stats as ls
from scoutiq.models import CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX
from scoutiq.sources import nba

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def _scalar_params(compiled) -> set:
    return {v for v in compiled.params.values() if isinstance(v, (str, int, float))}


def _conflict(stmt) -> str:
    sql = _sql(stmt)
    return sql[sql.index("ON CONFLICT"):]


class RecordingSession:
    def __init__(self, select_rows=()):
        self.statements: list = []
        self.select_rows = list(select_rows)

    def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: self.select_rows, first=lambda: None)

    def writes(self) -> list:
        return [s for s in self.statements if isinstance(s, (Insert, Update))]


def _patch_session(monkeypatch, module, session):
    opened = []

    @contextmanager
    def fake_get_session():
        opened.append(True)
        yield session

    monkeypatch.setattr(module, "get_session", fake_get_session)
    return opened


# ---------- load_stats ----------

def _season_frame(n=3, usg=0.2):
    return pd.DataFrame({
        "PLAYER_ID": list(range(1, n + 1)),
        "PLAYER_NAME": [f"Test Player {i}" for i in range(1, n + 1)],
        "TEAM_ID": [10] * n,
        "TEAM_ABBREVIATION": ["TST"] * n,
        "AGE": [25] * n,
        "GP": [60] * n,
        "MIN": [1500.0] * n,
        "PTS": [10] * n,
        "USG_PCT": [usg] * n,
        "PIE": [0.1] * n,
    })


def test_nba_and_bbref_advanced_keys_are_disjoint():
    assert not set(ls.ADV_KEYS) & set(ls.BBREF_ADV_KEYS)


def test_advanced_assignment_merges_instead_of_replacing():
    sql = _conflict(ls.player_season_upsert([{"player_id": 1, "season": "2025-26", "advanced": {}}]))
    assert "advanced = excluded.advanced" not in sql
    assert "coalesce(player_seasons.advanced" in sql
    assert "- CAST(ARRAY[" in sql
    assert "|| coalesce(excluded.advanced" in sql
    stmt = ls.player_season_upsert([{"player_id": 1, "season": "2025-26", "advanced": {}}])
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert set(ls.ADV_KEYS) <= {v for v in params.values() if isinstance(v, str)}


def test_team_id_assignment_keeps_stored_team_for_bbref_reconciled_rows():
    stmt = ls.player_season_upsert([{"player_id": 1, "season": "2025-26", "advanced": {}}])
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "team_id = CASE WHEN (player_seasons.advanced ?| ARRAY[" in sql
    assert "THEN player_seasons.team_id ELSE excluded.team_id END" in sql
    assert set(ls.BBREF_ADV_KEYS) <= _scalar_params(compiled)


def _merge_reference(stored: dict | None, incoming: dict | None) -> dict:
    # Mirrors the SQL verified on Postgres:
    # (coalesce(stored, '{}') - ARRAY[nba keys]) || coalesce(incoming, '{}')
    kept = {k: v for k, v in (stored or {}).items() if k not in ls.ADV_KEYS}
    return {**kept, **(incoming or {})}


def test_merge_rule_keeps_bbref_replaces_nba_and_drops_stale_nba_keys():
    stored = {"BPM": 1.5, "VORP": 2.0, "WS": 3, "PIE": 0.1, "USG_PCT": 0.2}
    incoming = {"PIE": 0.12}
    once = _merge_reference(stored, incoming)
    assert once == {"BPM": 1.5, "VORP": 2.0, "WS": 3, "PIE": 0.12}
    assert _merge_reference(once, incoming) == once


def test_load_season_is_idempotent_and_payload_carries_only_nba_keys(monkeypatch):
    monkeypatch.setattr(nba, "fetch_season", lambda season: _season_frame())

    def run_once():
        session = RecordingSession()
        _patch_session(monkeypatch, ls, session)
        ls.load_season("2025-26", min_players=1)
        stmt = session.writes()[-1]
        compiled = stmt.compile(dialect=postgresql.dialect())
        return str(compiled), compiled.params

    first, second = run_once(), run_once()
    assert first == second
    sql, params = first
    assert "INSERT INTO player_seasons" in sql
    advanced_payloads = [v for v in params.values() if isinstance(v, dict) and "USG_PCT" in v]
    assert advanced_payloads
    for payload in advanced_payloads:
        assert set(payload) <= set(ls.ADV_KEYS)


def test_validate_season_frame_rejections_and_acceptance():
    good = _season_frame(5)
    ls.validate_season_frame(good, "2025-26", min_players=5)

    with pytest.raises(ValueError, match="2025-26.*empty"):
        ls.validate_season_frame(good.iloc[0:0], "2025-26", min_players=1)
    with pytest.raises(ValueError, match="missing required columns"):
        ls.validate_season_frame(good.drop(columns=["GP"]), "2025-26", min_players=1)
    dup = pd.concat([good, good.iloc[[0]]])
    with pytest.raises(ValueError, match="duplicate"):
        ls.validate_season_frame(dup, "2025-26", min_players=1)
    with pytest.raises(ValueError, match="fewer than"):
        ls.validate_season_frame(good, "2025-26", min_players=6)
    with pytest.raises(ValueError, match="USG_PCT"):
        ls.validate_season_frame(_season_frame(5, usg=None), "2025-26", min_players=1)
    with pytest.raises(ValueError, match="USG_PCT"):
        ls.validate_season_frame(good.drop(columns=["USG_PCT"]), "2025-26", min_players=1)


def test_load_season_with_bad_frame_raises_before_opening_a_session(monkeypatch):
    monkeypatch.setattr(nba, "fetch_season", lambda season: _season_frame(2))
    opened = _patch_session(monkeypatch, ls, RecordingSession())
    with pytest.raises(ValueError):
        ls.load_season("2025-26", min_players=300)
    assert opened == []


# ---------- roster feed parsing ----------

def _feed_df(rows):
    return pd.DataFrame(rows, columns=["PERSON_ID", "DISPLAY_FIRST_LAST", "TEAM_ID", "ROSTERSTATUS"])


def test_parse_roster_feed_filters_unrostered_and_teamless():
    df = _feed_df([
        (1, "A One", 10, 1),
        (2, "B Two", 10, 0),
        (3, "C Three", 0, 1),
        (4, "D Four", 11, 1),
    ])
    rows, problems = lcr.parse_roster_feed(df)
    assert [r["player_id"] for r in rows] == [1, 4]
    assert problems == []


def test_parse_roster_feed_reports_missing_columns():
    rows, problems = lcr.parse_roster_feed(_feed_df([]).drop(columns=["TEAM_ID"]))
    assert rows == [] and "TEAM_ID" in problems[0]


def test_parse_roster_feed_reports_duplicate_player():
    df = _feed_df([(1, "A One", 10, 1), (1, "A One", 11, 1)])
    rows, problems = lcr.parse_roster_feed(df)
    assert len(rows) == 1 and rows[0]["current_team_id"] == 10
    assert problems == ["player 1 appears on more than one roster row"]


# ---------- roster planning ----------

TEAMS = set(range(1, 31))


def _full_feed(per_team=15):
    return [
        {"player_id": t * 1000 + i, "full_name": f"Test {t}-{i}", "current_team_id": t}
        for t in sorted(TEAMS) for i in range(per_team)
    ]


def _existing_from(feed, *, departed=0, moved_ids=()):
    rows = []
    for r in feed:
        team = r["current_team_id"] + 1 if r["player_id"] in moved_ids else r["current_team_id"]
        rows.append((r["player_id"], r["full_name"], team))
    rows.extend((90000 + i, f"Gone {i}", 5) for i in range(departed))
    return rows


def test_plan_complete_feed_lists_departed_moved_and_counts():
    feed = _full_feed()
    feed = [r for r in feed if r["player_id"] != 1003]
    existing = _existing_from(_full_feed(), departed=3, moved_ids={2001, 2002})
    plan = lcr.plan_roster_refresh(feed, existing, TEAMS, season="2025-26")
    assert plan.complete and plan.problems == []
    assert plan.source == "nba_api.commonallplayers:2025-26"
    assert [d["player_id"] for d in plan.departed] == [1003, 90000, 90001, 90002]
    assert plan.departed[1]["previous_team_id"] == 5
    assert [m["player_id"] for m in plan.moved] == [2001, 2002]
    assert plan.moved[0]["previous_team_id"] == 3 and plan.moved[0]["current_team_id"] == 2
    assert len(plan.assignments) == 449
    assert plan.added == 0
    assert plan.unchanged == 449 - 2
    d = plan.to_dict()
    assert d["counts"]["departed"] == 4 and d["complete"] is True
    json.dumps(d)


def test_plan_counts_added_players():
    feed = _full_feed()
    existing = [e for e in _existing_from(feed) if e[0] != 1000]
    plan = lcr.plan_roster_refresh(feed, existing, TEAMS, season="2025-26")
    assert plan.added == 1


def _plan(feed, existing=(), **kw):
    return lcr.plan_roster_refresh(feed, existing, TEAMS, season="2025-26", **kw)


def test_plan_empty_feed_is_incomplete():
    plan = _plan([])
    assert not plan.complete
    assert any("no rostered players" in p for p in plan.problems)


def test_plan_missing_team_is_incomplete():
    plan = _plan([r for r in _full_feed() if r["current_team_id"] != 7])
    assert not plan.complete
    assert any("no players for teams [7]" in p for p in plan.problems)


def test_plan_unknown_team_is_incomplete():
    plan = _plan(_full_feed() + [{"player_id": 5, "full_name": "X", "current_team_id": 999}])
    assert not plan.complete
    assert any("999" in p and "not NBA teams" in p for p in plan.problems)


def test_plan_team_below_min_and_above_max_are_incomplete():
    feed = _full_feed()
    low = [r for r in feed if not (r["current_team_id"] == 3 and r["player_id"] % 1000 >= lcr.MIN_TEAM_PLAYERS - 1)]
    plan = _plan(low)
    assert any("team 3 has" in p and "below" in p for p in plan.problems) and not plan.complete
    high = feed + [
        {"player_id": 70000 + i, "full_name": f"Extra {i}", "current_team_id": 4}
        for i in range(lcr.MAX_TEAM_PLAYERS - 15 + 1)
    ]
    plan = _plan(high)
    assert any("team 4 has" in p and "above" in p for p in plan.problems) and not plan.complete


def test_plan_departed_fraction_limit():
    feed = _full_feed()
    keep = feed[:6]
    existing = [(r["player_id"], r["full_name"], r["current_team_id"]) for r in keep]
    existing += [(90000 + i, f"Gone {i}", 5) for i in range(4)]
    at_limit = _plan(feed, existing)
    assert not any("absent from the feed" in p for p in at_limit.problems)
    over = _plan(feed, existing + [(95000, "Gone more", 5)])
    assert any("5 of 11" in p or "absent from the feed" in p for p in over.problems)
    assert not over.complete


def test_plan_collects_all_problems_and_feed_problems():
    plan = _plan([], feed_problems=["player 1 appears on more than one roster row"])
    assert plan.problems[0].startswith("player 1")
    assert len(plan.problems) >= 2 or "no rostered players" in plan.problems[-1]


# ---------- load_current_rosters ----------

def _feed_frame(feed):
    return _feed_df([(r["player_id"], r["full_name"], r["current_team_id"], 1) for r in feed])


def _setup_rosters(monkeypatch, feed, existing):
    monkeypatch.setattr(nba, "fetch_current_players", lambda season: _feed_frame(feed))
    monkeypatch.setattr(
        nba, "team_rows",
        lambda: [{"team_id": t, "abbreviation": f"T{t}", "name": f"Team {t}"} for t in sorted(TEAMS)],
    )
    session = RecordingSession(select_rows=existing)
    _patch_session(monkeypatch, lcr, session)
    return session


def test_incomplete_feed_raises_and_writes_nothing(monkeypatch):
    feed = [r for r in _full_feed() if r["current_team_id"] != 7]
    session = _setup_rosters(monkeypatch, feed, _existing_from(_full_feed()))
    with pytest.raises(lcr.RosterCompletenessError) as err:
        lcr.load_current_rosters("2025-26", now=NOW)
    assert err.value.problems
    assert session.writes() == []


def test_complete_feed_clears_departed_players(monkeypatch):
    feed = _full_feed()
    session = _setup_rosters(monkeypatch, feed, _existing_from(feed, departed=2))
    plan = lcr.load_current_rosters("2025-26", now=NOW)
    assert plan.complete
    updates = [s for s in session.writes() if isinstance(s, Update)]
    assert len(updates) == 1
    compiled = updates[0].compile(dialect=postgresql.dialect())
    assert "current_team_id=%(current_team_id)s" in str(compiled).replace(" ", "")
    assert compiled.params["current_team_id"] is None
    assert compiled.params["current_team_source"].endswith(CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX)
    assert compiled.params["current_team_source"].startswith(plan.source)
    assert [90000, 90001] in list(compiled.params.values())
    inserts = [s for s in session.writes() if isinstance(s, Insert)]
    assert len(inserts) == 2


def test_no_update_when_nobody_departed(monkeypatch):
    feed = _full_feed()
    session = _setup_rosters(monkeypatch, feed, _existing_from(feed))
    lcr.load_current_rosters("2025-26", now=NOW)
    assert not [s for s in session.writes() if isinstance(s, Update)]


def test_dry_run_writes_nothing(monkeypatch):
    feed = _full_feed()
    session = _setup_rosters(monkeypatch, feed, _existing_from(feed, departed=2))
    plan = lcr.load_current_rosters("2025-26", dry_run=True, now=NOW)
    assert len(plan.departed) == 2
    assert session.writes() == []


def test_upsert_only_skips_gate_and_clearing(monkeypatch, capsys):
    feed = [r for r in _full_feed() if r["current_team_id"] != 7]
    session = _setup_rosters(monkeypatch, feed, _existing_from(_full_feed(), departed=2))
    plan = lcr.load_current_rosters("2025-26", reconcile=False, now=NOW)
    assert not plan.complete
    assert not [s for s in session.writes() if isinstance(s, Update)]
    assert [s for s in session.writes() if isinstance(s, Insert)]
    assert "not cleared" in capsys.readouterr().out


# ---------- coverage tool ----------

def test_flatten_and_diff_reports():
    before = {"a": {"n": 1, "s": "x", "gone": 5}, "generated_at": "t0"}
    after = {"a": {"n": 4, "s": "y", "new": 2}, "generated_at": "t1"}
    assert cc.flatten(before) == {"a.n": 1, "a.s": "x", "a.gone": 5, "generated_at": "t0"}
    diff = {d["path"]: d for d in cc.diff_reports(before, after)}
    assert list(diff) == ["a.gone", "a.n", "a.new", "a.s"]
    assert diff["a.n"]["delta"] == 3
    assert diff["a.s"]["delta"] is None
    assert diff["a.gone"]["after"] is None and diff["a.new"]["before"] is None
    assert "generated_at" not in " ".join(diff)
    assert cc.render_diff([]) == "no differences"
    assert "a.n: 1 -> 4 (+3)" in cc.render_diff(list(diff.values()))


def test_cache_summary_recursive_and_missing(tmp_path):
    (tmp_path / "sub" / "deeper").mkdir(parents=True)
    (tmp_path / "a.html").write_text("abc")
    (tmp_path / "sub" / "deeper" / "b.html").write_text("de")
    summary = cc.cache_summary(tmp_path)
    assert summary["files"] == 2 and summary["bytes"] == 5
    assert summary["oldest_mtime"] and summary["newest_mtime"]
    missing = cc.cache_summary(tmp_path / "nope")
    assert missing["files"] == 0 and missing["bytes"] == 0 and missing["oldest_mtime"] is None


class FakeConn:
    def __init__(self, rows=()):
        self.statements: list[str] = []
        self.rows = list(rows)
        self.rolled_back = False
        self.closed = False

    def exec_driver_sql(self, sql, params=None):
        self.statements.append(sql)
        rows = [SimpleNamespace(_mapping=r) for r in self.rows]
        return SimpleNamespace(all=lambda: rows)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_write_snapshot_refuses_non_empty_dir(tmp_path):
    (tmp_path / "existing.txt").write_text("x")
    conn = FakeConn()
    with pytest.raises(FileExistsError):
        cc.write_snapshot(conn, tmp_path, ["2025-26"], {})
    assert conn.statements == []


def test_write_snapshot_writes_expected_files(tmp_path):
    conn = FakeConn(rows=[{"player_id": 1, "ts": NOW}])
    out = cc.write_snapshot(conn, tmp_path / "snap", ["2025-26", "2026-27"], {"k": 1})
    names = sorted(p.name for p in out)
    assert names == [
        "coverage.json", "player_salaries_2025-26.json", "player_salaries_2026-27.json",
        "player_seasons_2025-26.json", "player_seasons_2026-27.json", "players_current_team.json",
    ]
    assert json.loads((tmp_path / "snap" / "players_current_team.json").read_text())[0]["ts"] == NOW.isoformat()


def test_main_is_read_only(monkeypatch, tmp_path, capsys):
    conn = FakeConn()
    monkeypatch.setattr(cc, "_connect", lambda: conn)
    monkeypatch.setattr(cc, "collect", lambda c: {"baseline": {"valuation_baseline_season": "2025-26"}})
    out_json = tmp_path / "r.json"
    assert cc.main(["--raw-dir", str(tmp_path / "raw"), "--json", str(out_json)]) == 0
    assert conn.statements[0] == "SET TRANSACTION READ ONLY"
    assert conn.rolled_back and conn.closed
    report = json.loads(out_json.read_text())
    assert "generated_at" in report and report["raw_cache"]["files"] == 0
    assert cc.main(["--raw-dir", str(tmp_path / "raw"), "--compare", str(out_json)]) == 0
    assert "no differences" in capsys.readouterr().out


def test_coverage_module_never_uses_get_session():
    import inspect

    assert "get_session" not in inspect.getsource(cc)


def test_on_plan_called_once_before_any_write(monkeypatch):
    feed = _full_feed()
    session = _setup_rosters(monkeypatch, feed, _existing_from(feed, departed=2))
    seen = []
    lcr.load_current_rosters(
        "2025-26", now=NOW, on_plan=lambda plan: seen.append((plan, len(session.writes())))
    )
    assert len(seen) == 1
    assert seen[0][1] == 0
    assert seen[0][0].source == "nba_api.commonallplayers:2025-26"
    assert session.writes()


def test_on_plan_called_when_feed_is_incomplete(monkeypatch):
    feed = [r for r in _full_feed() if r["current_team_id"] != 7]
    session = _setup_rosters(monkeypatch, feed, _existing_from(_full_feed()))
    seen = []
    with pytest.raises(lcr.RosterCompletenessError):
        lcr.load_current_rosters("2025-26", now=NOW, on_plan=seen.append)
    assert len(seen) == 1 and not seen[0].complete
    assert session.writes() == []


def test_on_plan_failure_prevents_any_write(monkeypatch):
    feed = _full_feed()
    session = _setup_rosters(monkeypatch, feed, _existing_from(feed, departed=2))

    def boom(plan):
        raise OSError("disk full")

    with pytest.raises(OSError):
        lcr.load_current_rosters("2025-26", now=NOW, on_plan=boom)
    assert session.writes() == []
