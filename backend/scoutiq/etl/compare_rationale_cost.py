"""Compare the cost of the two rationale consensus modes on the same players.

Runs both `fusion` and `multi_source` over N scouted players (forcing fresh generation) and prints a
side-by-side table: avg input/output tokens and avg $/rationale per mode. `multi_source` bills real
Sonar calls, so keep N small (default 5).

Usage:
    python -m scoutiq.etl.compare_rationale_cost --players 5
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

from scoutiq.api.routers.players import get_player_rationale
from scoutiq.db import get_session
from scoutiq.models import ScoutReport

logger = logging.getLogger(__name__)
MODES = ["fusion", "multi_source"]


def _covered_players(limit: int) -> list[int]:
    with get_session() as s:
        rows = s.scalars(
            select(ScoutReport.player_id).order_by(ScoutReport.player_id).limit(limit)
        ).all()
    return list(dict.fromkeys(rows))


def run(limit: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    player_ids = _covered_players(limit)
    logger.info("Comparing rationale cost over %d players: %s", len(player_ids), MODES)

    totals = {m: {"in": 0, "out": 0, "usd": 0.0, "n": 0} for m in MODES}
    for pid in player_ids:
        for mode in MODES:
            try:
                with get_session() as s:
                    resp = get_player_rationale(pid, consensus=mode, refresh=True, db=s)
            except Exception as e:  # noqa: BLE001 — one player/mode failure shouldn't abort the sweep
                logger.warning("  %s/%s failed: %s", pid, mode, e)
                continue
            t = totals[mode]
            t["in"] += resp.cost.input_tokens
            t["out"] += resp.cost.output_tokens
            t["usd"] += resp.cost.est_cost_usd
            t["n"] += 1

    print(f"\n{'mode':<14}{'players':>8}{'avg_in':>10}{'avg_out':>10}{'avg_$':>12}{'total_$':>12}")
    for mode in MODES:
        t = totals[mode]
        n = t["n"] or 1
        print(
            f"{mode:<14}{t['n']:>8}{t['in'] // n:>10}{t['out'] // n:>10}"
            f"{t['usd'] / n:>12.5f}{t['usd']:>12.5f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=5)
    args = parser.parse_args()
    run(args.players)
