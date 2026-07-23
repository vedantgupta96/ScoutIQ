from pathlib import Path

from scoutiq.etl.check_availability_coverage import _match_identities
from scoutiq.sources import nba_injury_reports as inj
from scoutiq.sources.nba_injury_reports import (
    edition_effective_utc,
    fetch_edition,
    normalize_name,
    parse_edition_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "availability"
EDITION_TEXT = (FIXTURES / "edition_text.txt").read_text(encoding="utf-8")
S3_ABSENT_XML = (FIXTURES / "s3_absent.xml").read_text(encoding="utf-8")


class _FakePlayer:
    def __init__(self, player_id: int, full_name: str):
        self.player_id = player_id
        self.full_name = full_name


class _FakeTeam:
    def __init__(self, name: str):
        self.name = name


def _parse_fixture():
    return parse_edition_text(
        EDITION_TEXT,
        edition_effective_utc="2024-01-15T22:45:00+00:00",
        source_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2024-01-15_05PM.pdf",
        known_teams=("Fake Rockets",),
    )


def test_parses_rows_from_fixture_text():
    rows, summary = _parse_fixture()

    assert summary.rows_parsed == 3
    assert summary.unparseable_lines == 0
    assert [r.player_name for r in rows] == ["Doe, Jane", "Smith, Chris", "Unknownperson, Zed"]
    assert all(r.team == "Fake Rockets" for r in rows)
    assert all(r.matchup == "AAA@BBB" for r in rows)
    assert all(r.game_date == "01/15/2024" for r in rows)


def test_status_and_reason_are_preserved_verbatim():
    rows, _ = _parse_fixture()
    jane = next(r for r in rows if r.player_name == "Doe, Jane")

    assert jane.status == "Out"
    assert jane.reason == "Injury/Illness - Left Knee; Sprain"


def test_both_provenance_timestamps_are_carried_on_every_row():
    rows, _ = _parse_fixture()
    for row in rows:
        assert row.edition_effective_utc == "2024-01-15T22:45:00+00:00"
        assert row.source_url.endswith("Injury-Report_2024-01-15_05PM.pdf")


# --- B1: edition-token -> UTC parsing ----------------------------------------


def test_edition_effective_utc_parses_legacy_whole_hour_token():
    # 2025-12-20 is EST (UTC-5): 05PM ET -> 22:00 UTC.
    assert edition_effective_utc("2025-12-20", "05PM") == "2025-12-20T22:00:00+00:00"


def test_edition_effective_utc_parses_modern_minute_precision_token():
    # 2026-04-08 is EDT (UTC-4): 05:30PM ET -> 21:30 UTC.
    assert edition_effective_utc("2026-04-08", "05_30PM") == "2026-04-08T21:30:00+00:00"


def test_edition_effective_utc_parses_modern_am_token():
    # 2026-02-11 is EST (UTC-5): 11:30AM ET -> 16:30 UTC.
    assert edition_effective_utc("2026-02-11", "11_30AM") == "2026-02-11T16:30:00+00:00"


def test_edition_effective_utc_returns_none_for_unparseable_token():
    assert edition_effective_utc("2026-02-11", "garbage") is None
    assert edition_effective_utc("2026-02-11", "") is None


# --- B3: absent classification is explicitly provisional ---------------------


def test_s3_access_denied_403_is_classified_absent_not_failed(monkeypatch):
    class FakeResponse:
        status_code = 403
        content = S3_ABSENT_XML.encode("utf-8")
        headers = {}

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr(inj.requests, "get", fake_get)

    outcome = fetch_edition("2026-01-05", "05PM", use_cache=False, pause=0)

    assert outcome.status == "absent"
    assert outcome.http_status == 403
    assert outcome.error_type is None
    assert outcome.edition_effective_utc is None
    assert outcome.source_last_modified_utc is None
    assert outcome.fetched_at_utc is not None
    assert outcome.absent_is_provisional is True
    assert outcome.classification_note


def test_transport_failure_is_classified_failed(monkeypatch):
    class Boom(inj.requests.RequestException):
        pass

    def fake_get(url, timeout):
        raise Boom("connection reset")

    monkeypatch.setattr(inj.requests, "get", fake_get)

    outcome = fetch_edition("2025-12-20", "05PM", use_cache=False, pause=0, attempts=2)

    assert outcome.status == "failed"
    assert outcome.attempts == 2
    assert outcome.error_type == "Boom"
    assert outcome.absent_is_provisional is False


# --- B2: failures must be structural, never a crash ---------------------------


def test_html_body_on_200_is_classified_failed_not_a_crash_or_ok(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        content = b"<html><body>Access Denied</body></html>"
        headers = {}

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr(inj.requests, "get", fake_get)

    outcome = fetch_edition("2026-01-05", "05PM", use_cache=False, pause=0, cache_dir=tmp_path)

    assert outcome.status == "failed"
    assert outcome.http_status == 200
    assert outcome.error_type is not None
    assert outcome.error_message is not None
    assert outcome.raw_text is None


def test_server_error_status_is_classified_failed_with_http_status(monkeypatch):
    class FakeResponse:
        status_code = 500
        content = b"internal server error"
        headers = {}

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr(inj.requests, "get", fake_get)

    outcome = fetch_edition("2026-01-05", "05PM", use_cache=False, pause=0, attempts=2)

    assert outcome.status == "failed"
    assert outcome.http_status == 500


# --- B4: three distinct time fields --------------------------------------------


def test_ok_edition_preserves_all_three_distinct_timestamps(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        content = b"%PDF-1.4 fake"
        headers = {"Last-Modified": "Sat, 20 Dec 2025 22:45:09 GMT"}

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr(inj.requests, "get", fake_get)
    monkeypatch.setattr(inj, "_extract_text", lambda raw: EDITION_TEXT)

    outcome = fetch_edition("2025-12-20", "05PM", use_cache=False, pause=0, cache_dir=tmp_path)

    assert outcome.status == "ok"
    # edition_effective_utc: what the filename token claims (05PM ET -> UTC).
    assert outcome.edition_effective_utc == "2025-12-20T22:00:00+00:00"
    # source_last_modified_utc: the response's own Last-Modified header.
    assert outcome.source_last_modified_utc == "2025-12-20T22:45:09+00:00"
    assert outcome.fetched_at_utc is not None
    # All three are distinct concepts and must not collapse into each other.
    assert outcome.edition_effective_utc != outcome.source_last_modified_utc
    assert outcome.source_last_modified_utc != outcome.fetched_at_utc


def test_ok_edition_without_last_modified_header_has_no_source_last_modified(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        content = b"%PDF-1.4 fake"
        headers = {}

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr(inj.requests, "get", fake_get)
    monkeypatch.setattr(inj, "_extract_text", lambda raw: EDITION_TEXT)

    outcome = fetch_edition("2025-12-20", "05PM", use_cache=False, pause=0, cache_dir=tmp_path)

    assert outcome.status == "ok"
    assert outcome.edition_effective_utc == "2025-12-20T22:00:00+00:00"
    assert outcome.source_last_modified_utc is None


def test_cache_hit_has_edition_effective_utc_but_no_source_last_modified(monkeypatch, tmp_path):
    cache_file = tmp_path / "Injury-Report_2025-12-20_05PM.pdf"
    cache_file.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(inj, "_extract_text", lambda raw: EDITION_TEXT)

    outcome = fetch_edition("2025-12-20", "05PM", use_cache=True, pause=0, cache_dir=tmp_path)

    assert outcome.status == "ok"
    assert outcome.source == "cache"
    assert outcome.edition_effective_utc == "2025-12-20T22:00:00+00:00"
    assert outcome.source_last_modified_utc is None


def test_cache_hit_with_unparseable_body_is_classified_failed(monkeypatch, tmp_path):
    cache_file = tmp_path / "Injury-Report_2025-12-20_05PM.pdf"
    cache_file.write_bytes(b"<html><body>Access Denied</body></html>")

    outcome = fetch_edition("2025-12-20", "05PM", use_cache=True, pause=0, cache_dir=tmp_path)

    assert outcome.status == "failed"
    assert outcome.error_type is not None
    assert outcome.source == "cache"


def test_identity_matching_counts_matched_unmatched_and_ambiguous_separately():
    rows, _ = _parse_fixture()
    # Plain (player_id, full_name) tuples and team-name strings — the probe
    # materialises these inside the session so matching never touches the ORM.
    players = [
        (1, "Jane Doe"),
        (2, "Chris Smith"),
        (3, "Chris Smith"),  # deliberate duplicate -> ambiguous for "Smith, Chris"
    ]
    teams = ["Fake Rockets"]

    matches = _match_identities(rows, players, teams)
    by_name = {m.row.player_name: m for m in matches}

    assert by_name["Doe, Jane"].player_match == "matched"
    assert by_name["Doe, Jane"].matched_player_id == 1
    assert by_name["Smith, Chris"].player_match == "ambiguous"
    assert by_name["Smith, Chris"].matched_player_id is None
    assert by_name["Unknownperson, Zed"].player_match == "unmatched"
    assert all(m.team_match == "matched" for m in matches)


def test_normalize_name_strips_accents_and_punctuation():
    assert normalize_name("Nikola Jokić") == "nikola jokic"


def test_default_editions_switch_at_the_2025_12_22_convention_change():
    """The filename token gained minutes on 2025-12-22. Probing one convention across
    both eras makes the other era look absent — which is exactly how an earlier pass of
    this spike wrongly concluded the archive stopped at 2025-12-21."""
    from scoutiq.sources.nba_injury_reports import (
        LEGACY_EDITIONS,
        MODERN_EDITIONS,
        default_editions_for,
        edition_url,
    )

    assert default_editions_for("2025-12-21") == LEGACY_EDITIONS
    assert default_editions_for("2025-12-22") == MODERN_EDITIONS
    assert default_editions_for("2026-04-08") == MODERN_EDITIONS
    assert default_editions_for("2022-01-10") == LEGACY_EDITIONS

    # The URL builder passes the token through verbatim for both eras.
    assert edition_url("2025-12-19", "05PM").endswith("Injury-Report_2025-12-19_05PM.pdf")
    assert edition_url("2026-04-08", "05_30PM").endswith("Injury-Report_2026-04-08_05_30PM.pdf")


# --- B5: hyphenated-surname truncation is silent, not counted as unparseable --


def test_hyphenated_surname_truncation_is_flagged_separately_from_unparseable():
    text = (
        "01/15/2024 07:00 (ET) AAA@BBB Fake Rockets "
        "Caldwell- Pope, Kentavious Out Injury/Illness - Right Knee; Soreness "
        "Doe, Jane Questionable Injury/Illness - Ankle; Soreness"
    )

    rows, summary = parse_edition_text(text, known_teams=("Fake Rockets",))

    assert [r.player_name for r in rows] == ["Pope, Kentavious", "Doe, Jane"]
    # The truncated row still parses "successfully" (wrong name, but a complete
    # match) — it must not be counted as an unparseable line.
    assert summary.unparseable_lines == 0
    assert summary.suspected_truncated_names == 1
