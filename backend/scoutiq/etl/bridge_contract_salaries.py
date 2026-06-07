"""Bridge forward-season contract cap hits into player_salaries.

BBRef per-player Salaries tables only carry realized (past) salaries, so a future
season like 2025-26 has no player_salaries rows even though the valuation reads
that table. This backfills player_salaries for a forward season from
contract_years.aav (the per-season cap hit), tagged source='contract_years' so it
stays distinguishable from realized BBRef salaries.

A minimum-salary floor drops the small set of malformed/stale Spotrac rows
(sub-minimum values that are parse artifacts, not real contracts). Realized
BBRef rows are never overwritten.

Usage:
    python -m scoutiq.etl.bridge_contract_salaries                       # season 2025-26
    python -m scoutiq.etl.bridge_contract_salaries --season 2025-26 --floor 1100000
"""
from __future__ import annotations

import argparse

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import PlayerSalary

DEFAULT_SEASON = settings.CURRENT_SEASON  # '2025-26'
DEFAULT_FLOOR = 1_100_000  # below any NBA minimum -> malformed/stale source row, skip


def run(season: str, floor: int) -> None:
    with get_session() as s:
        # One row per player: the cap hit from their most recent contract that
        # covers `season` (DISTINCT ON keeps the newest signing if deals overlap).
        rows = s.execute(
            text(
                """
                SELECT DISTINCT ON (c.player_id) c.player_id, cy.aav
                FROM contract_years cy
                JOIN contracts c ON c.id = cy.contract_id
                WHERE cy.season = :season AND cy.aav IS NOT NULL
                ORDER BY c.player_id, c.season_start DESC, c.scraped_at DESC NULLS LAST
                """
            ),
            {"season": season},
        ).all()

        kept = [
            {"player_id": pid, "season": season, "salary": int(aav), "source": "contract_years"}
            for pid, aav in rows
            if aav and aav >= floor
        ]
        dropped = len(rows) - len(kept)

        if kept:
            stmt = insert(PlayerSalary).values(kept)
            # Never clobber realized BBRef salaries; only fill or refresh bridged rows.
            s.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_player_salary_season",
                    set_={"salary": stmt.excluded["salary"], "source": stmt.excluded["source"]},
                    where=(PlayerSalary.source != "bbref"),
                )
            )

    print(
        f"bridge {season}: wrote {len(kept)} salaries (source=contract_years); "
        f"skipped {dropped} below floor ${floor:,}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=DEFAULT_SEASON, help="forward season to bridge (default: CURRENT_SEASON)")
    ap.add_argument("--floor", type=int, default=DEFAULT_FLOOR, help="skip cap hits below this (default: 1.1M)")
    args = ap.parse_args()
    run(args.season, args.floor)
