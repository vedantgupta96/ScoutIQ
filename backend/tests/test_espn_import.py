"""Offline tests for the SCO-49 ESPN import path: identity evidence, resolution, planning, apply, guards."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

from scoutiq.api import valuation
from scoutiq.api.season import LATEST_SEASON
from scoutiq.etl import import_espn_snapshot as ie
from scoutiq.etl import load_current_rosters as lcr
from scoutiq.etl import load_stats as ls
from scoutiq.etl import resolve_espn_identity as rei
from scoutiq.sources import identity_evidence as ev
from test_espn_refresh import _stats
from test_refresh_path import RecordingSession, _patch_session, _sql

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
FETCHED = "2026-11-16T01:00:00+00:00"
ROSTER_FETCHED = "2026-11-16T00:30:00+00:00"
TEAM_IDS = set(range(1, 31))
GENERATED = "2026-11-16T00:00:00+00:00"


def _sql_set(stmt) -> str:
    sql = _sql(stmt)
    return sql[sql.index("DO UPDATE SET"):]


# ---------- evidence parsers ----------

INDEX_SOURCE = """
players = [
    [1, 'Doe', 'Jane', 'Jane Doe', True],
    [2, 'Roe', 'Rob', 'Rob Roe', False],
]
teams = [[1, 'x']]
"""


def test_parse_nba_index_reads_only_the_literal_assignment():
    rows = ev.parse_nba_index(INDEX_SOURCE + "\nraise SystemExit('executed')\n")
    assert rows == [
        {"nba_id": 1, "full_name": "Jane Doe", "is_active": True},
        {"nba_id": 2, "full_name": "Rob Roe", "is_active": False},
    ]


def test_parse_nba_index_does_not_execute_code(tmp_path):
    marker = tmp_path / "ran"
    source = f"open({str(marker)!r}, 'w')\nplayers = [[1, 'a', 'b', 'A B', True]]\n"
    assert ev.parse_nba_index(source)[0]["nba_id"] == 1
    assert not marker.exists()


@pytest.mark.parametrize("source", [
    "teams = []",
    "players = []",
    "players = build()",
    "players = [[1, 'a', 'b', 'A B']]",
    "players = [['x', 'a', 'b', 'A B', True]]",
])
def test_parse_nba_index_rejects_missing_empty_or_malformed(source):
    with pytest.raises(ValueError):
        ev.parse_nba_index(source)


def test_parse_wikidata_keeps_numeric_ids_and_valid_dates():
    payload = {"results": {"bindings": [
        {"nba": {"value": "12"}, "dob": {"value": "2001-02-03T00:00:00Z"}, "itemLabel": {"value": "A B"}},
        {"nba": {"value": "abc"}, "itemLabel": {"value": "C"}},
        {"nba": {"value": "13"}, "dob": {"value": "not a date"}, "itemLabel": {"value": "D"}},
        {"nba": {"value": "14"}, "itemLabel": {"value": "E"}},
    ]}}
    assert ev.parse_wikidata(payload) == [
        {"nba_id": 12, "dob": "2001-02-03", "label": "A B"},
        {"nba_id": 13, "dob": None, "label": "D"},
        {"nba_id": 14, "dob": None, "label": "E"},
    ]
    with pytest.raises(ValueError):
        ev.parse_wikidata({})


def test_fetchers_issue_one_get_and_reject_non_200():
    class Session:
        def __init__(self, status):
            self.calls = []
            self.status = status

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return SimpleNamespace(status_code=self.status, text="t", json=lambda: {"k": 1})

    ok = Session(200)
    text, meta = ev.fetch_nba_index(ok)
    assert text == "t" and meta["source_url"] == ev.NBA_INDEX_URL and meta["fetched_at_utc"]
    assert ok.calls[0][1]["timeout"] == 60
    payload, meta = ev.fetch_wikidata(ok)
    assert payload == {"k": 1} and meta["source_url"] == ev.WIKIDATA_SPARQL_URL
    assert ok.calls[1][1]["params"] == {"query": ev.WIKIDATA_QUERY}
    assert ok.calls[1][1]["headers"]["Accept"] == "application/sparql-results+json"
    with pytest.raises(RuntimeError):
        ev.fetch_nba_index(Session(500))
    with pytest.raises(RuntimeError):
        ev.fetch_wikidata(Session(500))


# ---------- identity resolution ----------

def _athlete(pid, name="Jane Doe", dob="2000-01-02"):
    return {"provider_id": pid, "full_name": name, "date_of_birth": dob}


def _resolve(roster, **kwargs):
    kwargs.setdefault("stored_players", [])
    return rei.resolve_identities(roster, **kwargs)


def test_bbref_stored_and_wikidata_resolve():
    result = _resolve(
        [_athlete(1)],
        stored_players=[{"player_id": 50, "full_name": "Jane Doe"}],
        bbref_evidence=[{"nba_id": 50, "name": "Jane Doe", "dob": "2000-01-02", "bbref_slug": "x", "verified": True}],
        wikidata=[{"nba_id": 50, "dob": "2000-01-02", "label": "Jane Doe"}],
    )
    row = result["resolved"][0]
    assert row["nba_id"] == 50 and row["basis"] == "bbref_dob+stored_name+wikidata_dob"
    assert row["sources"] == ["bbref_dob", "stored_name", "wikidata_dob"]
    assert row["is_new_player"] is False and row["player_full_name"] == "Jane Doe"
    assert result["counts"] == {
        "athletes": 1, "resolved": 1, "unresolved": 0, "new_players": 0,
        "by_basis": {"bbref_dob+stored_name+wikidata_dob": 1},
    }


def test_unverified_or_dobless_bbref_rows_are_ignored():
    result = _resolve(
        [_athlete(1)],
        bbref_evidence=[
            {"nba_id": 50, "name": "Jane Doe", "dob": "2000-01-02", "verified": False},
            {"nba_id": 51, "name": "Jane Doe", "dob": "", "verified": True},
        ],
    )
    assert result["unresolved"][0]["reason"] == "no candidate"


def test_stored_name_plus_wikidata_dob_resolves_existing_player():
    result = _resolve(
        [_athlete(1)],
        stored_players=[{"player_id": 50, "full_name": "jane doe"}],
        wikidata=[{"nba_id": 50, "dob": "2000-01-02", "label": "Someone Else"}],
    )
    assert result["resolved"][0]["basis"] == "stored_name+wikidata_dob"


def test_index_plus_wikidata_resolves_new_player_with_index_name():
    result = _resolve(
        [_athlete(1, name="Jane Doe")],
        nba_index=[{"nba_id": 70, "full_name": "Jane  Doe", "is_active": True}],
        wikidata=[{"nba_id": 70, "dob": "2000-01-02", "label": "x"}],
    )
    row = result["resolved"][0]
    assert row["is_new_player"] is True and row["player_full_name"] == "Jane  Doe"
    assert result["counts"]["new_players"] == 1


def test_name_only_sources_do_not_resolve():
    stored = _resolve([_athlete(1)], stored_players=[{"player_id": 50, "full_name": "Jane Doe"}])
    assert stored["unresolved"][0]["reason"] == "no birth-date corroboration"
    index = _resolve([_athlete(1)], nba_index=[{"nba_id": 70, "full_name": "Jane Doe", "is_active": True}])
    assert index["unresolved"][0]["reason"] == "no birth-date corroboration"
    both = _resolve(
        [_athlete(1)],
        stored_players=[{"player_id": 50, "full_name": "Jane Doe"}],
        nba_index=[{"nba_id": 50, "full_name": "Jane Doe", "is_active": True}],
    )
    assert both["unresolved"][0]["reason"] == "no birth-date corroboration"
    assert both["unresolved"][0]["candidates"] == {"50": ["nba_index_name", "stored_name"]}


def test_wikidata_label_and_dob_alone_is_single_source():
    result = _resolve([_athlete(1)], wikidata=[{"nba_id": 80, "dob": "2000-01-02", "label": "Jane Doe"}])
    assert result["unresolved"][0]["reason"] == "single source"


def test_conflicting_candidates_unresolved():
    result = _resolve(
        [_athlete(1)],
        stored_players=[{"player_id": 50, "full_name": "Jane Doe"}],
        nba_index=[{"nba_id": 70, "full_name": "Jane Doe", "is_active": True}],
        wikidata=[{"nba_id": 50, "dob": "2000-01-02", "label": "x"}],
    )
    assert result["unresolved"][0]["reason"] == "conflicting candidates"


def test_index_active_disambiguation():
    index = [
        {"nba_id": 70, "full_name": "Jane Doe", "is_active": False},
        {"nba_id": 71, "full_name": "Jane Doe", "is_active": True},
    ]
    wiki = [{"nba_id": 71, "dob": "2000-01-02", "label": "Jane Doe"}]
    assert _resolve([_athlete(1)], nba_index=index, wikidata=wiki)["resolved"][0]["nba_id"] == 71
    both_active = [{**index[0], "is_active": True}, index[1]]
    result = _resolve([_athlete(1)], nba_index=both_active, wikidata=wiki)
    assert result["unresolved"][0]["reason"] == "conflicting candidates"


def test_override_accepted_only_when_proposed():
    override = [{"espn_id": 1, "nba_id": 70, "reason": "reviewed"}]
    index = [{"nba_id": 70, "full_name": "Jane Doe", "is_active": True}]
    ok = _resolve([_athlete(1)], nba_index=index, overrides=override)
    row = ok["resolved"][0]
    assert row["basis"] == "override" and row["override_reason"] == "reviewed" and row["nba_id"] == 70
    bad = _resolve([_athlete(1)], nba_index=index, overrides=[{"espn_id": 1, "nba_id": 99, "reason": "r"}])
    assert bad["unresolved"][0]["reason"] == "override nba_id is not proposed by any source"


def test_one_nba_id_claimed_by_two_athletes_unresolves_both():
    result = _resolve(
        [_athlete(1), _athlete(2), _athlete(3, name="Other Guy", dob="1999-01-01")],
        nba_index=[
            {"nba_id": 70, "full_name": "Jane Doe", "is_active": True},
            {"nba_id": 71, "full_name": "Other Guy", "is_active": True},
        ],
        wikidata=[
            {"nba_id": 70, "dob": "2000-01-02", "label": "Jane Doe"},
            {"nba_id": 71, "dob": "1999-01-01", "label": "Other Guy"},
        ],
    )
    assert [r["provider_id"] for r in result["resolved"]] == [3]
    assert [r["provider_id"] for r in result["unresolved"]] == [1, 2]
    assert {r["reason"] for r in result["unresolved"]} == {"nba id claimed by more than one athlete"}


def test_load_overrides_validation_and_committed_csv(tmp_path):
    header = "espn_id,nba_id,full_name,reason,reviewed_on\n"
    dup = tmp_path / "dup.csv"
    dup.write_text(header + "1,2,A,why,2026-01-01\n1,3,B,why,2026-01-01\n")
    with pytest.raises(ValueError, match="duplicate"):
        rei.load_overrides(dup)
    blank = tmp_path / "blank.csv"
    blank.write_text(header + "1,2,A, ,2026-01-01\n")
    with pytest.raises(ValueError, match="blank reason"):
        rei.load_overrides(blank)
    committed = rei.load_overrides()
    assert len(committed) == 6
    assert {o["espn_id"] for o in committed} == {4600663, 4683860, 5105337, 5176517, 5105462, 4684443}


def test_resolve_cli_requires_cache_without_fetch_flag(tmp_path, monkeypatch, capsys):
    (tmp_path / "manifest.json").write_text(json.dumps({"season": "2026-27", "generated_at_utc": GENERATED}))
    (tmp_path / "normalized_roster.json").write_text("[]")
    monkeypatch.setattr(rei, "load_stored_players", lambda: [])
    assert rei.main(["--snapshot-dir", str(tmp_path)]) == 1
    assert "identity evidence cache is missing" in capsys.readouterr().err


def test_resolve_run_writes_identity_map_and_exits_nonzero_when_unresolved(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text(json.dumps({"season": "2026-27", "generated_at_utc": GENERATED}))
    (tmp_path / "normalized_roster.json").write_text(json.dumps([_athlete(1)]))
    cache = tmp_path / "identity_evidence"
    cache.mkdir()
    (cache / "nba_index.json").write_text(json.dumps(
        {"source_url": "u", "fetched_at_utc": "t", "text": "players = [[70, 'a', 'b', 'Jane Doe', True]]"}))
    (cache / "wikidata.json").write_text(json.dumps(
        {"source_url": "w", "fetched_at_utc": "t", "payload": {"results": {"bindings": [
            {"nba": {"value": "70"}, "dob": {"value": "2000-01-02"}, "itemLabel": {"value": "Jane Doe"}}]}}}))
    monkeypatch.setattr(rei, "load_stored_players", lambda: [])
    assert rei.main(["--snapshot-dir", str(tmp_path)]) == 0
    written = json.loads((tmp_path / "identity_map.json").read_text())
    assert written["season"] == "2026-27" and written["snapshot_generated_at_utc"] == GENERATED
    assert written["resolved"][0]["nba_id"] == 70
    assert written["evidence"]["nba_index"]["source_url"] == "u"
    (tmp_path / "normalized_roster.json").write_text(json.dumps([_athlete(1), _athlete(2, name="Nobody")]))
    assert rei.main(["--snapshot-dir", str(tmp_path)]) == 1


# ---------- synthetic snapshot ----------

def _world(*, drop_stats=(), missing_404=(), none_played=()):
    roster, resolved, stats = [], [], {}
    for team in range(1, 31):
        for slot in range(13):
            pid = team * 1000 + slot
            roster.append({
                "provider_id": pid, "full_name": f"Player {pid}", "date_of_birth": "2000-06-15",
                "current_team_abbreviation": f"T{team:02d}", "current_team_provider_id": team,
                "scoutiq_team_id": team, "salary_context": None,
            })
            resolved.append({
                "provider_id": pid, "full_name": f"Player {pid}", "date_of_birth": "2000-06-15",
                "nba_id": 9_000_000 + pid, "basis": "stored_name+wikidata_dob",
                "sources": ["stored_name", "wikidata_dob"], "is_new_player": False,
                "player_full_name": f"Stored {pid}", "override_reason": None,
            })
            if pid in drop_stats or pid in missing_404 or pid in none_played:
                continue
            stats[pid] = {
                "parsed": ie.espn.parse_season_totals(_stats(pid, gp=5), pid, "2026-27"),
                "fetched_at_utc": FETCHED, "source_url": "u",
            }
    manifest = {
        "season": "2026-27", "generated_at_utc": GENERATED, "errors": [],
        "missing_stats": [{"provider_id": p, "status": 404} for p in missing_404],
        "counts": {
            "validated_roster_teams": 30, "roster_athletes": len(roster), "validated_stats": len(stats),
            "missing_stats": len(missing_404), "none_played": len(none_played),
        },
    }
    snapshot = {
        "manifest": manifest, "roster": roster,
        "roster_fetched_at": {t: ROSTER_FETCHED for t in range(1, 31)},
        "stats": stats, "none_played": list(none_played), "problems": [],
    }
    identity = {
        "season": "2026-27", "snapshot_generated_at_utc": GENERATED,
        "resolved": resolved, "unresolved": [], "counts": {},
    }
    existing = [(9_000_000 + r["provider_id"], f"Stored {r['provider_id']}", r["scoutiq_team_id"]) for r in roster]
    kwargs = {
        "season": "2026-27", "existing_assignments": existing,
        "stored_player_ids": [e[0] for e in existing], "existing_season_rows": {},
        "existing_external_ids": {}, "team_ids": TEAM_IDS, "now": NOW,
    }
    return snapshot, identity, kwargs


def _plan(world=None, **overrides):
    snapshot, identity, kwargs = world or _world()
    kwargs = {**kwargs, **overrides}
    return ie.build_plan(snapshot, identity, **kwargs)


def test_complete_plan_counts_and_stamps():
    snapshot, identity, kwargs = _world(missing_404={1000, 1001}, none_played={2000})
    snapshot["stats"].pop(2000, None)
    new_pid = 3000
    identity["resolved"][identity["resolved"].index(
        next(r for r in identity["resolved"] if r["provider_id"] == new_pid))].update(is_new_player=True)
    kwargs["stored_player_ids"] = [p for p in kwargs["stored_player_ids"] if p != 9_000_000 + new_pid]
    kwargs["existing_assignments"] = [
        a for a in kwargs["existing_assignments"] if a[0] != 9_000_000 + new_pid and a[0] != 9_000_000 + 4000
    ] + [(7_777_777, "Gone Guy", 5), (9_000_000 + 5000, "Stored 5000", 1)]
    kwargs["existing_season_rows"] = {9_000_000 + 6000: ("espn", None)}
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert plan.problems == [] and plan.complete
    assert [p["player_id"] for p in plan.new_players] == [9_000_000 + new_pid]
    assert len(plan.assignments) == 390
    assert plan.added == 2
    assert [m["player_id"] for m in plan.moved] == [9_000_000 + 5000]
    assert [d["player_id"] for d in plan.departed] == [7_777_777]
    assert plan.departed_updated_at == datetime(2026, 11, 16, 0, 30, tzinfo=timezone.utc)
    assert plan.stat_updates == 1 and plan.stat_inserts == len(plan.stat_rows) - 1
    assert len(plan.stat_rows) == 387
    reasons = {w["full_name"]: w["reason"] for w in plan.without_stats}
    assert reasons["Stored 1000"] == "no ESPN regular-season stat record (HTTP 404)"
    assert reasons["Stored 2000"] == "zero games played"
    row = plan.stat_rows[0]
    assert row["age"] == 26 and row["source"] == "espn" and "advanced" not in row
    assert row["source_fetched_at"] == datetime(2026, 11, 16, 1, tzinfo=timezone.utc)
    assert row["team_id"] is None and row["gp"] == 5
    assignment = plan.assignments[0]
    assert assignment["current_team_updated_at"] == datetime(2026, 11, 16, 0, 30, tzinfo=timezone.utc)
    assert assignment["current_team_source"] == "espn.roster:2026-27"
    ext = plan.external_ids[0]
    assert ext["external_id"] == "1000" and ext["source"] == "espn" and ext["matched_at"] == NOW
    assert ext["evidence"]["espn_full_name"] == "Player 1000"
    report = plan.to_dict()
    json.dumps(report)
    assert report["stats"]["rostered"] == 390 and report["stats"]["with_stats"] == 387
    assert report["stats"]["max_gp"] == 5 and report["stats"]["by_roster_team"]["T01"] == {"rostered": 13, "with_stats": 11}
    assert report["roster"]["new_players"] == [{"full_name": "Stored 3000", "team": "T03"}]
    assert report["source_timestamps"]["stats_newest"] == FETCHED


def _has(plan, text):
    return any(text in p for p in plan.problems)


def test_completed_season_refused():
    snapshot, identity, kwargs = _world()
    kwargs["season"] = "2025-26"
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert _has(plan, "completed season") and not plan.complete


def test_manifest_gates():
    snapshot, identity, kwargs = _world()
    snapshot["manifest"]["season"] = "2025-26"
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "manifest season")
    snapshot, identity, kwargs = _world()
    snapshot["manifest"]["errors"] = [{"kind": "x"}]
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "collection errors")
    snapshot, identity, kwargs = _world()
    snapshot["manifest"]["counts"]["validated_roster_teams"] = 29
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "validated roster teams")
    snapshot, identity, kwargs = _world()
    snapshot["problems"] = ["stat file for athlete 1 failed validation: x"]
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "failed validation")


def test_identity_gates():
    snapshot, identity, kwargs = _world()
    identity["unresolved"] = [{"provider_id": 1}]
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "unresolved athletes")
    snapshot, identity, kwargs = _world()
    identity["resolved"].pop(0)
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "no resolved identity")
    snapshot, identity, kwargs = _world()
    identity["resolved"].append({**identity["resolved"][0], "provider_id": 99})
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "not on the roster")
    snapshot, identity, kwargs = _world()
    identity["resolved"][1]["nba_id"] = identity["resolved"][0]["nba_id"]
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "more than one athlete")
    snapshot, identity, kwargs = _world()
    identity["season"] = "2025-26"
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "identity map season")
    snapshot, identity, kwargs = _world()
    identity["snapshot_generated_at_utc"] = "other"
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "different snapshot")


def test_conflicting_existing_external_id():
    plan = _plan(existing_external_ids={"1000": 123})
    assert _has(plan, "conflict with stored external id")
    assert not _plan(existing_external_ids={"1000": 9_001_000}).problems


def test_stale_snapshot_reports_counts_and_oldest():
    plan = _plan(now=NOW + timedelta(hours=48))
    assert _has(plan, "30 roster and 390 stat responses") and _has(plan, ROSTER_FETCHED)
    assert _has(plan, (NOW + timedelta(hours=48)).isoformat())
    assert not _plan(now=NOW + timedelta(hours=48), max_snapshot_age_hours=100).problems


def test_existing_non_espn_season_row_blocks():
    plan = _plan(existing_season_rows={9_001_000: ("nba.com", None), 9_001_001: (None, None)})
    assert _has(plan, "2 players already have")
    assert not _plan(existing_season_rows={9_001_000: ("espn", None)}).problems


def test_roster_completeness_problem_surfaces():
    snapshot, identity, kwargs = _world()
    snapshot["roster"] = [r for r in snapshot["roster"] if r["scoutiq_team_id"] != 7]
    identity["resolved"] = [r for r in identity["resolved"] if r["provider_id"] // 1000 != 7]
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert _has(plan, "no players for teams [7]")


# ---------- load_snapshot ----------

def test_load_snapshot_records_problems_and_none_played(tmp_path):
    (tmp_path / "raw" / "rosters").mkdir(parents=True)
    (tmp_path / "raw" / "stats").mkdir(parents=True)
    roster = [
        {"provider_id": pid, "full_name": f"P{pid}", "date_of_birth": "2000-01-01",
         "current_team_abbreviation": "AAA", "current_team_provider_id": 5, "scoutiq_team_id": 1}
        for pid in (11, 12, 13)
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"season": "2026-27", "generated_at_utc": GENERATED}))
    (tmp_path / "normalized_roster.json").write_text(json.dumps(roster))
    (tmp_path / "raw" / "rosters" / "5.json").write_text(
        json.dumps({"source_url": "r", "fetched_at_utc": ROSTER_FETCHED, "payload": {}}))

    def put(pid, payload):
        (tmp_path / "raw" / "stats" / f"{pid}.json").write_text(
            json.dumps({"source_url": "s", "fetched_at_utc": FETCHED, "payload": payload}))

    put(11, _stats(11, gp=4))
    bad = _stats(12)
    bad["splits"]["type"] = "average"
    put(12, bad)
    zero = _stats(13, gp=0)
    for stat in zero["splits"]["categories"][0]["stats"]:
        if stat["name"] != "gamesPlayed":
            stat["value"] = 0.0
    put(13, zero)
    put(99, _stats(99))
    snapshot = ie.load_snapshot(tmp_path)
    assert snapshot["roster_fetched_at"] == {5: ROSTER_FETCHED}
    assert list(snapshot["stats"]) == [11] and snapshot["stats"][11]["fetched_at_utc"] == FETCHED
    assert snapshot["none_played"] == [13]
    assert any("athlete 12" in p for p in snapshot["problems"])
    assert any("athlete 99" in p and "not on the roster" in p for p in snapshot["problems"])


# ---------- apply_plan ----------

def _applied(plan):
    session = RecordingSession()
    ie.apply_plan(session, plan)
    return session


def test_apply_plan_statement_order_and_set_lists():
    snapshot, identity, kwargs = _world()
    kwargs["existing_assignments"] = kwargs["existing_assignments"][1:] + [(7_777_777, "Gone Guy", 5)]
    identity["resolved"][0]["is_new_player"] = True
    kwargs["stored_player_ids"] = kwargs["stored_player_ids"][1:]
    plan = ie.build_plan(snapshot, identity, **kwargs)
    session = _applied(plan)
    kinds = [(type(s).__name__, s.table.name) for s in session.writes()]
    assert kinds == [
        ("Insert", "players"), ("Insert", "players"), ("Update", "players"),
        ("Insert", "player_external_ids"), ("Insert", "player_seasons"),
    ]
    new, assign, departed, ext, seasons = session.writes()
    assert "ON CONFLICT (player_id) DO NOTHING" in _sql(new)
    assign_set = _sql_set(assign)
    assert "full_name" not in assign_set and "current_team_id" in assign_set
    assert "current_team_source" in assign_set and "current_team_updated_at" in assign_set
    assert _sql(assign).count("full_name") >= 1
    assert "uq_player_external_id_source_external" in _sql(ext)
    assert "player_external_ids.player_id = excluded.player_id" in _sql(ext)
    season_set = _sql_set(seasons)
    assert "advanced" not in season_set and "source_fetched_at" in season_set and "box" in season_set
    assert "WHERE player_seasons.source =" in _sql(seasons)


def test_apply_plan_skips_departed_update_when_nobody_departed():
    session = _applied(_plan())
    assert not [s for s in session.writes() if isinstance(s, Update)]
    assert all(isinstance(s, Insert) for s in session.writes())
    assert [s.table.name for s in session.writes()] == ["players", "player_external_ids", "player_seasons"]


# ---------- run ----------

class _RunSession:
    def __init__(self):
        self.statements = []

    def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [])


def _write_snapshot_dir(tmp_path, monkeypatch, *, generated=GENERATED):
    snapshot, identity, _ = _world()
    identity["snapshot_generated_at_utc"] = generated
    (tmp_path / "identity_map.json").write_text(json.dumps(identity))
    monkeypatch.setattr(ie, "load_snapshot", lambda path: snapshot)
    monkeypatch.setattr(ie.nba, "team_rows", lambda: [{"team_id": t} for t in TEAM_IDS])
    session = _RunSession()
    _patch_session(monkeypatch, ie, session)
    return session


def test_run_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    session = _write_snapshot_dir(tmp_path, monkeypatch)
    seen = []
    plan = ie.run(tmp_path, season="2026-27", dry_run=True, now=NOW, on_plan=seen.append)
    assert seen == [plan]
    assert not [s for s in session.statements if isinstance(s, (Insert, Update))]
    assert "dry run" in capsys.readouterr().out


def test_run_with_problem_raises_before_any_write(tmp_path, monkeypatch):
    session = _write_snapshot_dir(tmp_path, monkeypatch, generated="other")
    with pytest.raises(ie.ImportRefused) as raised:
        ie.run(tmp_path, season="2026-27", now=NOW)
    assert any("different snapshot" in p for p in raised.value.problems)
    assert not [s for s in session.statements if isinstance(s, (Insert, Update))]


def test_run_complete_applies(tmp_path, monkeypatch):
    session = _write_snapshot_dir(tmp_path, monkeypatch)
    plan = ie.run(tmp_path, season="2026-27", now=NOW)
    assert plan.complete
    assert [s for s in session.statements if isinstance(s, Insert)]


def test_import_cli_exit_codes(tmp_path, monkeypatch, capsys):
    _write_snapshot_dir(tmp_path, monkeypatch, generated="other")
    assert ie.main(["--snapshot-dir", str(tmp_path), "--season", "2025-26"]) == 1
    assert ie.main(["--snapshot-dir", str(tmp_path), "--dry-run", "--json", str(tmp_path / "o" / "p.json")]) == 1
    assert json.loads((tmp_path / "o" / "p.json").read_text())["complete"] is False
    assert "different snapshot" in capsys.readouterr().err


# ---------- valuation baseline guard ----------

def test_value_players_drops_in_progress_season_without_touching_db():
    class ExplodingDB:
        def __getattr__(self, name):
            raise AssertionError("database was touched")

    assert valuation.value_players(ExplodingDB(), [(1, "2026-27")]) == {}


def test_value_player_detail_refuses_in_progress_season():
    class ExplodingDB:
        def __getattr__(self, name):
            raise AssertionError("database was touched")

    with pytest.raises(LookupError, match=f"valuations stay on the completed {LATEST_SEASON} baseline"):
        valuation.value_player_detail(ExplodingDB(), 1, "2026-27")


# ---------- roster plan source and load_stats stamping ----------

def test_plan_roster_refresh_source_override_and_default():
    feed = [{"player_id": 1, "full_name": "A", "current_team_id": 1}]
    custom = lcr.plan_roster_refresh(feed, [], {1}, season="2026-27", source="espn.roster:2026-27")
    assert custom.source == "espn.roster:2026-27"
    assert lcr.plan_roster_refresh(feed, [], {1}, season="2026-27").source == "nba_api.commonallplayers:2026-27"


def test_load_stats_rows_and_set_carry_source_stamp():
    from test_refresh_path import _season_frame

    nba_module = ls.nba
    original = nba_module.fetch_season
    nba_module.fetch_season = lambda season: _season_frame()
    try:
        session = RecordingSession()
        from contextlib import contextmanager

        @contextmanager
        def fake():
            yield session

        original_get = ls.get_session
        ls.get_session = fake
        try:
            ls.load_season("2025-26", min_players=1)
        finally:
            ls.get_session = original_get
    finally:
        nba_module.fetch_season = original
    stmt = session.writes()[-1]
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert "nba.com" in params.values()
    assert any(isinstance(v, datetime) and v.tzinfo for v in params.values())
    set_sql = _sql_set(stmt)
    assert "source = excluded.source" in set_sql and "source_fetched_at = excluded.source_fetched_at" in set_sql


def test_alembic_revision_ids_fit_version_column():
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    for path in versions.glob("*.py"):
        values = {}
        for node in ast.parse(path.read_text()).body:
            target = node.target if isinstance(node, ast.AnnAssign) else None
            if target is not None and getattr(target, "id", None) in ("revision", "down_revision"):
                values[target.id] = ast.literal_eval(node.value)
        revisions[values["revision"]] = values.get("down_revision")
    assert revisions
    assert all(len(revision) <= 32 for revision in revisions)
    assert revisions["0011_season_source_external_ids"] == "0010_player_two_way"


def test_one_fresh_response_does_not_hide_stale_rest():
    snapshot, identity, kwargs = _world()
    for team in snapshot["roster_fetched_at"]:
        snapshot["roster_fetched_at"][team] = "2026-11-01T00:00:00+00:00"
    for pid, entry in snapshot["stats"].items():
        entry["fetched_at_utc"] = "2026-11-01T00:00:00+00:00"
    snapshot["stats"][1000]["fetched_at_utc"] = FETCHED
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert _has(plan, "30 roster and 389 stat responses")


def test_bad_timestamps_are_problems():
    snapshot, identity, kwargs = _world()
    snapshot["stats"][1000]["fetched_at_utc"] = "not a time"
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "unparseable fetched_at_utc")
    snapshot, identity, kwargs = _world()
    snapshot["roster_fetched_at"][1] = None
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "unparseable fetched_at_utc")


# ---------- stat outcomes and manifest reconciliation ----------

def test_athletes_without_stat_outcome_are_refused():
    snapshot, identity, kwargs = _world(drop_stats={1000, 1001})
    snapshot["manifest"]["counts"]["validated_stats"] = 388
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert _has(plan, "2 roster athletes have no stat response and no recorded 404")


def test_stat_response_with_404_entry_is_refused():
    snapshot, identity, kwargs = _world()
    snapshot["manifest"]["missing_stats"] = [{"provider_id": 1000, "status": 404}]
    snapshot["manifest"]["counts"]["missing_stats"] = 1
    assert _has(ie.build_plan(snapshot, identity, **kwargs), "both a stat response and a recorded 404")


def test_non_404_and_off_roster_missing_entries_are_refused():
    snapshot, identity, kwargs = _world(missing_404={1000})
    snapshot["manifest"]["missing_stats"] = [{"provider_id": 1000, "status": 500}, {"provider_id": 5, "status": 404}]
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert _has(plan, "not HTTP 404") and _has(plan, "not on the roster")


@pytest.mark.parametrize("name", ["roster_athletes", "validated_stats", "missing_stats", "none_played"])
def test_manifest_count_mismatch_is_refused(name):
    snapshot, identity, kwargs = _world()
    snapshot["manifest"]["counts"][name] += 1
    assert _has(ie.build_plan(snapshot, identity, **kwargs), f"manifest counts.{name}")


# ---------- older snapshot never overwrites newer data ----------

NEWER = datetime(2026, 11, 17, tzinfo=timezone.utc)
ROSTER_AT = datetime(2026, 11, 16, 0, 30, tzinfo=timezone.utc)
STAT_AT = datetime(2026, 11, 16, 1, tzinfo=timezone.utc)


def test_older_assignment_is_refused_and_equal_is_accepted():
    plan = _plan(stored_team_times={9_001_000: NEWER})
    assert _has(plan, "1 team assignments are older than stored")
    assert not _plan(stored_team_times={9_001_000: ROSTER_AT}).problems
    assert not _plan(stored_team_times={9_001_000: ROSTER_AT.replace(tzinfo=None)}).problems


def test_older_departed_clear_is_refused():
    snapshot, identity, kwargs = _world()
    kwargs["existing_assignments"] = kwargs["existing_assignments"] + [(7_777_777, "Gone Guy", 5)]
    assert _plan((snapshot, identity, kwargs), stored_team_times={7_777_777: ROSTER_AT}).problems == []
    plan = _plan((snapshot, identity, kwargs), stored_team_times={7_777_777: NEWER})
    assert _has(plan, "1 departed-player clears are older")


def test_older_stat_row_is_refused_and_equal_is_accepted():
    plan = _plan(existing_season_rows={9_001_000: ("espn", NEWER)})
    assert _has(plan, "1 stat rows are older than the stored ESPN row")
    assert not _plan(existing_season_rows={9_001_000: ("espn", STAT_AT)}).problems


def test_write_guards_reference_timestamp_columns():
    snapshot, identity, kwargs = _world()
    kwargs["existing_assignments"] = kwargs["existing_assignments"] + [(7_777_777, "Gone Guy", 5)]
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assign, departed, _, seasons = _applied(plan).writes()
    assert "players.current_team_updated_at <= excluded.current_team_updated_at" in _sql(assign)
    assert "players.current_team_updated_at IS NULL" in _sql(assign)
    assert "players.current_team_updated_at <=" in _sql(departed)
    assert "player_seasons.source_fetched_at <= excluded.source_fetched_at" in _sql(seasons)
    assert "player_seasons.source_fetched_at IS NULL" in _sql(seasons)


def test_stat_rows_carry_no_team_but_upsert_still_sets_it():
    plan = _plan()
    assert all(row["team_id"] is None for row in plan.stat_rows)
    assert "team_id = excluded.team_id" in _sql_set(ie.espn_season_upsert(plan.stat_rows))
    assert "by_roster_team" in plan.to_dict()["stats"]


def test_departed_clear_is_bounded_by_oldest_roster_time():
    snapshot, identity, kwargs = _world()
    snapshot["roster_fetched_at"][1] = "2026-11-16T00:00:00+00:00"
    snapshot["roster_fetched_at"][2] = "2026-11-16T02:00:00+00:00"
    oldest = datetime(2026, 11, 16, 0, tzinfo=timezone.utc)
    kwargs["existing_assignments"] = kwargs["existing_assignments"] + [(7_777_777, "Gone Guy", 1)]

    refused = ie.build_plan(snapshot, identity, **{**kwargs, "stored_team_times": {7_777_777: oldest + timedelta(hours=1)}})
    assert _has(refused, "1 departed-player clears are older")

    older = ie.build_plan(snapshot, identity, **{**kwargs, "stored_team_times": {7_777_777: oldest - timedelta(hours=1)}})
    assert older.problems == [] and older.departed_updated_at == oldest

    equal = ie.build_plan(snapshot, identity, **{**kwargs, "stored_team_times": {7_777_777: oldest}})
    assert equal.problems == []

    clear = [s for s in _applied(older).writes() if isinstance(s, Update)][0]
    assert oldest in clear.compile(dialect=postgresql.dialect()).params.values()


def test_departed_updated_at_is_none_when_any_roster_time_is_bad_and_no_clear_is_issued():
    snapshot, identity, kwargs = _world()
    snapshot["roster_fetched_at"][1] = "garbage"
    kwargs["existing_assignments"] = kwargs["existing_assignments"] + [(7_777_777, "Gone Guy", 1)]
    plan = ie.build_plan(snapshot, identity, **kwargs)
    assert plan.departed_updated_at is None and plan.departed and not plan.complete
    assert not [s for s in _applied(plan).writes() if isinstance(s, Update)]
