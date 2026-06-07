"""Repair historical player_seasons.team_id from cached Basketball-Reference pages.

This is intentionally cache-only and no-network. It corrects cases where nba.com stat rows carry a
player's current team instead of the team represented by a historical season. For traded players with
BBRef combined rows (2TM/3TM/etc.), the total-season row has no single team, so team_id is cleared.

Usage:
    python -m scoutiq.etl.repair_team_history
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl._util import clean
from scoutiq.models import PlayerSeason, PlayerXref, Team
from scoutiq.sources import bbref, nba

MULTI_TEAM_CODES = {"TOT", "2TM", "3TM", "4TM", "5TM"}


def _cached_html(slug: str) -> str | None:
    path = Path(settings.RAW_DIR) / f"{slug}.html"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


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


def repair_team_history() -> dict[str, int]:
    seasons = set(settings.seasons)
    counts = {
        "players_seen": 0,
        "missing_cache": 0,
        "season_rows_seen": 0,
        "updated_team_id": 0,
        "cleared_multi_team": 0,
        "unknown_team_code": 0,
    }

    with get_session() as session:
        _upsert_teams(session)
        xrefs = session.execute(
            select(PlayerXref.player_id, PlayerXref.bbref_slug)
            .where(PlayerXref.bbref_slug.is_not(None))
            .order_by(PlayerXref.player_id)
        ).all()

        for player_id, slug in xrefs:
            counts["players_seen"] += 1
            html = _cached_html(slug)
            if not html:
                counts["missing_cache"] += 1
                continue
            adv = bbref.parse_advanced(html)
            if adv is None:
                continue

            for _, row in adv.iterrows():
                season = str(row["Season"])
                if season not in seasons:
                    continue
                counts["season_rows_seen"] += 1
                team_code = str(clean(row.get("Team") or row.get("Tm")) or "").upper()
                if not team_code:
                    continue
                if team_code in MULTI_TEAM_CODES:
                    team_id = None
                    counts["cleared_multi_team"] += 1
                else:
                    team_id = nba.team_id_for_abbreviation(team_code)
                    if team_id is None:
                        counts["unknown_team_code"] += 1
                        continue

                ps = session.scalars(
                    select(PlayerSeason).where(
                        PlayerSeason.player_id == player_id,
                        PlayerSeason.season == season,
                    )
                ).first()
                if ps is None:
                    continue
                if ps.team_id != team_id:
                    ps.team_id = team_id
                    counts["updated_team_id"] += 1

    print("repair_team_history:", " ".join(f"{k}={v}" for k, v in counts.items()))
    return counts


if __name__ == "__main__":
    repair_team_history()
