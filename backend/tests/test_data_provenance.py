"""Tests for the data-provenance router.

Uses a real (SQLite, in-memory) Session — see provenance_db.py — rather than
FakeDB: FakeDB loads Python row lists and can't exercise SQL aggregates (COUNT/MIN/
MAX/GROUP BY), real source-column grouping, or SAVEPOINT-based degradation, which is
why those bugs shipped past FakeDB-backed tests before. Sources are seeded mixed
(contracts: spotrac + bbref_contracts; rosters: nba_api) so the source strings are
provably read from the data, not hardcoded. We also assert no dataset record ever
leaks scout-report/rating text, and that a per-dataset query failure degrades only
that dataset (docs/adr/0001) without poisoning the shared transaction.
"""
from datetime import datetime, timezone

import scoutiq.api.routers.data_provenance as data_provenance
from fastapi.testclient import TestClient

from provenance_db import make_session, seed

from scoutiq.api.deps import get_db
from scoutiq.api.main import app


def _dt(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _by_key(body):
    return {row["key"]: row for row in body["datasets"]}


def _populated_session():
    db = make_session()
    seed(db, table="players", rows=[
        {"player_id": 1, "current_team_id": 10, "current_team_source": "nba_api.commonallplayers:2025-26",
         "current_team_updated_at": _dt(2026, 6, 1), "is_two_way": False},
        {"player_id": 2, "current_team_id": None, "current_team_source": None,
         "current_team_updated_at": _dt(2026, 5, 1), "is_two_way": True},
        {"player_id": 3, "current_team_id": 10, "current_team_source": "nba_api.commonallplayers:2025-26",
         "current_team_updated_at": None, "is_two_way": False},
        {"player_id": 4, "current_team_id": 20, "current_team_source": "nba_api.commonallplayers:2025-26",
         "current_team_updated_at": _dt(2026, 6, 20), "is_two_way": True},
    ])
    seed(db, table="player_seasons", rows=[
        {"id": 1, "player_id": 1, "season": "2023-24"},
        {"id": 2, "player_id": 1, "season": "2024-25"},
        {"id": 3, "player_id": 2, "season": "2024-25"},
    ])
    seed(db, table="player_salaries", rows=[
        {"id": 1, "player_id": 1, "season": "2022-23", "source": "bbref"},
        {"id": 2, "player_id": 2, "season": "2023-24", "source": "bbref"},
    ])
    seed(db, table="contracts", rows=[
        {"id": 1, "player_id": 1, "source": "spotrac", "scraped_at": _dt(2026, 6, 15)},
        {"id": 2, "player_id": 2, "source": "bbref_contracts", "scraped_at": _dt(2026, 1, 1)},
        {"id": 3, "player_id": 3, "source": "spotrac", "scraped_at": _dt(2026, 7, 1)},
    ])
    seed(db, table="contract_years", rows=[
        {"id": 1, "contract_id": 1, "season": "2024-25"},
        {"id": 2, "contract_id": 1, "season": "2025-26"},
        {"id": 3, "contract_id": 2, "season": "2023-24"},
        {"id": 4, "contract_id": 3, "season": "2025-26"},
    ])
    seed(db, table="cap_constants", rows=[
        {"season": "2024-25"},
        {"season": "2025-26"},
    ])
    seed(db, table="free_agent_rights", rows=[
        {"id": 1, "player_id": 1, "entering_season": "2025-26", "source": "spotrac", "scraped_at": _dt(2026, 4, 1)},
        {"id": 2, "player_id": 3, "entering_season": "2026-27", "source": "spotrac", "scraped_at": _dt(2026, 5, 1)},
    ])
    seed(db, table="scout_reports", rows=[
        {"report_id": "r1", "player_id": 1, "season": "2024-25", "source_label": "Perplexity Sonar",
         "fetched_at": _dt(2026, 3, 1)},
        {"report_id": "r2", "player_id": 2, "season": "2025-26", "source_label": "Perplexity Sonar",
         "fetched_at": _dt(2026, 3, 15)},
    ])
    seed(db, table="player_ratings", rows=[
        {"id": 1, "report_id": "r1", "player_id": 1},
        {"id": 2, "report_id": "r2", "player_id": 2},
        {"id": 3, "report_id": "r1", "player_id": 1},
    ])
    seed(db, table="player_valuations", rows=[
        {"id": 1, "player_id": 1, "season": "2024-25", "computed_at": _dt(2026, 7, 1), "model_version": "v1"},
        {"id": 2, "player_id": 2, "season": "2025-26", "computed_at": _dt(2026, 7, 10), "model_version": "v1"},
        {"id": 3, "player_id": 1, "season": "2025-26", "computed_at": _dt(2026, 7, 15), "model_version": "v2"},
    ])
    return db


def test_data_provenance_populated_db_reports_counts_seasons_sources_and_timestamps():
    resp = _client(_populated_session()).get("/data-provenance")
    assert resp.status_code == 200
    body = resp.json()

    assert [row["key"] for row in body["datasets"]] == [
        "player_seasons",
        "player_salaries",
        "contracts",
        "cap_constants",
        "free_agent_rights",
        "rosters",
        "two_way_status",
        "scout_reports",
        "player_valuations",
    ]
    assert body["generated_at_utc"]
    assert body["caveat"]

    rows = _by_key(body)

    ps = rows["player_seasons"]
    assert ps["record_count"] == 3
    assert ps["player_count"] == 2
    assert ps["season_count"] == 2
    assert ps["earliest_season"] == "2023-24"
    assert ps["latest_season"] == "2024-25"
    assert ps["last_updated_utc"] is None

    sal = rows["player_salaries"]
    assert sal["record_count"] == 2
    assert sal["player_count"] == 2
    assert sal["source"] == "bbref (2)"
    assert sal["last_updated_utc"] is None

    con = rows["contracts"]
    assert con["record_count"] == 4
    assert con["player_count"] == 3
    assert con["season_count"] == 3
    assert con["earliest_season"] == "2023-24"
    assert con["latest_season"] == "2025-26"
    assert con["source"] == "spotrac (2), bbref_contracts (1)"
    assert con["last_updated_utc"] == _dt(2026, 7, 1).isoformat()
    assert con["last_updated_basis"] == "contracts.scraped_at"

    cap = rows["cap_constants"]
    assert cap["record_count"] == 2
    assert cap["earliest_season"] == "2024-25"
    assert cap["latest_season"] == "2025-26"
    assert cap["last_updated_utc"] is None

    far = rows["free_agent_rights"]
    assert far["record_count"] == 2
    assert far["player_count"] == 2
    assert far["earliest_season"] == "2025-26"
    assert far["latest_season"] == "2026-27"
    assert far["source"] == "spotrac (2)"
    assert far["last_updated_utc"] == _dt(2026, 5, 1).isoformat()
    assert far["last_updated_basis"] == "free_agent_rights.scraped_at"

    rosters = rows["rosters"]
    assert rosters["record_count"] == 3  # players with current_team_id set
    assert rosters["player_count"] == 3
    assert rosters["source"] == "nba_api.commonallplayers:2025-26 (3)"
    assert "Spotrac" not in rosters["source"]
    assert rosters["last_updated_utc"] == _dt(2026, 6, 20).isoformat()
    assert rosters["last_updated_basis"] == "players.current_team_updated_at"

    two_way = rows["two_way_status"]
    assert two_way["record_count"] == 2  # players flagged is_two_way
    assert two_way["player_count"] == 4  # total players considered
    assert two_way["last_updated_utc"] is None
    assert two_way["last_updated_basis"] is None
    assert "may indicate" in two_way["caveat"]
    assert "flagged true out of all tracked players" in two_way["caveat"]

    sr = rows["scout_reports"]
    assert sr["record_count"] == 2
    assert sr["player_count"] == 2
    assert sr["season_count"] == 2
    assert sr["source"] == "Perplexity Sonar (2)"
    assert sr["last_updated_utc"] == _dt(2026, 3, 15).isoformat()
    assert sr["last_updated_basis"] == "scout_reports.fetched_at"
    assert "3" in sr["caveat"]  # rating count called out explicitly

    val = rows["player_valuations"]
    assert val["record_count"] == 3
    assert val["player_count"] == 2
    assert val["earliest_season"] == "2024-25"
    assert val["latest_season"] == "2025-26"
    assert val["last_updated_utc"] == _dt(2026, 7, 15).isoformat()
    assert val["last_updated_basis"] == "player_valuations.computed_at"
    assert "2 distinct model_version" in val["caveat"]


def test_data_provenance_empty_db_returns_all_zero_or_null():
    resp = _client(make_session()).get("/data-provenance")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["datasets"]) == 9

    for row in body["datasets"]:
        assert row["record_count"] == 0
        assert row["last_updated_utc"] is None
        assert row["last_updated_basis"] is None
        assert row["caveat"]


