"""Flag two-way contracts on players from Spotrac (for Trade Lab roster-count legality).

Two-way players do not count against the 15-man standard roster limit, so an accurate
standard-contract count needs them flagged. Spotrac's team contracts page — the page
`load_contracts` already fetches and caches — tags each player's contract type; this
reads that tag and sets `players.is_two_way`.

Idempotent and self-correcting: every run clears all flags first, then re-sets from the
current pages, so a player who is no longer on a two-way deal is cleared. Reuses the
cached team-page fetch from load_contracts (same disk cache), so running it right after
a contract load hits cache; standalone it does one polite fetch per team.

Usage:
    python -m scoutiq.etl.load_two_way_status            # all teams
    python -m scoutiq.etl.load_two_way_status --team boston-celtics
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import update

from scoutiq.db import get_session
from scoutiq.etl.load_contracts import NBA_TEAM_SLUGS, _build_name_index, _match_player, scrape_team
from scoutiq.models import Player

logger = logging.getLogger(__name__)


def run(team_slugs: list[str] | None = None) -> tuple[int, int]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    teams = team_slugs or NBA_TEAM_SLUGS

    two_way_ids: set[int] = set()
    unmatched = 0
    with get_session() as session:
        name_index = _build_name_index(session)

    for team_slug in teams:
        players = scrape_team(team_slug)
        team_two_way = [p for p in players if p.get("is_two_way")]
        for p in team_two_way:
            player_id = _match_player(p["full_name"], name_index)
            if player_id is None:
                logger.warning("no DB match for two-way player '%s' (%s)", p["full_name"], team_slug)
                unmatched += 1
                continue
            two_way_ids.add(player_id)
        logger.info("%s: %d two-way on page", team_slug, len(team_two_way))

    with get_session() as session:
        # Full-team runs re-baseline every flag; single-team runs only touch matches.
        if team_slugs is None:
            session.execute(update(Player).values(is_two_way=False))
        if two_way_ids:
            session.execute(
                update(Player).where(Player.player_id.in_(two_way_ids)).values(is_two_way=True)
            )

    print(f"two-way status: flagged {len(two_way_ids)} players across {len(teams)} teams "
          f"({unmatched} unmatched)")
    return len(two_way_ids), unmatched


def main() -> None:
    parser = argparse.ArgumentParser(description="Flag two-way contracts from Spotrac.")
    parser.add_argument("--team", action="append", dest="teams", metavar="team-slug",
                        help="Team slug to process (repeatable). Default: all 30.")
    args = parser.parse_args()
    run(args.teams)


if __name__ == "__main__":
    main()
