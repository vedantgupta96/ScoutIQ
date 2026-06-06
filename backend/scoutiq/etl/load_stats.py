"""Load nba.com Base+Advanced stats -> teams, players, player_seasons. Idempotent (upserts).

Usage:
  python -m scoutiq.etl.load_stats                 # all configured seasons
  python -m scoutiq.etl.load_stats --season 2023-24
"""
from __future__ import annotations

import argparse

from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl._util import clean, jsonify
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


def _upsert(session, model, rows, index_elements, update_keys):
    if not rows:
        return
    stmt = insert(model).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={k: stmt.excluded[k] for k in update_keys},
    )
    session.execute(stmt)


def load_season(season: str) -> int:
    df = nba.fetch_season(season)

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
            }
        )

    with get_session() as s:
        _upsert(s, Team, list(teams.values()), ["team_id"], ["abbreviation"])
        _upsert(s, Player, list(players.values()), ["player_id"], ["full_name"])
        _upsert(
            s, PlayerSeason, seasons, ["player_id", "season"],
            ["team_id", "age", "gp", "minutes", "box", "advanced"],
        )
    print(f"  {season}: {len(players)} players, {len(seasons)} player-seasons")
    return len(seasons)


def run(seasons: list[str]) -> None:
    print(f"load_stats: {len(seasons)} seasons")
    total = sum(load_season(s) for s in seasons)
    print(f"done. {total} player-seasons total.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", help="single season e.g. 2023-24 (default: all configured)")
    args = ap.parse_args()
    run([args.season] if args.season else settings.seasons)
