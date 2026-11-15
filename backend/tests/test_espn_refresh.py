"""Offline contracts for the source-only ESPN refresh collector."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scoutiq.etl import collect_espn_refresh as collector
from scoutiq.sources import espn


ABBREVIATIONS = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS", "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NO", "NY", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SA", "TOR", "UTAH", "WSH"]
CANONICAL = [espn.ESPN_TEAM_ALIASES.get(name, name) for name in ABBREVIATIONS]


def _stats(athlete_id=1, gp=1, pct=50.0):
    base = "http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
    return {"$ref": f"{base}/seasons/2027/types/2/athletes/{athlete_id}/statistics/0?lang=en",
            "season": {"$ref": f"{base}/seasons/2027?lang=en"},
            "athlete": {"$ref": f"{base}/seasons/2027/athletes/{athlete_id}?lang=en"},
            "splits": {"id": "0", "type": "total", "categories": [{"stats": [
                {"name": "gamesPlayed", "value": gp}, {"name": "minutes", "value": 12.0},
                {"name": "points", "value": 8.0}, {"name": "totalRebounds", "value": 3.0},
                {"name": "offensiveRebounds", "value": 1.0}, {"name": "defensiveRebounds", "value": 2.0},
                {"name": "assists", "value": 2.0}, {"name": "steals", "value": 1.0},
                {"name": "blocks", "value": 1.0}, {"name": "turnovers", "value": 1.0},
                {"name": "fouls", "value": 2.0}, {"name": "gamesStarted", "value": 1.0},
                {"name": "fieldGoalsMade", "value": 3.0}, {"name": "fieldGoalsAttempted", "value": 6.0},
                {"name": "threePointFieldGoalsMade", "value": 1.0},
                {"name": "threePointFieldGoalsAttempted", "value": 3.0},
                {"name": "freeThrowsMade", "value": 1.0}, {"name": "freeThrowsAttempted", "value": 2.0},
                {"name": "fieldGoalPct", "value": pct}, {"name": "threePointFieldGoalPct", "value": 33.0},
                {"name": "freeThrowPct", "value": 50.0}, {"name": "usageRate", "value": 0.0},
                {"name": "vorp", "value": 0.0}]}]}}


def _teams_payload():
    return {"sports": [{"leagues": [{"teams": [
        {"team": {"id": str(index), "abbreviation": abbreviation, "displayName": abbreviation}}
        for index, abbreviation in enumerate(ABBREVIATIONS, 1)
    ]}]}]}


def _roster(team_id: int):
    start = team_id * 1000
    return {"season": {"year": 2027, "displayName": "2026-27", "type": 2}, "team": {"id": str(team_id)},
            "athletes": [{"id": str(start + index), "fullName": f"Player {team_id} {index}", "dateOfBirth": "2000-01-01T00:00Z"}
                         for index in range(12)]}


class _CollectorClient:
    def __init__(self, *, stat_status: dict[int, int] | None = None, invalid_stats: set[int] | None = None,
                 halt_teams: bool = False):
        self.calls = []
        self.stat_status = stat_status or {}
        self.invalid_stats = invalid_stats or set()
        self.halt_teams = halt_teams

    def get_json(self, url):
        self.calls.append(url)
        metadata = {"url": url, "fetched_at_utc": "2026-11-14T00:00:00+00:00", "attempts": 1, "status": 200}
        if url.endswith("/teams"):
            if self.halt_teams:
                return None, {**metadata, "status": 403, "halt": True, "error": "HTTP 403"}
            return _teams_payload(), metadata
        if "/roster?" in url:
            team_id = int(urlparse(url).path.split("/")[-2])
            assert parse_qs(urlparse(url).query) == {"season": ["2027"]}
            return _roster(team_id), metadata
        athlete_id = int(urlparse(url).path.split("/")[-3])
        status = self.stat_status.get(athlete_id, 200)
        if status != 200:
            return None, {**metadata, "status": status, "error": f"HTTP {status}"}
        payload = _stats(athlete_id)
        if athlete_id in self.invalid_stats:
            payload["splits"]["type"] = "average"
        return payload, metadata


def _patch_teams(monkeypatch):
    monkeypatch.setattr(espn.nba, "team_rows", lambda: [
        {"team_id": index, "abbreviation": abbreviation} for index, abbreviation in enumerate(CANONICAL, 1)
    ])


def test_season_requires_the_following_calendar_year():
    assert espn.season_year("2026-27") == 2027
    with pytest.raises(espn.ESPNValidationError):
        espn.season_year("2026-28")


def test_roster_requires_team_identity_and_correct_season():
    team = espn.ESPNTeam(1, "ATL", 1, "Atlanta")
    payload = {"season": {"year": 2027, "displayName": "2026-27", "type": 2}, "athletes": []}
    with pytest.raises(espn.ESPNValidationError, match="team identity"):
        espn.validate_roster(payload, team, "2026-27")


def test_stat_total_uses_exact_values_and_excludes_advanced_placeholders():
    parsed = espn.parse_season_totals(_stats(), 1, "2026-27")
    assert parsed["box"] == {
        "PTS": 8.0, "REB": 3.0, "OREB": 1.0, "DREB": 2.0, "AST": 2.0, "STL": 1.0, "BLK": 1.0,
        "TOV": 1.0, "PF": 2.0, "GS": 1.0, "FGM": 3.0, "FGA": 6.0, "FG3M": 1.0, "FG3A": 3.0,
        "FTM": 1.0, "FTA": 2.0, "FG_PCT": 0.5, "FG3_PCT": 0.33, "FT_PCT": 0.5,
    }
    assert "usageRate" not in parsed["box"] and "vorp" not in parsed["box"]
    with pytest.raises(espn.ESPNValidationError, match="percentage"):
        espn.parse_season_totals(_stats(pct=101), 1, "2026-27")
    wrong = _stats()
    wrong["splits"]["type"] = "average"
    with pytest.raises(espn.ESPNValidationError, match="total split"):
        espn.parse_season_totals(wrong, 1, "2026-27")


def test_stat_total_without_box_score_fields_is_rejected():
    payload = _stats()
    payload["splits"]["categories"][0]["stats"] = [
        {"name": "gamesPlayed", "value": 1}, {"name": "minutes", "value": 12.0},
    ]
    with pytest.raises(espn.ESPNValidationError, match="expected box-score fields"):
        espn.parse_season_totals(payload, 1, "2026-27")


def test_stat_total_missing_one_field_names_it():
    payload = _stats()
    stats = payload["splits"]["categories"][0]["stats"]
    stats[:] = [stat for stat in stats if stat["name"] != "steals"]
    with pytest.raises(espn.ESPNValidationError, match="expected box-score fields.*steals"):
        espn.parse_season_totals(payload, 1, "2026-27")


def test_zero_game_stat_is_explicit_not_a_played_stat():
    payload = _stats(gp=0, pct=0)
    for stat in payload["splits"]["categories"][0]["stats"]:
        stat["value"] = 0
    assert espn.parse_season_totals(payload, 1, "2026-27")["gp"] == 0


def test_identity_requires_unique_normalized_name_and_dob():
    roster = [{"provider_id": 1, "full_name": "Nikola Jokić", "date_of_birth": "1995-02-19"},
              {"provider_id": 2, "full_name": "No DOB", "date_of_birth": None}]
    evidence = [{"nba_id": 7, "name": "Nikola Jokic", "dob": "1995-02-19", "bbref_slug": "jokicni01", "verified": True},
                {"nba_id": 8, "name": "Nikola Jokic", "dob": "1995-02-19", "verified": True}]
    report = collector.reconcile_identity(roster, evidence)
    assert report["counts"] == {"matched": 0, "unmatched": 1, "ambiguous": 1}


class _Response:
    def __init__(self, status): self.status_code = status
    def json(self): return {}


class _Session:
    def __init__(self): self.headers, self.calls = {}, 0
    def get(self, url, timeout): self.calls += 1; return _Response(403)


def test_403_halts_without_retry():
    session = _Session()
    payload, meta = collector.ESPNClient(session, pause=0).get_json("https://example.test")
    assert payload is None and session.calls == 1 and meta["halt"] is True


def test_cli_requires_new_output_dir_and_identity_path():
    with pytest.raises(SystemExit):
        collector.build_arg_parser().parse_args([])
    args = collector.build_arg_parser().parse_args(["--output-dir", "/tmp/espn", "--identity-evidence", "/tmp/evidence.json"])
    assert args.output_dir == Path("/tmp/espn") and args.identity_evidence == Path("/tmp/evidence.json")


def test_collector_rejects_unowned_or_wrong_season_output_directories(tmp_path: Path):
    output = tmp_path / "snapshot"
    output.mkdir()
    (output / "unrelated.txt").write_text("keep")
    with pytest.raises(ValueError, match="nonempty"):
        collector.collect("2026-27", output, rosters_only=True)

    (output / "unrelated.txt").unlink()
    (output / "manifest.json").write_text('{"season": "2025-26", "cache": {}}')
    with pytest.raises(ValueError, match="belongs"):
        collector.collect("2026-27", output, rosters_only=True)


def test_collector_rejects_missing_identity_evidence_before_network(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        collector.collect("2026-27", tmp_path / "snapshot", rosters_only=True,
                          identity_evidence=tmp_path / "missing.json")


def test_cached_response_envelope_preserves_original_timestamp_and_invalid_is_not_reusable(tmp_path: Path):
    path = tmp_path / "stats.json"
    metadata = {"url": "https://example.test/stats", "fetched_at_utc": "2026-11-14T00:00:00+00:00"}
    collector._write_response(path, _stats(), metadata)
    state, cached = collector._cached_valid(path, espn.parse_season_totals, 1, "2026-27")
    assert state == "valid" and cached[2]["fetched_at_utc"] == metadata["fetched_at_utc"]
    path.write_text("{}")
    state, cached = collector._cached_valid(path, espn.parse_season_totals, 1, "2026-27")
    assert state == "invalid" and cached is None


def test_identity_rejects_nonpositive_or_nonintegral_nba_ids():
    roster = [{"provider_id": 1, "full_name": "A Player", "date_of_birth": "2000-01-01"}]
    for nba_id in (0, -1, True, 1.0):
        with pytest.raises(ValueError, match="invalid nba_id"):
            collector.reconcile_identity(roster, [{"nba_id": nba_id, "name": "A Player", "dob": "2000-01-01", "verified": True}])


def test_collect_full_success_rosters_only_and_resume_preserves_response_timestamp(monkeypatch, tmp_path: Path):
    _patch_teams(monkeypatch)
    output = tmp_path / "snapshot"
    first = _CollectorClient()
    result = collector.collect("2026-27", output, client=first)
    assert result["counts"] == {"teams": 30, "validated_roster_teams": 30, "roster_athletes": 360,
                                "validated_stats": 360, "errors": 0, "missing_stats": 0, "none_played": 0}

    class _NoRequestClient:
        def get_json(self, url):
            raise AssertionError(f"cache resume unexpectedly requested {url}")

    resumed = collector.collect("2026-27", output, client=_NoRequestClient())
    assert resumed["counts"]["validated_stats"] == 360
    assert all(entry.get("fetched_at_utc") == "2026-11-14T00:00:00+00:00" for entry in resumed["requests"])

    rosters_only = collector.collect("2026-27", tmp_path / "rosters-only", rosters_only=True, client=_CollectorClient())
    assert rosters_only["counts"]["validated_stats"] == 0 and rosters_only["counts"]["missing_stats"] == 0


def test_collect_classifies_404_500_validation_and_403_halt(monkeypatch, tmp_path: Path):
    _patch_teams(monkeypatch)
    result = collector.collect("2026-27", tmp_path / "failures", client=_CollectorClient(
        stat_status={1000: 404, 1001: 500}, invalid_stats={1002}))
    assert any(row["provider_id"] == 1000 for row in result["missing_stats"])
    assert any(row.get("provider_id") == 1001 and row["kind"] == "stats" for row in result["errors"])
    assert any(row.get("provider_id") == 1002 and row["kind"] == "stats_validation" for row in result["errors"])

    halted_client = _CollectorClient(halt_teams=True)
    halted = collector.collect("2026-27", tmp_path / "halted", client=halted_client)
    assert halted["errors"][0]["halt"] is True and len(halted_client.calls) == 1


def test_interrupted_after_first_envelope_resumes_with_its_timestamp(monkeypatch, tmp_path: Path):
    _patch_teams(monkeypatch)

    class _InterruptedClient(_CollectorClient):
        def get_json(self, url):
            if self.calls:
                raise RuntimeError("simulated process interruption")
            return super().get_json(url)

    output = tmp_path / "interrupted"
    with pytest.raises(RuntimeError, match="interruption"):
        collector.collect("2026-27", output, rosters_only=True, client=_InterruptedClient())
    assert (output / "manifest.json").exists() and (output / "raw" / "teams.json").exists()
    resumed = collector.collect("2026-27", output, rosters_only=True, client=_CollectorClient())
    teams_request = resumed["requests"][0]
    assert teams_request["source"] == "cache" and teams_request["fetched_at_utc"] == "2026-11-14T00:00:00+00:00"


def test_invalid_cached_response_is_preserved_without_a_network_request(monkeypatch, tmp_path: Path):
    _patch_teams(monkeypatch)
    output = tmp_path / "invalid-cache"
    output.mkdir()
    (output / "manifest.json").write_text('{"season": "2026-27", "cache": {}}')
    raw = output / "raw" / "teams.json"
    raw.parent.mkdir()
    raw.write_text("{}")

    class _NoRequestClient:
        def get_json(self, url):
            raise AssertionError("invalid cache must not be refreshed")

    result = collector.collect("2026-27", output, rosters_only=True, client=_NoRequestClient())
    assert result["errors"][0]["kind"] == "teams_cache_validation"
    assert raw.read_text() == "{}"
