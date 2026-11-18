"""Pure helpers that say whether a contract record covers the current season."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from scoutiq.api.season import in_progress_season

CURRENT_SEASON = in_progress_season()

CoverageStatus = Literal["current", "expired", "future_only", "no_years"]


def contract_coverage(seasons: Iterable[str], current_season: str = CURRENT_SEASON) -> CoverageStatus:
    year_seasons = list(seasons)
    if not year_seasons:
        return "no_years"
    if current_season in year_seasons:
        return "current"
    if max(year_seasons) < current_season:
        return "expired"
    return "future_only"


def non_current_contract_caveat(
    coverage_status: CoverageStatus,
    source: str,
    start: str | None,
    end: str | None,
    current_season: str = CURRENT_SEASON,
) -> str:
    tail = (
        f"No contract covering {current_season} is on file; "
        "a current roster listing does not verify pay."
    )
    if coverage_status == "expired":
        return (
            f"Contract history: this {source} record covers {start} to {end} "
            f"and does not cover {current_season}. {tail}"
        )
    if coverage_status == "future_only":
        return (
            f"Contract history: this {source} record starts {start} "
            f"and does not cover {current_season}. {tail}"
        )
    return (
        f"Contract history: this {source} record has no contract years on file "
        f"and does not cover {current_season}. {tail}"
    )
