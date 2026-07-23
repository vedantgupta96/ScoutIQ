"""Official NBA injury-report PDF adapter (availability-ledger spike, issue #95).

Read-only: fetches (with disk cache), classifies, and parses the league's official
Injury Report PDFs. `status`/`reason` text is preserved verbatim — this module makes
no medical, severity, or risk judgment. No DB access here (the probe CLI owns that).

Retrieval semantics: a missing edition returns HTTP 403 with an S3 "AccessDenied" XML
body. That is S3's response for a nonexistent object, not a block — we classify it as
`absent`, distinct from `failed` (timeouts, connection errors, other error statuses). A
403+AccessDenied cannot reliably distinguish "never published" from "access now denied",
so `absent` is reported as an explicitly provisional classification, never a confirmed
archive fact.
"""
from __future__ import annotations

import io
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from pypdf import PdfReader

from scoutiq.config import settings

RAW_DIR = settings.RAW_DIR / "injury_reports"

BASE_URL = "https://ak-static.cms.nba.com/referee/injury"
# The edition token in the filename changed convention on 2025-12-22. Editions up
# to 2025-12-21 use a whole-hour token ("05PM"); from 2025-12-22 they carry minutes
# with an underscore ("05_30PM"), and the modern era publishes many more editions
# per day. Both eras are live and reachable — this is a naming change, not an
# archive cutoff, and probing only one convention makes the other era look absent.
EDITION_CONVENTION_CHANGE_DATE = "2025-12-22"
LEGACY_EDITIONS = ("05PM", "08PM")
MODERN_EDITIONS = ("12_45PM", "05_30PM", "08_30PM")
DEFAULT_EDITIONS = LEGACY_EDITIONS  # kept for back-compat; prefer default_editions_for()


def default_editions_for(date: str) -> tuple[str, ...]:
    """Edition tokens to try for `date`, accounting for the 2025-12-22 rename."""
    return MODERN_EDITIONS if date >= EDITION_CONVENTION_CHANGE_DATE else LEGACY_EDITIONS
DEFAULT_TIMEOUT = 30
DEFAULT_PAUSE = 1.0
DEFAULT_ATTEMPTS = 3

_S3_ACCESS_DENIED = "<Code>AccessDenied</Code>"
_ABSENT_CLASSIFICATION_NOTE = (
    "S3 403 AccessDenied cannot distinguish 'this edition was never published' from "
    "'access to this object is now restricted' — absent is provisional, not a confirmed "
    "archive fact. A sudden jump from mostly-ok to mostly-absent should be treated as a "
    "possible access change, not evidence the archive ended."
)
_last_fetch_ts = 0.0

REPORT_TIMEZONE = ZoneInfo("America/New_York")
_EDITION_TOKEN_RE = re.compile(r"^(\d{1,2})(?:_(\d{2}))?(AM|PM)$")


def _parse_edition_token(edition: str) -> tuple[int, int] | None:
    """Parse an edition filename token into 24-hour (hour, minute), Eastern local time.

    Handles the legacy whole-hour form ('05PM') and the modern minute-precision form
    ('05_30PM', '12_45PM', '11_30AM'). Returns None on anything that doesn't match either
    convention — callers must never guess a time for an unparseable token.
    """
    m = _EDITION_TOKEN_RE.match(edition)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return None
    meridiem = m.group(3)
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return hour, minute


def edition_effective_utc(date: str, edition: str) -> str | None:
    """What this edition claims to be, in UTC: the filename's date + edition token,
    interpreted in the league's publication timezone (US/Eastern — the NBA publishes
    injury reports on ET) and converted to UTC. Returns None if the token cannot be
    parsed, rather than emitting an invalid string."""
    parsed = _parse_edition_token(edition)
    if parsed is None:
        return None
    hour, minute = parsed
    try:
        year, month, day = (int(p) for p in date.split("-"))
        local = datetime(year, month, day, hour, minute, tzinfo=REPORT_TIMEZONE)
    except ValueError:
        return None
    return local.astimezone(timezone.utc).isoformat()

