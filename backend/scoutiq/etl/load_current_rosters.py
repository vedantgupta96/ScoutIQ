"""Load current NBA roster teams into players.current_team_*, clearing departed players.

This separates current roster state from historical player-season stats. The historical
`player_seasons.team_id` field means "team for that stat season"; current team belongs here.
Clearing `current_team_id` for players absent from the feed is what keeps a player who left
the league from keeping a stale current team while their last stat team stays historical.

A refresh only reconciles (clears departed players) when the feed passes a completeness gate:
rostered players present, every one of the 30 teams represented with a plausible head count,
no team id outside the NBA, no player on two rows, and a bounded share of currently assigned
players departing. A failed gate raises `RosterCompletenessError` before any write.

Usage:
    python -m scoutiq.etl.load_current_rosters
    python -m scoutiq.etl.load_current_rosters --season 2025-26
    python -m scoutiq.etl.load_current_rosters --dry-run --json plan.json
    python -m scoutiq.etl.load_current_rosters --upsert-only      # old behaviour, no clearing
    python -m scoutiq.etl.load_current_rosters --max-departed-fraction 0.5
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl._util import clean
from scoutiq.models import CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX, Player, Team
from scoutiq.sources import nba

ROSTER_SOURCE_PREFIX = "nba_api.commonallplayers"
MIN_TEAM_PLAYERS = 12
MAX_TEAM_PLAYERS = 23
DEFAULT_MAX_DEPARTED_FRACTION = 0.40
REQUIRED_COLUMNS = ["PERSON_ID", "DISPLAY_FIRST_LAST", "TEAM_ID", "ROSTERSTATUS"]


class RosterCompletenessError(RuntimeError):
    """The roster feed failed a completeness check; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class RosterPlan:
    season: str
    source: str
    assignments: list[dict]
    departed: list[dict]
    moved: list[dict]
    added: int
    unchanged: int
    problems: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "season": self.season,
            "source": self.source,
            "complete": self.complete,
            "counts": {
                "assigned": len(self.assignments),
                "added": self.added,
                "moved": len(self.moved),
                "unchanged": self.unchanged,
                "departed": len(self.departed),
                "problems": len(self.problems),
            },
            "problems": list(self.problems),
            "departed": self.departed,
            "moved": self.moved,
        }


