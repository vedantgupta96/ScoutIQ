"""Tests for the data-provenance router.

FakeDB stands in for Postgres (see fakes.py); each dataset query is exercised with a
populated, a partial, and an empty fake, plus a fake that raises for player_valuations
only — proving that dataset's failure degrades independently and never 500s the rest
(docs/adr/0001). We also assert no dataset record ever leaks scout-report/rating text.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from fakes import FakeDB

from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.models import (
    CapConstants,
    Contract,
    ContractYear,
    FreeAgentRight,
    Player,
    PlayerRating,
    PlayerSalary,
    PlayerSeason,
    PlayerValuation,
    ScoutReport,
)


def _dt(*args):
    return datetime(*args, tzinfo=timezone.utc)


PLAYERS = [
    Player(player_id=1, full_name="Player One", current_team_id=10, is_two_way=False,
           current_team_updated_at=_dt(2026, 6, 1)),
    Player(player_id=2, full_name="Player Two", current_team_id=None, is_two_way=True,
           current_team_updated_at=_dt(2026, 5, 1)),
    Player(player_id=3, full_name="Player Three", current_team_id=10, is_two_way=False,
           current_team_updated_at=None),
]

SEASONS = [
    PlayerSeason(player_id=1, season="2023-24", advanced={}),
    PlayerSeason(player_id=1, season="2024-25", advanced={}),
    PlayerSeason(player_id=2, season="2024-25", advanced={}),
]

SALARIES = [
    PlayerSalary(player_id=1, season="2022-23", salary=1_000_000, source="bbref"),
    PlayerSalary(player_id=2, season="2023-24", salary=2_000_000, source="bbref"),
]

CONTRACTS = [
    Contract(id=1, player_id=1, season_start="2024-25", years=2, scraped_at=_dt(2026, 6, 15)),
    Contract(id=2, player_id=2, season_start="2023-24", years=1, scraped_at=_dt(2026, 1, 1)),
]
CONTRACT_YEARS = [
    ContractYear(id=1, contract_id=1, season="2024-25"),
    ContractYear(id=2, contract_id=1, season="2025-26"),
    ContractYear(id=3, contract_id=2, season="2023-24"),
]

CAPS = [
    CapConstants(season="2024-25", salary_cap=1),
    CapConstants(season="2025-26", salary_cap=2),
]

RIGHTS = [
    FreeAgentRight(id=1, player_id=1, entering_season="2025-26", scraped_at=_dt(2026, 4, 1)),
    FreeAgentRight(id=2, player_id=3, entering_season="2026-27", scraped_at=_dt(2026, 5, 1)),
]

SCOUT_REPORTS = [
    ScoutReport(report_id="r1", player_id=1, season="2024-25", source_label="Perplexity Sonar",
                source_text="SECRET NARRATIVE ONE", citations=["http://example.com/a"],
                fetched_at=_dt(2026, 3, 1)),
    ScoutReport(report_id="r2", player_id=2, season="2025-26", source_label="Perplexity Sonar",
                source_text="SECRET NARRATIVE TWO", citations=None, fetched_at=_dt(2026, 3, 15)),
]
PLAYER_RATINGS = [
    PlayerRating(id=1, report_id="r1", player_id=1, trait="leadership", score=4, confidence="high",
                 evidence_span="SECRET EVIDENCE SPAN ONE"),
    PlayerRating(id=2, report_id="r2", player_id=2, trait="motor", score=3, confidence="medium",
                 evidence_span="SECRET EVIDENCE SPAN TWO"),
    PlayerRating(id=3, report_id="r1", player_id=1, trait="shooting", score=5, confidence="high",
                 evidence_span="SECRET EVIDENCE SPAN THREE"),
]

VALUATIONS = [
    PlayerValuation(id=1, player_id=1, season="2024-25", value_pct=50, lo_pct=40, hi_pct=60,
                     verdict_label="fair", verdict_tone="neutral", model_version="v1",
                     computed_at=_dt(2026, 7, 1)),
    PlayerValuation(id=2, player_id=2, season="2025-26", value_pct=60, lo_pct=50, hi_pct=70,
                     verdict_label="fair", verdict_tone="neutral", model_version="v1",
                     computed_at=_dt(2026, 7, 10)),
]


class _ExplodingValuationsDB(FakeDB):
    """Everything works except player_valuations — simulates the valuation store being
    unavailable (ADR-0001) without touching the shared FakeDB's normal behavior."""

    def scalars(self, stmt):
        if "player_valuations" in str(stmt):
            raise RuntimeError("valuation store unavailable")
        return super().scalars(stmt)


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _by_key(body):
    return {row["key"]: row for row in body["datasets"]}


def _populated_db():
    return FakeDB(
        players=PLAYERS,
        seasons=SEASONS,
        salaries=SALARIES,
        caps=CAPS,
        contracts=CONTRACTS,
        contract_years=CONTRACT_YEARS,
        rights=RIGHTS,
        scout_reports=SCOUT_REPORTS,
        player_ratings=PLAYER_RATINGS,
        valuations=VALUATIONS,
    )


