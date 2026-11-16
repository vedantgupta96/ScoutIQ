"""Load nba.com Base+Advanced stats -> teams, players, player_seasons. Idempotent (upserts).

Re-running a season merges instead of replacing: nba.com owns age/gp/minutes/box and its own
keys inside `advanced` (ADV_KEYS); the Basketball-Reference keys that etl/load_bbref merged in
(BPM/OBPM/DBPM/VORP/WS/WS48/PER) survive, and so does the historical `team_id` that
etl/repair_team_history set once a row carries BBRef metrics. Rows are stamped with
`source` = "nba.com" and the fetch time in `source_fetched_at`. A frame that fails
`validate_season_frame` is refused before any write.

Usage:
  python -m scoutiq.etl.load_stats                 # all configured seasons
  python -m scoutiq.etl.load_stats --season 2023-24
  python -m scoutiq.etl.load_stats --season 2026-27 --min-players 150
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import Text, case, cast, func, literal_column, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, array, insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl._util import clean, jsonify
from scoutiq.etl.load_bbref import BBREF_ADV
from scoutiq.models import Player, PlayerSeason, Team
from scoutiq.sources import nba

# nba.com Base box-stat keys we keep in player_seasons.box
BOX_KEYS = [
    "PTS", "REB", "OREB", "DREB", "AST", "STL", "BLK", "TOV", "PF", "GS",
    "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT",
]
# nba.com Advanced keys we keep in player_seasons.advanced (BBRef adds BPM/VORP/WS later)
ADV_KEYS = [
    "USG_PCT", "TS_PCT", "EFG_PCT", "PIE", "OFF_RATING", "DEF_RATING", "NET_RATING",
    "AST_PCT", "OREB_PCT", "DREB_PCT", "REB_PCT", "TM_TOV_PCT", "PACE",
]
# Keys Basketball-Reference owns inside player_seasons.advanced (see load_bbref.BBREF_ADV).
BBREF_ADV_KEYS = sorted(BBREF_ADV.values())
REQUIRED_COLUMNS = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN"]
DEFAULT_MIN_PLAYERS = 300


def _upsert(session, model, rows, index_elements, update_keys):
    if not rows:
        return
    stmt = insert(model).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={k: stmt.excluded[k] for k in update_keys},
    )
    session.execute(stmt)


def validate_season_frame(df: pd.DataFrame, season: str, *, min_players: int = DEFAULT_MIN_PLAYERS) -> None:
    """Raise ValueError if the fetched frame is not a plausible full-league season."""
    if df is None or df.empty:
        raise ValueError(f"{season}: nba.com returned an empty frame")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{season}: frame is missing required columns {missing}")
    if df["PLAYER_ID"].duplicated().any():
        raise ValueError(f"{season}: duplicate PLAYER_ID rows in frame")
    if len(df) < min_players:
        raise ValueError(f"{season}: only {len(df)} player rows, fewer than the {min_players} minimum")
    if "USG_PCT" not in df.columns:
        raise ValueError(f"{season}: no USG_PCT values; the Advanced merge failed")
    advanced = df[[c for c in ADV_KEYS if c in df.columns]]
    unmatched = df.loc[advanced.isna().all(axis=1), "PLAYER_ID"]
    if len(unmatched):
        raise ValueError(
            f"{season}: {len(unmatched)} of {len(df)} player rows have no nba.com Advanced values "
            f"(first ids: {unmatched.head(10).tolist()}); the Advanced merge is incomplete"
        )


def player_season_upsert(rows: list[dict]):
    """INSERT ... ON CONFLICT for player_seasons that merges rather than replaces.

    nba.com owns age/gp/minutes/box and the ADV_KEYS inside `advanced`; BBRef keys are kept.
    `team_id` is kept when the stored row already carries BBRef metrics (it was reconciled to
    the historical stat team), else nba.com's team is taken.
    """
    stmt = insert(PlayerSeason).values(rows)
    empty_jsonb = cast(literal_column("'{}'"), JSONB)
    merged_advanced = type_coerce(
        func.coalesce(PlayerSeason.advanced, empty_jsonb)
        .op("-")(cast(array(ADV_KEYS), ARRAY(Text)))
        .op("||")(func.coalesce(stmt.excluded.advanced, empty_jsonb)),
        JSONB,
    )
    return stmt.on_conflict_do_update(
        index_elements=["player_id", "season"],
        set_={
            "age": stmt.excluded.age,
            "gp": stmt.excluded.gp,
            "minutes": stmt.excluded.minutes,
            "box": stmt.excluded.box,
            "advanced": merged_advanced,
            "source": stmt.excluded.source,
            "source_fetched_at": stmt.excluded.source_fetched_at,
            "team_id": case(
                (PlayerSeason.advanced.has_any(array(BBREF_ADV_KEYS)), PlayerSeason.team_id),
                else_=stmt.excluded.team_id,
            ),
        },
    )


def load_season(season: str, *, min_players: int = DEFAULT_MIN_PLAYERS) -> int:
    df = nba.fetch_season(season)
    fetched_at = datetime.now(tz=timezone.utc)
    validate_season_frame(df, season, min_players=min_players)

    teams, players, seasons = {}, {}, []
    for _, row in df.iterrows():
        tid = clean(row.get("TEAM_ID"))
        if tid:
            teams[tid] = {"team_id": tid, "abbreviation": clean(row.get("TEAM_ABBREVIATION"))}
        pid = clean(row["PLAYER_ID"])
        players[pid] = {"player_id": pid, "full_name": clean(row.get("PLAYER_NAME"))}
        seasons.append(
            {
                "player_id": pid,
                "season": season,
                "team_id": tid,
                "age": clean(row.get("AGE")),
                "gp": clean(row.get("GP")),
                "minutes": clean(row.get("MIN")),
                "box": jsonify(row, BOX_KEYS),
                "advanced": jsonify(row, ADV_KEYS),
                "source": "nba.com",
                "source_fetched_at": fetched_at,
            }
        )

    with get_session() as s:
        _upsert(s, Team, list(teams.values()), ["team_id"], ["abbreviation"])
        _upsert(s, Player, list(players.values()), ["player_id"], ["full_name"])
        s.execute(player_season_upsert(seasons))
    print(f"  {season}: {len(players)} players, {len(seasons)} player-seasons")
    return len(seasons)


def run(seasons: list[str], *, min_players: int = DEFAULT_MIN_PLAYERS) -> None:
    print(f"load_stats: {len(seasons)} seasons")
    total = sum(load_season(s, min_players=min_players) for s in seasons)
    print(f"done. {total} player-seasons total.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", help="single season e.g. 2023-24 (default: all configured)")
    ap.add_argument(
        "--min-players", type=int, default=DEFAULT_MIN_PLAYERS,
        help="refuse to load a season with fewer player rows",
    )
    args = ap.parse_args()
    run([args.season] if args.season else settings.seasons, min_players=args.min_players)