STATUS_VALUES = ("Out", "Doubtful", "Questionable", "Probable", "Available")

# Official NBA team full names as printed in the injury-report PDFs. Used by the
# parser to draw a reliable boundary between a "team header" line and free-text
# reason content — both are otherwise just prose in the extracted text.
NBA_TEAM_NAMES = (
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
    "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
    "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
    "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans",
    "New York Knicks", "Oklahoma City Thunder", "Orlando Magic",
    "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
    "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz",
    "Washington Wizards",
)


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation — for identity-matching against players.full_name."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", norm.lower()).strip()


def edition_url(date: str, edition: str) -> str:
    """date is YYYY-MM-DD; edition is the filename token verbatim — legacy whole-hour
    form ('05PM') for dates before 2025-12-22, modern form ('05_30PM') from then on."""
    return f"{BASE_URL}/Injury-Report_{date}_{edition}.pdf"


def _is_s3_absent(status_code: int, body: bytes) -> bool:
    if status_code != 403:
        return False
    try:
        text = body.decode("utf-8", errors="ignore")
    except Exception:
        return False
    return _S3_ACCESS_DENIED in text


@dataclass(frozen=True)
class EditionOutcome:
    date: str
    edition: str
    url: str
    status: str  # 'ok' | 'absent' | 'failed'
    http_status: int | None
    absent_is_provisional: bool
    classification_note: str | None
    rows: int | None
    error_type: str | None
    error_message: str | None
    attempts: int
    elapsed_s: float
    source: str  # 'cache' | 'live'
    edition_effective_utc: str | None  # what the edition claims to be (filename token, ET->UTC)
    source_last_modified_utc: str | None  # the response's Last-Modified header, if any
    fetched_at_utc: str  # this run's ingestion time
    raw_bytes: int | None
    raw_text: str | None = field(default=None, repr=False)


def _cache_path(date: str, edition: str, cache_dir=None):
    return (cache_dir or RAW_DIR) / f"Injury-Report_{date}_{edition}.pdf"


