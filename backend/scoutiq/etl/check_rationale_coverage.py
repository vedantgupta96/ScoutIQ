"""Offline audit: which players can get a grounded rationale, and which can't (and why)?

A grounded rationale needs BOTH signals the endpoint fuses:
  1. scouting coverage — at least one Claude-extracted trait in `player_ratings`, and
  2. a model valuation — at least one `player_seasons` row with BBRef advanced (BPM)
     features, so the production-implied value gap can be computed.

This script classifies every rostered or scouted player into one of:
  ready              — has both signals (rationale can be grounded)
  load_managed       — scouted but no valuation-capable season (e.g. injured /
                       load-managed / never logged a qualifying NBA season)
  no_scout_coverage  — valuation-capable but no scouting traits yet
  no_coverage        — neither signal

It also flags `ready` players that have no cached rationale yet. Read-only and fully
offline: it never calls Sonar or Claude and never triggers generation.

Usage:  python -m scoutiq.etl.check_rationale_coverage [--limit N]
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from scoutiq.db import get_session


def _classify(has_scout: bool, has_val: bool) -> str:
    if has_scout and has_val:
        return "ready"
    if has_scout and not has_val:
        return "load_managed"
    if has_val and not has_scout:
        return "no_scout_coverage"
    return "no_coverage"


def run(list_limit: int = 25) -> dict[str, int]:
    with get_session() as s:
        scouted = {
            pid for (pid,) in s.execute(text("SELECT DISTINCT player_id FROM player_ratings"))
        }
        valuable = {
            pid
            for (pid,) in s.execute(
                text("SELECT DISTINCT player_id FROM player_seasons WHERE advanced ? 'BPM'")
            )
        }
        cached = {
            pid for (pid,) in s.execute(text("SELECT DISTINCT player_id FROM player_rationales"))
        }
        # Universe: anyone rostered, scouted, or valuation-capable.
        rostered = {
            pid
            for (pid,) in s.execute(
                text("SELECT player_id FROM players WHERE current_team_id IS NOT NULL")
            )
        }
        names = dict(s.execute(text("SELECT player_id, full_name FROM players")))

    universe = rostered | scouted | valuable
    buckets: dict[str, list[int]] = {
        "ready": [],
        "load_managed": [],
        "no_scout_coverage": [],
        "no_coverage": [],
    }
    for pid in universe:
        buckets[_classify(pid in scouted, pid in valuable)].append(pid)

    ready_uncached = sorted(
        (pid for pid in buckets["ready"] if pid not in cached),
        key=lambda p: names.get(p, ""),
    )

    print(f"=== rationale coverage over {len(universe)} rostered/scouted/valued players ===")
    for label in ("ready", "load_managed", "no_scout_coverage", "no_coverage"):
        print(f"  {label:18} {len(buckets[label]):>5}")
    print(f"  {'cached rationales':18} {len(cached):>5}")
    print(f"  {'ready but uncached':18} {len(ready_uncached):>5}")

    def _sample(label: str) -> None:
        pids = sorted(buckets[label], key=lambda p: names.get(p, ""))[:list_limit]
        if not pids:
            return
        print(f"\n--- {label} (first {min(list_limit, len(buckets[label]))} by name) ---")
        for pid in pids:
            print(f"  {pid:>10}  {names.get(pid, '?')}")

    # The two actionable gaps: scouted stars we can't value, and valued players we
    # haven't scouted yet.
    _sample("load_managed")
    _sample("no_scout_coverage")

    return {label: len(pids) for label, pids in buckets.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=25, help="rows to list per gap bucket")
    args = parser.parse_args()
    run(list_limit=args.limit)