def test_data_provenance_populated_db_reports_counts_seasons_and_timestamps():
    resp = _client(_populated_db()).get("/data-provenance")
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
    assert ps["last_updated_basis"] is None

    sal = rows["player_salaries"]
    assert sal["record_count"] == 2
    assert sal["player_count"] == 2
    assert sal["last_updated_utc"] is None

    con = rows["contracts"]
    assert con["record_count"] == 3
    assert con["player_count"] == 2
    assert con["season_count"] == 3
    assert con["earliest_season"] == "2023-24"
    assert con["latest_season"] == "2025-26"
    assert con["last_updated_utc"] == _dt(2026, 6, 15).isoformat()
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
    assert far["last_updated_utc"] == _dt(2026, 5, 1).isoformat()
    assert far["last_updated_basis"] == "free_agent_rights.scraped_at"

    rosters = rows["rosters"]
    assert rosters["record_count"] == 2  # players with current_team_id set
    assert rosters["player_count"] == 2
    assert rosters["last_updated_utc"] == _dt(2026, 6, 1).isoformat()
    assert rosters["last_updated_basis"] == "players.current_team_updated_at"

    two_way = rows["two_way_status"]
    assert two_way["record_count"] == 1  # players flagged is_two_way
    assert two_way["player_count"] == 3  # total players considered
    assert two_way["last_updated_utc"] is None
    assert two_way["last_updated_basis"] is None
    assert "unloaded" in two_way["caveat"]

    sr = rows["scout_reports"]
    assert sr["record_count"] == 2
    assert sr["player_count"] == 2
    assert sr["season_count"] == 2
    assert sr["last_updated_utc"] == _dt(2026, 3, 15).isoformat()
    assert sr["last_updated_basis"] == "scout_reports.fetched_at"
    assert "3" in sr["caveat"]  # rating count called out explicitly

    val = rows["player_valuations"]
    assert val["record_count"] == 2
    assert val["player_count"] == 2
    assert val["earliest_season"] == "2024-25"
    assert val["latest_season"] == "2025-26"
    assert val["last_updated_utc"] == _dt(2026, 7, 10).isoformat()
    assert val["last_updated_basis"] == "player_valuations.computed_at"


def test_data_provenance_partial_db_shows_zero_or_null_without_crashing():
    fake = FakeDB(players=PLAYERS, seasons=SEASONS)
    resp = _client(fake).get("/data-provenance")
    assert resp.status_code == 200
    rows = _by_key(resp.json())

    assert rows["player_seasons"]["record_count"] == 3

    for key in ("player_salaries", "contracts", "cap_constants", "free_agent_rights", "scout_reports", "player_valuations"):
        row = rows[key]
        assert row["record_count"] == 0
        assert row["last_updated_utc"] is None
        assert row["caveat"]

    rosters = rows["rosters"]
    assert rosters["record_count"] == 2
    assert rosters["player_count"] == 2
    assert rosters["last_updated_utc"] == _dt(2026, 6, 1).isoformat()

    two_way = rows["two_way_status"]
    assert two_way["record_count"] == 1
    assert two_way["player_count"] == 3
    assert two_way["last_updated_utc"] is None


def test_data_provenance_empty_db_returns_all_zero_or_null():
    resp = _client(FakeDB()).get("/data-provenance")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["datasets"]) == 9

    for row in body["datasets"]:
        assert row["record_count"] == 0
        assert row["last_updated_utc"] is None
        assert row["last_updated_basis"] is None
        assert row["caveat"]


def test_data_provenance_missing_valuation_data_degrades_independently():
    resp = _client(_ExplodingValuationsDB(
        players=PLAYERS,
        seasons=SEASONS,
        salaries=SALARIES,
        caps=CAPS,
        contracts=CONTRACTS,
        contract_years=CONTRACT_YEARS,
        rights=RIGHTS,
        scout_reports=SCOUT_REPORTS,
        player_ratings=PLAYER_RATINGS,
        valuations=VALUATIONS,
    )).get("/data-provenance")
    assert resp.status_code == 200
    rows = _by_key(resp.json())

    val = rows["player_valuations"]
    assert val["record_count"] is None
    assert val["player_count"] is None
    assert val["last_updated_utc"] is None
    assert "unavailable" in val["caveat"]

    # Every other dataset is unaffected by the valuations failure.
    assert rows["player_seasons"]["record_count"] == 3
    assert rows["contracts"]["record_count"] == 3
    assert rows["scout_reports"]["record_count"] == 2
    assert rows["rosters"]["record_count"] == 2
    assert rows["two_way_status"]["record_count"] == 1


def test_data_provenance_never_leaks_report_bodies_or_evidence_text():
    resp = _client(_populated_db()).get("/data-provenance")
    raw = resp.text

    for leaked in (
        "SECRET NARRATIVE ONE",
        "SECRET NARRATIVE TWO",
        "SECRET EVIDENCE SPAN ONE",
        "SECRET EVIDENCE SPAN TWO",
        "SECRET EVIDENCE SPAN THREE",
        "example.com/a",
        '"source_text"',
        '"evidence_span"',
        '"citations"',
    ):
        assert leaked not in raw
