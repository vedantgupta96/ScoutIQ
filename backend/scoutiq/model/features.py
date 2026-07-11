"""Feature specification for the v1 valuation model.

Target: a player's salary as % of cap in season t+1.
Features: production at season t, prior-season production/trajectory, age, and role.
All numeric features tolerate NaN — HistGradientBoostingRegressor handles missing values natively, so
rookies (no prior season) or players missing a metric still produce a prediction.
"""
from __future__ import annotations

# nba.com Advanced (rate/efficiency metrics) — JSON keys as stored in player_seasons.advanced
NBA_ADV = [
    "USG_PCT", "TS_PCT", "EFG_PCT", "PIE", "OFF_RATING", "DEF_RATING", "NET_RATING",
    "AST_PCT", "OREB_PCT", "DREB_PCT", "REB_PCT", "TM_TOV_PCT", "PACE",
]
# Basketball-Reference all-in-one metrics
BBREF_ADV = ["BPM", "OBPM", "DBPM", "VORP", "WS", "WS48", "PER"]

# Per-game box rates derived from season totals
PER_GAME = ["pts_pg", "reb_pg", "ast_pg", "stl_pg", "blk_pg", "tov_pg", "fg3m_pg"]

# Context: age + availability. We deliberately EXCLUDE the player's current salary — this is a
# production-implied *value* model, not salary autoregression. (prior_pct_cap is still computed in the
# dataset for the over/under-valued analysis, just not fed to the model.)
BASE_NUM = ["age", "gp", "minutes"]

POSITIONS = ["PG", "SG", "SF", "PF", "C"]
POS_COLS = [f"pos_{p}" for p in POSITIONS]

# Multi-season context (v1): last season's workload/production/impact, the scoring
# trend, and two-year availability. NaN for rookies or missing history — HGB is
# NaN-native, so "no history" is a learnable state, not an error.
LAG_SRC = ["gp", "minutes", "pts_pg", "TS_PCT", "BPM", "WS"]
LAG_FEATURES = [f"lag_{c}" for c in LAG_SRC] + ["d_pts_pg", "gp_2yr"]

NUMERIC_FEATURES = BASE_NUM + PER_GAME + NBA_ADV + BBREF_ADV + LAG_FEATURES
FEATURE_COLS = NUMERIC_FEATURES + POS_COLS

TARGET = "pct_cap_next"


def primary_position(pos: str | None) -> str | None:
    """'SF-PF' -> 'SF'. The first listed position is BBRef's primary."""
    return pos.split("-")[0] if isinstance(pos, str) and pos else None
