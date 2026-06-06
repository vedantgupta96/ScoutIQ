"""Data-quality gate: how much of the data is actually trainable?

A v0 training example = features from season t (advanced incl. BPM) -> salary as % of cap in season t+1.
This script reports raw counts and the count of (player, t) rows that have all three:
  advanced stats at t,  salary at t+1,  cap_constants at t+1.

Usage:  python -m scoutiq.etl.check_coverage
"""
from __future__ import annotations

from sqlalchemy import text

from scoutiq.config import settings
from scoutiq.db import get_session


def _scalar(s, sql: str) -> int:
    return s.execute(text(sql)).scalar() or 0


def run() -> None:
    seasons = settings.seasons
    next_of = {seasons[i]: seasons[i + 1] for i in range(len(seasons) - 1)}

    with get_session() as s:
        print("=== row counts ===")
        for tbl in ["teams", "players", "player_xref", "player_seasons", "player_salaries", "cap_constants"]:
            print(f"  {tbl:16} {_scalar(s, f'SELECT count(*) FROM {tbl}'):>7}")

        print("\n=== player_xref status ===")
        for status, n in s.execute(text("SELECT status, count(*) FROM player_xref GROUP BY status ORDER BY 2 DESC")):
            print(f"  {status:12} {n:>7}")

        print("\n=== enrichment ===")
        adv = _scalar(s, "SELECT count(*) FROM player_seasons WHERE advanced ? 'BPM'")
        tot = _scalar(s, "SELECT count(*) FROM player_seasons")
        print(f"  player_seasons with BBRef advanced (BPM): {adv} / {tot}")

        # trainable: advanced at t, salary at t+1, cap at t+1
        adv_set = {
            (pid, season)
            for pid, season in s.execute(
                text("SELECT player_id, season FROM player_seasons WHERE advanced ? 'BPM'")
            )
        }
        sal_set = {
            (pid, season)
            for pid, season in s.execute(
                text("SELECT player_id, season FROM player_salaries WHERE salary IS NOT NULL")
            )
        }
        cap_set = {row[0] for row in s.execute(text("SELECT season FROM cap_constants WHERE salary_cap IS NOT NULL"))}

    trainable = sum(
        1
        for (pid, t) in adv_set
        if t in next_of and next_of[t] in cap_set and (pid, next_of[t]) in sal_set
    )
    print(f"\n=== TRAINABLE ROWS (features@t -> salary%cap@t+1): {trainable} ===")
    print("  (gate to the modeling phase; target was >3,000)")


if __name__ == "__main__":
    run()
