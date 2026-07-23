"""nba.com tracking/hustle adapter via nba_api — read-only spike source (issue #94).

Covers four player-level "second spectrum"-derived endpoint families that nba.com
exposes on top of the box-score data `nba.py` already loads:

  hustle    -> leaguehustlestatsplayer.LeagueHustleStatsPlayer
  tracking  -> leaguedashptstats.LeagueDashPtStats (parameterised by PtMeasureType)
  defense   -> leaguedashptdefend.LeagueDashPtDefend
  shooting  -> leaguedashplayerptshot.LeagueDashPlayerPtShot

Disk-cached to JSON (mirrors bbref.py's RAW_DIR pattern) so re-runs never re-hit the
network. Conservative pacing + bounded retries; failures are returned as a structured
`FetchOutcome`, never swallowed or fabricated. This module never writes to the database.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashplayerptshot,
    leaguedashptdefend,
    leaguedashptstats,
    leaguehustlestatsplayer,
)

from scoutiq.config import settings

TRACKING_RAW_DIR = settings.DATA_DIR / "raw" / "tracking"
DEFAULT_PAUSE_SECONDS = 1.5
DEFAULT_TIMEOUT_SECONDS = 45
MAX_ATTEMPTS = 3

TRACKING_MEASURE_TYPES = ["Drives", "Passing", "Rebounding", "CatchShoot"]

# family -> (nba_api endpoint class, whether it takes a PtMeasureType, extra fixed kwargs).
FAMILY_REGISTRY: dict[str, dict] = {
    "hustle": {
        "endpoint": leaguehustlestatsplayer.LeagueHustleStatsPlayer,
        "parameterised": False,
        "kwargs": {},
        "player_id_field": "PLAYER_ID",
    },
    "tracking": {
        "endpoint": leaguedashptstats.LeagueDashPtStats,
        "parameterised": True,
        "kwargs": {"player_or_team": "Player"},
        "player_id_field": "PLAYER_ID",
    },
    "defense": {
        "endpoint": leaguedashptdefend.LeagueDashPtDefend,
        "parameterised": False,
        "kwargs": {},
        # LeagueDashPtDefend uniquely names its player id column CLOSE_DEF_PERSON_ID,
        # not PLAYER_ID — callers must join on this field for this family.
        "player_id_field": "CLOSE_DEF_PERSON_ID",
    },
    "shooting": {
        "endpoint": leaguedashplayerptshot.LeagueDashPlayerPtShot,
        "parameterised": False,
        "kwargs": {},
        "player_id_field": "PLAYER_ID",
    },
}


def player_id_field(family: str) -> str:
    """The column holding the numeric nba.com player id for this family."""
    return FAMILY_REGISTRY[family]["player_id_field"]


@dataclass
class FetchOutcome:
    """Structured result of one fetch_family call — success or failure, never fabricated."""

    family: str
    season: str
    measure_type: str | None
    ok: bool
    rows: int
    source: str  # 'cache' | 'live'
    http_status: int | None
    error_type: str | None
    error_message: str | None
    attempts: int
    elapsed_s: float
    fetched_at_utc: str
    frame: pd.DataFrame | None = field(default=None, repr=False)


def _cache_key(family: str, season: str, measure_type: str | None) -> str:
    parts = [family, season]
    if measure_type:
        parts.append(measure_type)
    return "__".join(parts)


def _cache_path(cache_dir: Path, family: str, season: str, measure_type: str | None) -> Path:
    return cache_dir / f"{_cache_key(family, season, measure_type)}.json"


def _load_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame(payload["rows"])


def _write_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cached_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": df.to_dict(orient="records"),
    }
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")


def fetch_family(
    family: str,
    season: str,
    *,
    measure_type: str | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
    pause: float = DEFAULT_PAUSE_SECONDS,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> FetchOutcome:
    """Fetch one (family, season[, measure_type]) player-level frame.

    Cache hits never touch the network. Live fetches retry up to MAX_ATTEMPTS times with
    linear backoff (pause * attempt) before giving up; a failure is reported as
    ok=False and never papered over with fabricated rows.
    """
    if family not in FAMILY_REGISTRY:
        raise ValueError(f"Unknown tracking family: {family!r}")

    spec = FAMILY_REGISTRY[family]
    if spec["parameterised"] and not measure_type:
        raise ValueError(f"family {family!r} requires measure_type")
    if not spec["parameterised"]:
        measure_type = None

    cache_dir = cache_dir or TRACKING_RAW_DIR
    path = _cache_path(cache_dir, family, season, measure_type)

    if use_cache:
        cached = _load_cache(path)
        if cached is not None:
            return FetchOutcome(
                family=family,
                season=season,
                measure_type=measure_type,
                ok=True,
                rows=len(cached),
                source="cache",
                http_status=None,
                error_type=None,
                error_message=None,
                attempts=0,
                elapsed_s=0.0,
                fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                frame=cached,
            )

    endpoint_cls = spec["endpoint"]
    kwargs = dict(spec["kwargs"])
    kwargs["season"] = season
    if measure_type:
        kwargs["pt_measure_type"] = measure_type

    start = time.monotonic()
    last_error_type: str | None = None
    last_error_message: str | None = None
    last_http_status: int | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = endpoint_cls(timeout=timeout, **kwargs)
            df = response.get_data_frames()[0]
            elapsed = time.monotonic() - start
            time.sleep(pause)
            if use_cache:
                _write_cache(path, df)
            return FetchOutcome(
                family=family,
                season=season,
                measure_type=measure_type,
                ok=True,
                rows=len(df),
                source="live",
                http_status=200,
                error_type=None,
                error_message=None,
                attempts=attempt,
                elapsed_s=elapsed,
                fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                frame=df,
            )
        except Exception as exc:  # noqa: BLE001 — capture into FetchOutcome, never swallow silently
            last_error_type = type(exc).__name__
            last_error_message = str(exc)
            last_http_status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt < MAX_ATTEMPTS:
                time.sleep(pause * attempt)

    elapsed = time.monotonic() - start
    return FetchOutcome(
        family=family,
        season=season,
        measure_type=measure_type,
        ok=False,
        rows=0,
        source="live",
        http_status=last_http_status,
        error_type=last_error_type,
        error_message=last_error_message,
        attempts=MAX_ATTEMPTS,
        elapsed_s=elapsed,
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        frame=None,
    )


def iter_probe_targets(seasons: list[str], measure_types: list[str] | None = None):
    """Yield (family, season, measure_type) tuples the probe CLI should iterate."""
    measure_types = measure_types or TRACKING_MEASURE_TYPES
    for season in seasons:
        for family, spec in FAMILY_REGISTRY.items():
            if spec["parameterised"]:
                for measure_type in measure_types:
                    yield family, season, measure_type
            else:
                yield family, season, None
