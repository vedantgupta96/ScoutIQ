"""Load current NBA roster teams into players.current_team_*.

This separates current roster state from historical player-season stats. The historical
`player_seasons.team_id` field should mean "team for that stat season"; current team belongs here.

Usage:
    python -m scoutiq.etl.load_current_rosters
    python -m scoutiq.etl.load_current_rosters --season 2025-26
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl._util import clean
from scoutiq.models import Player, Team
from scoutiq.sources import nba


def _upsert_teams(session) -> None:
    rows = nba.team_rows()
    stmt = insert(Team).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["team_id"],
            set_={
                "abbreviation": stmt.excluded.abbreviation,
                "name": stmt.excluded.name,
            },
        )
    )


def load_current_rosters(season: str | None = None) -> int:
    season = season or settings.CURRENT_SEASON
    df = nba.fetch_current_players(season)
    now = datetime.now(tz=timezone.utc)
    source = f"nba_api.commonallplayers:{season}"

    rows = []
    for _, row in df.iterrows():
        player_id = clean(row.get("PERSON_ID"))
        team_id = clean(row.get("TEAM_ID"))
        name = clean(row.get("DISPLAY_FIRST_LAST"))
        roster_status = clean(row.get("ROSTERSTATUS"))
        if not player_id or not name or not team_id or str(roster_status) != "1":
            continue
        rows.append(
            {
                "player_id": player_id,
                "full_name": name,
                "current_team_id": team_id,
                "current_team_source": source,
                "current_team_updated_at": now,
            }
        )

    with get_session() as session:
        _upsert_teams(session)
        if rows:
            stmt = insert(Player).values(rows)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["player_id"],
                    set_={
                        "full_name": stmt.excluded.full_name,
                        "current_team_id": stmt.excluded.current_team_id,
                        "current_team_source": stmt.excluded.current_team_source,
                        "current_team_updated_at": stmt.excluded.current_team_updated_at,
                    },
                )
            )

    print(f"current_rosters: upserted {len(rows)} players from {source}")
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=None, help="current NBA season string, e.g. 2025-26")
    args = parser.parse_args()
    load_current_rosters(args.season)
