"""nba.com (stats.nba.com) adapter via nba_api.

We use `LeagueDashPlayerStats` (league-wide, one call per season per measure type) rather than per-player
career calls — far fewer requests. Base gives box totals; Advanced gives USG/TS/PIE/ratings.
"""
from __future__ import annotations

import time

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats


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