def test_data_provenance_determinism_ignores_generated_at_utc():
    db = _populated_session()
    client = _client(db)

    first = client.get("/data-provenance").json()
    second = client.get("/data-provenance").json()

    assert first["datasets"] == second["datasets"]
    assert first["caveat"] == second["caveat"]


def test_data_provenance_degrades_one_dataset_without_affecting_others(monkeypatch):
    def boom(db):
        raise RuntimeError("valuation store unavailable")

    monkeypatch.setattr(data_provenance, "_player_valuations", boom)

    resp = _client(_populated_session()).get("/data-provenance")
    assert resp.status_code == 200
    rows = _by_key(resp.json())

    val = rows["player_valuations"]
    assert val["record_count"] is None
    assert val["player_count"] is None
    assert val["last_updated_utc"] is None
    assert "unavailable" in val["caveat"]

    # Every other dataset — including ones queried after player_valuations would
    # have been, in the endpoint's declared order — is unaffected by the failure,
    # proving the SAVEPOINT rolls back only the failing dataset's work.
    assert rows["player_seasons"]["record_count"] == 3
    assert rows["contracts"]["record_count"] == 4
    assert rows["contracts"]["source"] == "spotrac (2), bbref_contracts (1)"
    assert rows["scout_reports"]["record_count"] == 2
    assert rows["rosters"]["record_count"] == 3
    assert rows["two_way_status"]["record_count"] == 2


def test_data_provenance_never_leaks_report_bodies_or_evidence_text():
    resp = _client(_populated_session()).get("/data-provenance")
    raw = resp.text

    for leaked in ('"source_text"', '"evidence_span"', '"citations"', '"stats"', '"features"'):
        assert leaked not in raw
