"""Seed the draft_picks table for the tradable seven-draft window.

Two layers, honest by construction:
1. Default self-ownership: every team owns its own R1/R2 picks for the next seven
   drafts (source='default-ownership'). Mechanically complete, never wrong about a
   pick's existence — only, potentially, about who owns it today.
2. Verified overrides from data/draft_pick_overrides.csv: real traded picks,
   protections, and swap rights, one row per pick with a source URL. Only overrides
   change ownership/protection; nothing is invented.

Usage:
    python -m scoutiq.etl.load_draft_picks            # defaults + overrides
    python -m scoutiq.etl.load_draft_picks --window 7
"""
from __future__ import annotations

import argparse
import csv
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import DraftPick, Team

logger = logging.getLogger(__name__)

OVERRIDES_CSV = settings.DATA_DIR / "draft_pick_overrides.csv"
TRADABLE_DRAFTS = 7  # the CBA's seven-year rule, enforced structurally by the window


def upcoming_draft_year() -> int:
    # '2025-26' season -> 2026 draft is the next one on the board.
    return int(settings.CURRENT_SEASON[:4]) + 1


def _load_overrides(teams_by_abbr: dict[str, int]) -> dict[tuple[int, int, int], dict]:
    """CSV rows keyed by pick identity (draft_year, round, original_team_id)."""
    if not OVERRIDES_CSV.exists():
        return {}
    overrides: dict[tuple[int, int, int], dict] = {}
    with OVERRIDES_CSV.open() as fh:
        for row in csv.DictReader(fh):
            if not row.get("draft_year"):
                continue
            original = teams_by_abbr.get(row["original_team_abbr"].strip().upper())
            owner = teams_by_abbr.get(row["current_team_abbr"].strip().upper())
            if original is None or owner is None:
                logger.warning("Skipping override with unknown team: %s", row)
                continue
            swap_abbr = (row.get("swap_rights_team_abbr") or "").strip().upper()
            overrides[(int(row["draft_year"]), int(row["round"]), original)] = {
                "current_team_id": owner,
                "protected_top": int(row["protected_top"]) if row.get("protected_top") else None,
                "swap_rights_team_id": teams_by_abbr.get(swap_abbr) if swap_abbr else None,
                "converts_to": (row.get("converts_to") or "").strip() or None,
                "source": "verified-override",
                "source_url": (row.get("source_url") or "").strip() or None,
                "notes": (row.get("notes") or "").strip() or None,
            }
    return overrides


def run(window: int = TRADABLE_DRAFTS) -> int:
    window = min(window, TRADABLE_DRAFTS)
    now = datetime.now(timezone.utc)
    first_year = upcoming_draft_year()
    with get_session() as db:
        teams = db.scalars(select(Team)).all()
        teams_by_abbr = {t.abbreviation: t.team_id for t in teams if t.abbreviation}
        overrides = _load_overrides(teams_by_abbr)

        values: list[dict] = []
        for team in teams:
            for year in range(first_year, first_year + window):
                for rnd in (1, 2):
                    base = {
                        "draft_year": year,
                        "round": rnd,
                        "original_team_id": team.team_id,
                        "current_team_id": team.team_id,
                        "protected_top": None,
                        "swap_rights_team_id": None,
                        "converts_to": None,
                        "source": "default-ownership",
                        "source_url": None,
                        "notes": None,
                        "updated_at": now,
                    }
                    override = overrides.get((year, rnd, team.team_id))
                    if override:
                        base.update(override)
                        base["updated_at"] = now
                    values.append(base)

        stmt = pg_insert(DraftPick).values(values)
        update_cols = {
            col: stmt.excluded[col]
            for col in values[0]
            if col not in ("draft_year", "round", "original_team_id")
        }
        db.execute(stmt.on_conflict_do_update(constraint="uq_draft_pick_identity", set_=update_cols))
        applied = sum(1 for v in values if v["source"] == "verified-override")
        print(f"draft_picks: upserted {len(values)} picks "
              f"({first_year}-{first_year + window - 1}, {applied} verified overrides)")
        return len(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed draft_picks (defaults + verified overrides).")
    parser.add_argument("--window", type=int, default=TRADABLE_DRAFTS,
                        help=f"Drafts to materialize (max {TRADABLE_DRAFTS}, the CBA limit).")
    args = parser.parse_args()
    run(args.window)


if __name__ == "__main__":
    main()
