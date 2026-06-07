"""nba.com (stats.nba.com) adapter via nba_api.

We use `LeagueDashPlayerStats` (league-wide, one call per season per measure type) rather than per-player
career calls — far fewer requests. Base gives box totals; Advanced gives USG/TS/PIE/ratings.
"""
from __future__ import annotations

import time

import pandas as pd
from nba_api.stats.endpoints import commonallplayers, leaguedashplayerstats
from nba_api.stats.static import teams as static_teams

_TEAM_ABBREV_ALIASES = {
    "BRK": "BKN",  # Basketball-Reference abbreviation for Brooklyn.
    "CHO": "CHA",
    "NOH": "NOP",
    "PHO": "PHX",
}


def _league_dash(season: str, measure_type: str) -> pd.DataFrame:
    return leaguedashplayerstats.LeagueDashPlayerStats(
        measure_type_detailed_defense=measure_type,
        season=season,
        per_mode_detailed="Totals",
        timeout=60,
    ).get_data_frames()[0]


def fetch_season(season: str, pause: float = 0.6) -> pd.DataFrame:
    """Return one row per player for `season`, merging Base + Advanced on PLAYER_ID.

    Advanced-only columns are suffixed nothing; overlapping keys (e.g. AGE, GP, MIN, TEAM_*) come from Base.
    """
    base = _league_dash(season, "Base")
    time.sleep(pause)
    adv = _league_dash(season, "Advanced")

    adv_only = [c for c in adv.columns if c == "PLAYER_ID" or c not in base.columns]
    merged = base.merge(adv[adv_only], on="PLAYER_ID", how="left")
    merged["SEASON"] = season
    return merged


def team_rows() -> list[dict]:
    """Current NBA team reference rows from nba_api static metadata."""
    return [
        {
            "team_id": t["id"],
            "abbreviation": t["abbreviation"],
            "name": t["full_name"],
        }
        for t in static_teams.get_teams()
    ]


def team_id_for_abbreviation(abbreviation: str | None) -> int | None:
    """Map an NBA/BBRef team abbreviation to the stable nba_api team id."""
    if not abbreviation:
        return None
    abbr = _TEAM_ABBREV_ALIASES.get(str(abbreviation).upper(), str(abbreviation).upper())
    for row in team_rows():
        if row["abbreviation"] == abbr:
            return row["team_id"]
    return None


def fetch_current_players(season: str) -> pd.DataFrame:
    """Return current roster/team metadata for active NBA players."""
    return commonallplayers.CommonAllPlayers(
        is_only_current_season=1,
        season=season,
        timeout=60,
    ).get_data_frames()[0]