def parse_roster_feed(df) -> tuple[list[dict], list[str]]:
    """Turn the CommonAllPlayers frame into rostered-player rows plus any problems."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return [], [f"roster feed is missing required columns {missing}"]

    rows: list[dict] = []
    problems: list[str] = []
    seen: set = set()
    for _, row in df.iterrows():
        player_id = clean(row.get("PERSON_ID"))
        team_id = clean(row.get("TEAM_ID"))
        name = clean(row.get("DISPLAY_FIRST_LAST"))
        roster_status = clean(row.get("ROSTERSTATUS"))
        if not player_id or not name or not team_id or str(roster_status) != "1":
            continue
        if player_id in seen:
            problems.append(f"player {player_id} appears on more than one roster row")
            continue
        seen.add(player_id)
        rows.append({"player_id": player_id, "full_name": name, "current_team_id": team_id})
    return rows, problems


def plan_roster_refresh(
    feed_rows: list[dict],
    existing: Iterable[tuple],
    team_ids: set,
    *,
    season: str,
    max_departed_fraction: float = DEFAULT_MAX_DEPARTED_FRACTION,
    feed_problems: Iterable[str] = (),
) -> RosterPlan:
    """Pure planning step: diff the feed against stored assignments and run the completeness gate."""
    existing_rows = list(existing)
    stored = {pid: (name, team) for pid, name, team in existing_rows}
    feed = {row["player_id"]: row for row in feed_rows}
    problems = list(feed_problems)

    if not feed_rows:
        problems.append("roster feed has no rostered players")
    else:
        counts = Counter(row["current_team_id"] for row in feed_rows)
        unknown = sorted(t for t in counts if t not in team_ids)
        if unknown:
            problems.append(f"roster feed has team ids that are not NBA teams: {unknown}")
        missing_teams = sorted(t for t in team_ids if t not in counts)
        if missing_teams:
            problems.append(f"roster feed has no players for teams {missing_teams}")
        for team_id in sorted(t for t in counts if t in team_ids):
            n = counts[team_id]
            if n < MIN_TEAM_PLAYERS:
                problems.append(f"team {team_id} has {n} players, below the {MIN_TEAM_PLAYERS} minimum")
            elif n > MAX_TEAM_PLAYERS:
                problems.append(f"team {team_id} has {n} players, above the {MAX_TEAM_PLAYERS} maximum")

    departed = sorted(
        (
            {"player_id": pid, "full_name": name, "previous_team_id": team}
            for pid, (name, team) in stored.items()
            if pid not in feed
        ),
        key=lambda d: d["player_id"],
    )
    if stored and len(departed) / len(stored) > max_departed_fraction:
        problems.append(
            f"{len(departed)} of {len(stored)} currently assigned players are absent from the feed, "
            f"over the {max_departed_fraction:.0%} limit"
        )

    moved = sorted(
        (
            {
                "player_id": pid,
                "full_name": row["full_name"],
                "previous_team_id": stored[pid][1],
                "current_team_id": row["current_team_id"],
            }
            for pid, row in feed.items()
            if pid in stored and stored[pid][1] != row["current_team_id"]
        ),
        key=lambda d: d["player_id"],
    )
    added = sum(1 for pid in feed if pid not in stored)
    unchanged = sum(1 for pid, row in feed.items() if pid in stored and stored[pid][1] == row["current_team_id"])

    return RosterPlan(
        season=season,
        source=f"{ROSTER_SOURCE_PREFIX}:{season}",
        assignments=[
            {"player_id": r["player_id"], "full_name": r["full_name"], "current_team_id": r["current_team_id"]}
            for r in feed_rows
        ],
        departed=departed,
        moved=moved,
        added=added,
        unchanged=unchanged,
        problems=problems,
    )


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


def _summary(plan: RosterPlan) -> str:
    return (
        f"current_rosters: {plan.source} assigned {len(plan.assignments)}, added {plan.added}, "
        f"moved {len(plan.moved)}, unchanged {plan.unchanged}, departed {len(plan.departed)}, "
        f"problems {len(plan.problems)}"
    )


def load_current_rosters(
    season: str | None = None,
    *,
    reconcile: bool = True,
    dry_run: bool = False,
    max_departed_fraction: float = DEFAULT_MAX_DEPARTED_FRACTION,
    now: datetime | None = None,
    on_plan: Callable[[RosterPlan], None] | None = None,
) -> RosterPlan:
    season = season or settings.CURRENT_SEASON
    df = nba.fetch_current_players(season)
    feed_rows, feed_problems = parse_roster_feed(df)
    team_ids = {t["team_id"] for t in nba.team_rows()}
    now = now or datetime.now(tz=timezone.utc)

    with get_session() as session:
        existing = session.execute(
            select(Player.player_id, Player.full_name, Player.current_team_id)
            .where(Player.current_team_id.is_not(None))
        ).all()
        plan = plan_roster_refresh(
            feed_rows,
            [tuple(r) for r in existing],
            team_ids,
            season=season,
            max_departed_fraction=max_departed_fraction,
            feed_problems=feed_problems,
        )

        if on_plan is not None:
            on_plan(plan)

        if dry_run:
            print(_summary(plan))
            return plan
        if reconcile and plan.problems:
            raise RosterCompletenessError(plan.problems)

        _upsert_teams(session)
        if plan.assignments:
            rows = [
                {**a, "current_team_source": plan.source, "current_team_updated_at": now}
                for a in plan.assignments
            ]
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
        if reconcile and plan.departed:
            session.execute(
                update(Player)
                .where(Player.player_id.in_([d["player_id"] for d in plan.departed]))
                .values(
                    current_team_id=None,
                    current_team_source=plan.source + CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX,
                    current_team_updated_at=now,
                )
            )

    print(_summary(plan))
    if not reconcile:
        print("current_rosters: --upsert-only, departed players were not cleared")
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=None, help="current NBA season string, e.g. 2025-26")
    parser.add_argument("--dry-run", action="store_true", help="plan and report only; write nothing")
    parser.add_argument(
        "--upsert-only", action="store_true",
        help="upsert players in the feed without the completeness gate or clearing departed players",
    )
    parser.add_argument(
        "--max-departed-fraction", type=float, default=DEFAULT_MAX_DEPARTED_FRACTION,
        help="refuse to reconcile if more than this share of assigned players is absent from the feed",
    )
    parser.add_argument("--json", metavar="PATH", default=None, help="write the plan (incl. cleared assignments) as JSON")
    args = parser.parse_args()

    def _write_json(plan: RosterPlan) -> None:
        Path(args.json).write_text(json.dumps(plan.to_dict(), indent=2) + "\n")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)

    try:
        result = load_current_rosters(
            args.season,
            reconcile=not args.upsert_only,
            dry_run=args.dry_run,
            max_departed_fraction=args.max_departed_fraction,
            on_plan=_write_json if args.json else None,
        )
    except RosterCompletenessError as exc:
        for problem in exc.problems:
            print(problem, file=sys.stderr)
        sys.exit(1)
    if args.dry_run and not result.complete:
        for problem in result.problems:
            print(problem, file=sys.stderr)
        sys.exit(1)