def fetch_edition(
    date: str,
    edition: str,
    *,
    use_cache: bool = True,
    pause: float = DEFAULT_PAUSE,
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = DEFAULT_ATTEMPTS,
    cache_dir=None,
) -> EditionOutcome:
    """Fetch one edition's PDF and extract its text (not yet parsed into rows).

    Returns an EditionOutcome with `raw_text` populated on `status == 'ok'`, for the
    caller to hand to `parse_edition_text`. Never raises on absence or transport
    failure — those are recorded, not propagated.
    """
    global _last_fetch_ts
    url = edition_url(date, edition)
    fetched_at_utc = datetime.now(timezone.utc).isoformat()
    cache = _cache_path(date, edition, cache_dir)

    if use_cache and cache.exists():
        raw = cache.read_bytes()
        try:
            text = _extract_text(raw)
        except Exception as exc:
            return EditionOutcome(
                date=date,
                edition=edition,
                url=url,
                status="failed",
                http_status=200,
                absent_is_provisional=False,
                classification_note=None,
                rows=None,
                error_type=type(exc).__name__,
                error_message=str(exc),
                attempts=0,
                elapsed_s=0.0,
                source="cache",
                edition_effective_utc=None,
                source_last_modified_utc=None,
                fetched_at_utc=fetched_at_utc,
                raw_bytes=len(raw),
                raw_text=None,
            )
        return EditionOutcome(
            date=date,
            edition=edition,
            url=url,
            status="ok",
            http_status=200,
            absent_is_provisional=False,
            classification_note=None,
            rows=None,
            error_type=None,
            error_message=None,
            attempts=0,
            elapsed_s=0.0,
            source="cache",
            edition_effective_utc=edition_effective_utc(date, edition),
            source_last_modified_utc=None,
            fetched_at_utc=fetched_at_utc,
            raw_bytes=len(raw),
            raw_text=text,
        )

    started = time.monotonic()
    last_exc: Exception | None = None
    last_http_status: int | None = None
    for attempt in range(1, attempts + 1):
        wait = pause - (time.monotonic() - _last_fetch_ts)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            _last_fetch_ts = time.monotonic()
            if attempt < attempts:
                time.sleep(pause * attempt)
            continue
        finally:
            _last_fetch_ts = time.monotonic()

        elapsed = time.monotonic() - started

        if resp.status_code == 200:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(resp.content)
            last_modified = resp.headers.get("Last-Modified")
            source_last_modified_utc = (
                parsedate_to_datetime(last_modified).astimezone(timezone.utc).isoformat()
                if last_modified
                else None
            )
            try:
                text = _extract_text(resp.content)
            except Exception as exc:
                return EditionOutcome(
                    date=date,
                    edition=edition,
                    url=url,
                    status="failed",
                    http_status=200,
                    absent_is_provisional=False,
                    classification_note=None,
                    rows=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    attempts=attempt,
                    elapsed_s=elapsed,
                    source="live",
                    edition_effective_utc=None,
                    source_last_modified_utc=source_last_modified_utc,
                    fetched_at_utc=fetched_at_utc,
                    raw_bytes=len(resp.content),
                    raw_text=None,
                )
            return EditionOutcome(
                date=date,
                edition=edition,
                url=url,
                status="ok",
                http_status=200,
                absent_is_provisional=False,
                classification_note=None,
                rows=None,
                error_type=None,
                error_message=None,
                attempts=attempt,
                elapsed_s=elapsed,
                source="live",
                edition_effective_utc=edition_effective_utc(date, edition),
                source_last_modified_utc=source_last_modified_utc,
                fetched_at_utc=fetched_at_utc,
                raw_bytes=len(resp.content),
                raw_text=text,
            )

        if _is_s3_absent(resp.status_code, resp.content):
            return EditionOutcome(
                date=date,
                edition=edition,
                url=url,
                status="absent",
                http_status=resp.status_code,
                absent_is_provisional=True,
                classification_note=_ABSENT_CLASSIFICATION_NOTE,
                rows=None,
                error_type=None,
                error_message=None,
                attempts=attempt,
                elapsed_s=elapsed,
                source="live",
                edition_effective_utc=None,
                source_last_modified_utc=None,
                fetched_at_utc=fetched_at_utc,
                raw_bytes=len(resp.content),
                raw_text=None,
            )

        last_http_status = resp.status_code
        last_exc = RuntimeError(f"HTTP {resp.status_code}")
        if attempt < attempts:
            time.sleep(pause * attempt)

    elapsed = time.monotonic() - started
    return EditionOutcome(
        date=date,
        edition=edition,
        url=url,
        status="failed",
        http_status=last_http_status,
        absent_is_provisional=False,
        classification_note=None,
        rows=None,
        error_type=type(last_exc).__name__ if last_exc else None,
        error_message=str(last_exc) if last_exc else None,
        attempts=attempts,
        elapsed_s=elapsed,
        source="live",
        edition_effective_utc=None,
        source_last_modified_utc=None,
        fetched_at_utc=fetched_at_utc,
        raw_bytes=None,
        raw_text=None,
    )


def _extract_text(raw_pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw_pdf))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(parts)


# --- Parsing -----------------------------------------------------------------

