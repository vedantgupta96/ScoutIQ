"""Official NBA injury-report PDF adapter (availability-ledger spike, issue #95).

Read-only: fetches (with disk cache), classifies, and parses the league's official
Injury Report PDFs. `status`/`reason` text is preserved verbatim — this module makes
no medical, severity, or risk judgment. No DB access here (the probe CLI owns that).

Retrieval semantics: a missing edition returns HTTP 403 with an S3 "AccessDenied" XML
body. That is S3's response for a nonexistent object, not a block — we classify it as
`absent`, distinct from `failed` (timeouts, connection errors, other error statuses).
"""
from __future__ import annotations

import io
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

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
_last_fetch_ts = 0.0

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


def _fallback_effective_utc(date: str, edition: str) -> str:
    """Best-effort report-effective timestamp derived from the filename when no
    Last-Modified header is available (e.g. served from an old cache write)."""
    return f"{date}T{edition}"


@dataclass(frozen=True)
class EditionOutcome:
    date: str
    edition: str
    url: str
    status: str  # 'ok' | 'absent' | 'failed'
    http_status: int | None
    rows: int | None
    error_type: str | None
    error_message: str | None
    attempts: int
    elapsed_s: float
    source: str  # 'cache' | 'live'
    report_effective_utc: str | None
    fetched_at_utc: str
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
        text = _extract_text(raw)
        return EditionOutcome(
            date=date,
            edition=edition,
            url=url,
            status="ok",
            http_status=200,
            rows=None,
            error_type=None,
            error_message=None,
            attempts=0,
            elapsed_s=0.0,
            source="cache",
            report_effective_utc=_fallback_effective_utc(date, edition),
            fetched_at_utc=fetched_at_utc,
            raw_bytes=len(raw),
            raw_text=text,
        )

    started = time.monotonic()
    last_exc: Exception | None = None
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
            effective = resp.headers.get("Last-Modified")
            report_effective_utc = (
                parsedate_to_datetime(effective).astimezone(timezone.utc).isoformat()
                if effective
                else _fallback_effective_utc(date, edition)
            )
            return EditionOutcome(
                date=date,
                edition=edition,
                url=url,
                status="ok",
                http_status=200,
                rows=None,
                error_type=None,
                error_message=None,
                attempts=attempt,
                elapsed_s=elapsed,
                source="live",
                report_effective_utc=report_effective_utc,
                fetched_at_utc=fetched_at_utc,
                raw_bytes=len(resp.content),
                raw_text=_extract_text(resp.content),
            )

        if _is_s3_absent(resp.status_code, resp.content):
            return EditionOutcome(
                date=date,
                edition=edition,
                url=url,
                status="absent",
                http_status=resp.status_code,
                rows=None,
                error_type=None,
                error_message=None,
                attempts=attempt,
                elapsed_s=elapsed,
                source="live",
                report_effective_utc=None,
                fetched_at_utc=fetched_at_utc,
                raw_bytes=len(resp.content),
                raw_text=None,
            )

        last_exc = RuntimeError(f"HTTP {resp.status_code}")
        if attempt < attempts:
            time.sleep(pause * attempt)

    elapsed = time.monotonic() - started
    return EditionOutcome(
        date=date,
        edition=edition,
        url=url,
        status="failed",
        http_status=getattr(last_exc, "response", None) and last_exc.response.status_code or None,
        rows=None,
        error_type=type(last_exc).__name__ if last_exc else None,
        error_message=str(last_exc) if last_exc else None,
        attempts=attempts,
        elapsed_s=elapsed,
        source="live",
        report_effective_utc=None,
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


@dataclass(frozen=True)
class AvailabilityRow:
    game_date: str | None
    game_time: str | None
    matchup: str | None
    team: str | None
    player_name: str
    status: str
    reason: str
    report_effective_utc: str | None
    source_url: str


@dataclass(frozen=True)
class ParseSummary:
    pages: int
    rows_parsed: int
    unparseable_lines: int


def parse_edition_text(
    text: str,
    *,
    report_effective_utc: str | None = None,
    source_url: str = "",
    pages: int = 0,
    known_teams: tuple[str, ...] = NBA_TEAM_NAMES,
) -> tuple[list[AvailabilityRow], ParseSummary]:
    """Extract player-status rows from PDF-extracted text.

    `status` and `reason` are copied verbatim from the source — never mapped to a
    diagnosis, severity, or risk value. Rows carry provenance (report_effective_utc,
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
                    report_effective_utc=report_effective_utc,
                    source_url=source_url,
                )
            )

    total_status_words = len(_STATUS_WORD_RE.findall(blob))
    unparseable = max(total_status_words - len(rows), 0)
    summary = ParseSummary(pages=pages, rows_parsed=len(rows), unparseable_lines=unparseable)
    return rows, summary
