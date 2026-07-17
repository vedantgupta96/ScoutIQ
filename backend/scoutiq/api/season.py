"""Season-string parsing and validation, shared across the API.

Seasons are NBA-style 'YYYY-YY' labels (e.g. '2025-26'), where the two trailing
digits are the *next* calendar year mod 100. Centralizing this keeps every router
rejecting malformed input the same way — a clean 422 instead of a leaked
``int('bana')`` ValueError surfacing as a 500.
"""
from __future__ import annotations

import re

SEASON_RE = re.compile(r"^\d{4}-\d{2}$")

# The most recent completed season for which we have full stats.
# Update each offseason after the ETL runs for the new season.
LATEST_SEASON = "2025-26"


def is_valid_season(season: str) -> bool:
    """True iff `season` is a well-formed 'YYYY-YY' label with a consistent end year."""
    if not isinstance(season, str) or not SEASON_RE.match(season):
        return False
    start = int(season[:4])
    return int(season[5:]) == (start + 1) % 100


def validate_season(season: str) -> str:
    """Return `season` unchanged if valid, else raise ValueError with a clear message."""
    if not is_valid_season(season):
        raise ValueError(
            f"invalid season {season!r}; expected 'YYYY-YY' (e.g. '2025-26')"
        )
    return season


def next_season(season: str) -> str | None:
    """The label for the season after `season`, or None if `season` is malformed."""
    if not is_valid_season(season):
        return None
    y1, y2 = int(season[:4]), int(season[5:])
    return f"{y1 + 1}-{str((y2 + 1) % 100).zfill(2)}"


def prev_season(season: str) -> str | None:
    """The label for the season before `season`, or None if malformed. Inverse of next_season."""
    if not is_valid_season(season):
        return None
    y1 = int(season[:4])
    return f"{y1 - 1}-{str(y1 % 100).zfill(2)}"