_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
_TIME_RE = re.compile(r"\d{2}:\d{2}\s*\(ET\)")
_MATCHUP_RE = re.compile(r"[A-Z]{2,4}@[A-Z]{2,4}")
_STATUS_ALT = "|".join(STATUS_VALUES)
_NAME_SUFFIX = r"(?:Jr\.|Sr\.|II|III|IV)"
_PLAYER_RE = re.compile(
    rf"([A-Z][\w'.\-]*(?:\s{_NAME_SUFFIX})?),\s*([A-Za-z][\w'.\-]*)"
    rf"\s+({_STATUS_ALT})\b"
)
_STATUS_WORD_RE = re.compile(rf"\b(?:{_STATUS_ALT})\b")
# A hyphen glued to a word with no preceding space, immediately before a player-name
# anchor, suggests a hyphenated surname whose prefix was split onto its own PDF
# extraction line and lost (e.g. 'Caldwell-' / 'Pope,' -> row parses as 'Pope, Kentavious').
# Heuristic only: it flags a row as SUSPECT, it does not correct the name and it will
# miss any truncation that doesn't leave a dangling hyphen fragment next to the anchor.
_TRUNCATION_PREFIX_RE = re.compile(r"\w-\s*$")


@dataclass(frozen=True)
class AvailabilityRow:
    game_date: str | None
    game_time: str | None
    matchup: str | None
    team: str | None
    player_name: str
    status: str
    reason: str
    edition_effective_utc: str | None
    source_url: str


@dataclass(frozen=True)
class ParseSummary:
    pages: int
    rows_parsed: int
    unparseable_lines: int
    suspected_truncated_names: int


def parse_edition_text(
    text: str,
    *,
    edition_effective_utc: str | None = None,
    source_url: str = "",
    pages: int = 0,
    known_teams: tuple[str, ...] = NBA_TEAM_NAMES,
) -> tuple[list[AvailabilityRow], ParseSummary]:
    """Extract player-status rows from PDF-extracted text.

    `status` and `reason` are copied verbatim from the source — never mapped to a
    diagnosis, severity, or risk value. Rows carry provenance (edition_effective_utc,
    source_url) so downstream consumers can trace every row back to its snapshot.
    """
    blob = re.sub(r"\s+", " ", text).strip()

    anchors: list[tuple[int, int, str, object]] = []
    for m in _DATE_RE.finditer(blob):
        anchors.append((m.start(), m.end(), "date", m.group(0)))
    for m in _TIME_RE.finditer(blob):
        anchors.append((m.start(), m.end(), "time", m.group(0).replace("(ET)", "").strip()))
    for m in _MATCHUP_RE.finditer(blob):
        anchors.append((m.start(), m.end(), "matchup", m.group(0)))
    for team in known_teams:
        for m in re.finditer(re.escape(team), blob):
            anchors.append((m.start(), m.end(), "team", team))
    player_matches = list(_PLAYER_RE.finditer(blob))
    for m in player_matches:
        anchors.append((m.start(), m.end(), "player", m))

    anchors.sort(key=lambda a: a[0])

    rows: list[AvailabilityRow] = []
    cur_date: str | None = None
    cur_time: str | None = None
    cur_matchup: str | None = None
    cur_team: str | None = None

    for idx, (start, end, kind, value) in enumerate(anchors):
        if kind == "date":
            cur_date = value
        elif kind == "time":
            cur_time = value
        elif kind == "matchup":
            cur_matchup = value
        elif kind == "team":
            cur_team = value
        elif kind == "player":
            m = value
            last, first, status = m.group(1), m.group(2), m.group(3)
            next_start = anchors[idx + 1][0] if idx + 1 < len(anchors) else len(blob)
            reason = blob[end:next_start].strip()
            rows.append(
                AvailabilityRow(
                    game_date=cur_date,
                    game_time=cur_time,
                    matchup=cur_matchup,
                    team=cur_team,
                    player_name=f"{last}, {first}",
                    status=status,
                    reason=reason,
                    edition_effective_utc=edition_effective_utc,
                    source_url=source_url,
                )
            )

    total_status_words = len(_STATUS_WORD_RE.findall(blob))
    unparseable = max(total_status_words - len(rows), 0)
    suspected_truncated_names = sum(
        1 for m in player_matches if _TRUNCATION_PREFIX_RE.search(blob[: m.start()])
    )
    summary = ParseSummary(
        pages=pages,
        rows_parsed=len(rows),
        unparseable_lines=unparseable,
        suspected_truncated_names=suspected_truncated_names,
    )
    return rows, summary
