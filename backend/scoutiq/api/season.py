"""Season-string parsing and validation, shared across the API.

Seasons are NBA-style 'YYYY-YY' labels (e.g. '2025-26'), where the two trailing
digits are the *next* calendar year mod 100. Centralizing this keeps every router
rejecting malformed input the same way — a clean 422 instead of a leaked
``int('bana')`` ValueError surfacing as a 500.
"""
from __future__ import annotations

import re

SEASON_RE = re.compile(r"^\d{4}-\d{2}$")

# The completed-season valuation baseline. Rows for a later, in-progress season may exist in
# player_seasons and must not become a default valuation input until live-season behaviour
# is deliberately designed (SCO-49).
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


def in_progress_season() -> str | None:
    """The season after the completed baseline; rows for it are season-to-date."""
    return next_season(LATEST_SEASON)


def prev_season(season: str) -> str | None:
    """The label for the season before `season`, or None if malformed. Inverse of next_season."""
    if not is_valid_season(season):
        return None
    y1 = int(season[:4])
    return f"{y1 - 1}-{str(y1 % 100).zfill(2)}"


def is_completed_season(season: str) -> bool:
    """True iff `season` is a valid label at or before the completed-season baseline (LATEST_SEASON)."""
    return is_valid_season(season) and season <= LATEST_SEASON
