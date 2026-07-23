"""Offline tests for the tracking/hustle coverage spike (issue #94).

Everything here runs against the sanitized fixtures in tests/fixtures/tracking/ — no
network calls, no DB writes. The source adapter is monkeypatched at the fetch_family
seam so the probe logic (join rate, null rate, failure handling) is exercised without
ever importing nba_api's network path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scoutiq.etl import check_tracking_coverage as probe
from scoutiq.sources.nba_tracking import FetchOutcome

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "tracking"

# Fake ScoutIQ player_ids — 201001..201004 match fixture rows; 999999 deliberately does not.
KNOWN_PLAYER_IDS = {201001, 201002, 201003, 201004, 201005}


def _load_fixture(name: str) -> pd.DataFrame:
    payload = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return pd.DataFrame(payload)


def test_join_rate_counts_unmatched_ids_separately():
    frame = _load_fixture("hustle")
    result = probe.join_rate(frame, "PLAYER_ID", KNOWN_PLAYER_IDS)
    assert result["total_rows"] == 6
    assert result["matched"] == 5
    assert result["unmatched_count"] == 1
    assert result["unmatched_ids"] == [999999]
    assert result["join_rate"] == pytest.approx(5 / 6)


def test_join_rate_defense_family_uses_close_def_person_id():
    frame = _load_fixture("defense")
    result = probe.join_rate(frame, "CLOSE_DEF_PERSON_ID", KNOWN_PLAYER_IDS)
    assert result["matched"] == 4
    assert result["unmatched_ids"] == [999999]


def test_null_rate_computed_per_field():
    frame = _load_fixture("hustle")
    rates = probe.null_rates(frame)
    assert rates["DEFLECTIONS"] == pytest.approx(1 / 6)
    assert rates["CHARGES_DRAWN"] == pytest.approx(1 / 6)
    assert rates["PLAYER_ID"] == 0.0


def test_null_rate_respects_sample_size():
    frame = _load_fixture("tracking_drives")
    rates = probe.null_rates(frame, sample_size=2)
    assert rates["DRIVE_FG_PCT"] == pytest.approx(0.5)  # row 0 has a value, row 1 is null


def test_failed_outcome_reported_as_failure_not_fabricated(monkeypatch):
    def fake_fetch_family(family, season, **kwargs):
        return FetchOutcome(
            family=family,
            season=season,
            measure_type=kwargs.get("measure_type"),
            ok=False,
            rows=0,
            source="live",
            http_status=429,
            error_type="ReadTimeout",
            error_message="simulated timeout",
            attempts=3,
            elapsed_s=1.23,
            fetched_at_utc="2026-01-01T00:00:00+00:00",
            frame=None,
        )

    monkeypatch.setattr(probe, "fetch_family", fake_fetch_family)
    monkeypatch.setattr(probe, "_known_player_ids", lambda session: KNOWN_PLAYER_IDS)
    monkeypatch.setattr(probe, "get_session", _fake_get_session)

    args = probe.build_arg_parser().parse_args(["--season", "2024-25", "--json"])
    summary = probe.run(args)

    assert summary["any_failure"] is True
    for entry in summary["results"]:
        assert entry["ok"] is False
        assert entry["join"] is None
        assert entry["null_rates"] is None
        assert entry["rows"] == 0


def test_cache_hit_never_touches_network(monkeypatch, tmp_path):
    from scoutiq.sources import nba_tracking

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    fixture = _load_fixture("hustle")
    cache_path = nba_tracking._cache_path(cache_dir, "hustle", "2024-25", None)
    nba_tracking._write_cache(cache_path, fixture)

    def _boom(*args, **kwargs):
        raise AssertionError("network endpoint should never be called on a cache hit")

    monkeypatch.setattr(nba_tracking.leaguehustlestatsplayer, "LeagueHustleStatsPlayer", _boom)

    outcome = nba_tracking.fetch_family("hustle", "2024-25", use_cache=True, cache_dir=cache_dir)

    assert outcome.ok is True
    assert outcome.source == "cache"
    assert outcome.rows == len(fixture)


def test_cli_arg_parser_builds():
    parser = probe.build_arg_parser()
    args = parser.parse_args(
        [
            "--season",
            "2024-25",
            "--season",
            "2023-24",
            "--measure-types",
            "Drives,Passing",
            "--sample-size",
            "50",
            "--cache-dir",
            "/tmp/whatever",
            "--no-cache",
            "--pause",
            "2.0",
            "--timeout",
            "30",
            "--json",
        ]
    )
    assert args.season == ["2024-25", "2023-24"]
    assert args.measure_types == "Drives,Passing"
    assert args.sample_size == 50
    assert args.no_cache is True
    assert args.pause == 2.0
    assert args.timeout == 30
    assert args.json is True


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_get_session():
    return _FakeSession()


def test_join_rate_denominator_is_all_sampled_rows_not_just_rows_with_ids():
    """A sample of one matching id + one null id must not read as 100%.

    Regression for a review finding: dividing matches by only the id-bearing rows
    overstated coverage while the printed total said 1/2.
    """
    import pandas as pd
    from scoutiq.etl.check_tracking_coverage import join_rate

    frame = pd.DataFrame({"PLAYER_ID": [201939, None]})
    stats = join_rate(frame, "PLAYER_ID", {201939})

    assert stats["total_rows"] == 2
    assert stats["rows_with_id"] == 1
    assert stats["rows_missing_id"] == 1
    assert stats["matched"] == 1
    # Over ALL sampled rows, not just the id-bearing subset.
    assert stats["join_rate"] == 0.5
    # The id-present subset is reported separately rather than hidden.
    assert stats["match_rate_where_id_present"] == 1.0
    assert stats["id_presence_rate"] == 0.5


def test_qualified_sample_uses_minutes_and_flags_when_it_cannot():
    """head(N) is endpoint ordering, not a rotation-player sample."""
    import pandas as pd
    from scoutiq.etl.check_tracking_coverage import qualified_sample

    frame = pd.DataFrame({"PLAYER_ID": [1, 2, 3], "MIN": [50, 900, 400]})
    sample, meta = qualified_sample(frame, sample_size=2, min_minutes=200)
    assert meta["qualified"] is True
    assert meta["minutes_column"] == "MIN"
    # Sub-threshold row excluded; highest minutes first.
    assert sample["PLAYER_ID"].tolist() == [2, 3]

    no_min = pd.DataFrame({"PLAYER_ID": [1, 2, 3]})
    sample2, meta2 = qualified_sample(no_min, sample_size=2, min_minutes=200)
    assert meta2["qualified"] is False
    assert "NOT a qualified" in meta2["note"]
    assert len(sample2) == 2
