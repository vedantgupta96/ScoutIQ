"""Import a cached ESPN roster and season-to-date snapshot into production tables.

Reads a snapshot written by `collect_espn_refresh` plus the identity map written by
`resolve_espn_identity`, plans every change in memory, and writes only when the plan has no
problems: new `players`, current-team assignments (departed players are cleared), the
`player_external_ids` mapping, and `player_seasons` box totals stamped with their ESPN
source and fetch time. Only an in-progress season after the `LATEST_SEASON` baseline is
accepted, and existing nba.com rows are never overwritten. Season rows carry no team
because ESPN season totals do not split by team, so the source does not establish one.
Every response must be fresh, every roster athlete needs an explained stat outcome, and an
older snapshot never overwrites newer stored data (checked in the plan and again in the
write conditions).

Usage:
    python -m scoutiq.etl.import_espn_snapshot --snapshot-dir DIR --dry-run --json plan.json
    python -m scoutiq.etl.import_espn_snapshot --snapshot-dir DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from scoutiq.api.season import LATEST_SEASON, is_completed_season, is_valid_season
from scoutiq.db import get_session
from scoutiq.etl import collect_espn_refresh
from scoutiq.etl.load_current_rosters import DEFAULT_MAX_DEPARTED_FRACTION, plan_roster_refresh
from scoutiq.models import CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX, Player, PlayerExternalId, PlayerSeason
from scoutiq.sources import espn, nba

SOURCE = "espn"
DEFAULT_MAX_SNAPSHOT_AGE_HOURS = 36
EXPECTED_ROSTER_TEAMS = 30


class ImportRefused(RuntimeError):
    """The snapshot plan has problems; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass
class ImportPlan:
    season: str
    source: str
    snapshot_generated_at_utc: str | None = None
    new_players: list[dict] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)
    departed: list[dict] = field(default_factory=list)
    moved: list[dict] = field(default_factory=list)
    added: int = 0
    unchanged: int = 0
    departed_updated_at: datetime | None = None
    external_ids: list[dict] = field(default_factory=list)
    stat_rows: list[dict] = field(default_factory=list)
    stat_inserts: int = 0
    stat_updates: int = 0
    without_stats: list[dict] = field(default_factory=list)
    new_player_teams: dict[int, str] = field(default_factory=dict)
    by_roster_team: dict[str, dict[str, int]] = field(default_factory=dict)
    identity_by_basis: dict[str, int] = field(default_factory=dict)
    identity_overrides: list[dict] = field(default_factory=list)
    roster_times: list[str] = field(default_factory=list)
    stat_times: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        totals = {
            "gp": sum(r["gp"] for r in self.stat_rows),
            "minutes": sum(r["minutes"] for r in self.stat_rows),
            "pts": sum(r["box"]["PTS"] for r in self.stat_rows),
        }
        return {
            "season": self.season,
            "source": self.source,
            "complete": self.complete,
            "problems": list(self.problems),
            "source_timestamps": {
                "roster_oldest": min(self.roster_times, default=None),
                "roster_newest": max(self.roster_times, default=None),
                "stats_oldest": min(self.stat_times, default=None),
                "stats_newest": max(self.stat_times, default=None),
                "snapshot_generated_at_utc": self.snapshot_generated_at_utc,
            },
            "identity": {
                "by_basis": dict(self.identity_by_basis),
                "new_players": len(self.new_players),
                "overrides": list(self.identity_overrides),
            },
            "roster": {
                "counts": {
                    "assigned": len(self.assignments),
                    "added": self.added,
                    "moved": len(self.moved),
                    "unchanged": self.unchanged,
                    "departed": len(self.departed),
                    "new_players": len(self.new_players),
                },
                "new_players": [
                    {"full_name": p["full_name"], "team": self.new_player_teams.get(p["player_id"])}
                    for p in self.new_players
                ],
                "moved": [
                    {
                        "full_name": m["full_name"],
                        "previous_team_id": m["previous_team_id"],
                        "current_team_id": m["current_team_id"],
                    }
                    for m in self.moved
                ],
                "departed": [
                    {"full_name": d["full_name"], "previous_team_id": d["previous_team_id"]}
                    for d in self.departed
                ],
            },
            "stats": {
                "rostered": len(self.stat_rows) + len(self.without_stats),
                "with_stats": len(self.stat_rows),
                "without_stats": list(self.without_stats),
                "inserts": self.stat_inserts,
                "updates": self.stat_updates,
                "by_roster_team": {k: dict(v) for k, v in sorted(self.by_roster_team.items())},
                "totals": totals,
                "max_gp": max((r["gp"] for r in self.stat_rows), default=0),
            },
        }


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_snapshot(snapshot_dir: Path) -> dict:
    snapshot_dir = Path(snapshot_dir)
    manifest = collect_espn_refresh._read_json(snapshot_dir / "manifest.json")
    roster = collect_espn_refresh._read_json(snapshot_dir / "normalized_roster.json")
    season = manifest["season"]
    on_roster = {row["provider_id"] for row in roster}
    problems: list[str] = []

    roster_fetched: dict[int, str] = {}
    for team_provider_id in sorted({row["current_team_provider_id"] for row in roster}):
        path = snapshot_dir / "raw" / "rosters" / f"{team_provider_id}.json"
        try:
            roster_fetched[team_provider_id] = str(collect_espn_refresh._read_json(path)["fetched_at_utc"])
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(f"roster response for team {team_provider_id} is missing or unreadable")

    stats: dict[int, dict[str, Any]] = {}
    none_played: list[int] = []
    for path in sorted((snapshot_dir / "raw" / "stats").glob("*.json")):
        try:
            athlete_id = int(path.stem)
        except ValueError:
            problems.append(f"stat file {path.name} does not have an athlete id name")
            continue
        if athlete_id not in on_roster:
            problems.append(f"stat file for athlete {athlete_id} who is not on the roster")
            continue
        try:
            envelope = collect_espn_refresh._read_json(path)
            parsed = espn.parse_season_totals(envelope["payload"], athlete_id, season)
            entry = {
                "parsed": parsed,
                "fetched_at_utc": str(envelope["fetched_at_utc"]),
                "source_url": envelope.get("source_url"),
            }
        except (OSError, ValueError, KeyError, TypeError, espn.ESPNValidationError) as exc:
            problems.append(f"stat file for athlete {athlete_id} failed validation: {exc}")
            continue
        if parsed["gp"] == 0:
            none_played.append(athlete_id)
        else:
            stats[athlete_id] = entry
    return {
        "manifest": manifest,
        "roster": roster,
        "roster_fetched_at": roster_fetched,
        "stats": stats,
        "none_played": none_played,
        "problems": problems,
    }


def _try_time(value: Any) -> datetime | None:
    try:
        return _parse_time(value)
    except (TypeError, ValueError):
        return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _older_problem(label: str, offenders: list[tuple[int, datetime, datetime]]) -> str:
    first = offenders[0]
    return (
        f"{len(offenders)} {label} (first ids: {[o[0] for o in offenders[:10]]}); "
        f"first offender snapshot time {first[1].isoformat()} is older than stored {first[2].isoformat()}"
    )


def _age_on(date_of_birth: str | None, on: datetime) -> int | None:
    if not date_of_birth:
        return None
    born, today = datetime.fromisoformat(date_of_birth).date(), on.astimezone(timezone.utc).date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def build_plan(
    snapshot: dict,
    identity_map: dict,
    *,
    season: str,
    existing_assignments: Iterable[tuple],
    stored_player_ids: Iterable[int],
    existing_season_rows: dict[int, tuple[str | None, datetime | None]],
    existing_external_ids: dict[str, int],
    team_ids: set,
    now: datetime,
    stored_team_times: dict[int, datetime] | None = None,
    max_departed_fraction: float = DEFAULT_MAX_DEPARTED_FRACTION,
    max_snapshot_age_hours: float = DEFAULT_MAX_SNAPSHOT_AGE_HOURS,
) -> ImportPlan:
    manifest, roster = snapshot["manifest"], snapshot["roster"]
    source = f"{SOURCE}.roster:{season}"
    plan = ImportPlan(season=season, source=source, snapshot_generated_at_utc=manifest.get("generated_at_utc"))
    problems = plan.problems

    if not is_valid_season(season):
        problems.append(f"season {season!r} is not a valid YYYY-YY label")
    elif is_completed_season(season):
        problems.append(
            f"{season} is a completed season; ESPN snapshots are only imported for an in-progress "
            f"season after the {LATEST_SEASON} baseline"
        )
    if manifest.get("season") != season:
        problems.append(f"manifest season {manifest.get('season')!r} does not match {season!r}")
    if manifest.get("errors"):
        problems.append(f"manifest records {len(manifest['errors'])} collection errors")
    counts = manifest.get("counts")
    if not counts or counts.get("validated_roster_teams") != EXPECTED_ROSTER_TEAMS:
        problems.append(f"manifest does not show {EXPECTED_ROSTER_TEAMS} validated roster teams")
    problems.extend(snapshot["problems"])

    on_roster = {row["provider_id"] for row in roster}
    if identity_map.get("season") != manifest.get("season"):
        problems.append(f"identity map season {identity_map.get('season')!r} differs from the manifest")
    if identity_map.get("snapshot_generated_at_utc") != manifest.get("generated_at_utc"):
        problems.append("identity map was resolved from a different snapshot than the manifest")
    if identity_map.get("unresolved"):
        problems.append(f"identity map has {len(identity_map['unresolved'])} unresolved athletes")
    resolved: dict[int, dict] = {}
    for row in identity_map.get("resolved", []):
        resolved.setdefault(row["provider_id"], row)
    missing_identity = sorted(on_roster - resolved.keys())
    if missing_identity:
        problems.append(
            f"{len(missing_identity)} roster athletes have no resolved identity (first ids: {missing_identity[:10]})"
        )
    extra_identity = sorted(resolved.keys() - on_roster)
    if extra_identity:
        problems.append(
            f"{len(extra_identity)} resolved identities are not on the roster (first ids: {extra_identity[:10]})"
        )
    claimed: dict[int, int] = {}
    duplicated: set[int] = set()
    for row in identity_map.get("resolved", []):
        if row["nba_id"] in claimed and claimed[row["nba_id"]] != row["provider_id"]:
            duplicated.add(row["nba_id"])
        claimed.setdefault(row["nba_id"], row["provider_id"])
    if duplicated:
        problems.append(f"nba ids resolved for more than one athlete: {sorted(duplicated)[:10]}")

    existing_mapped_players = {player_id: external for external, player_id in existing_external_ids.items()}
    athletes = [(row, resolved[row["provider_id"]]) for row in roster if row["provider_id"] in resolved]
    conflicting_ids = [
        row["provider_id"] for row, identity in athletes
        if existing_external_ids.get(str(row["provider_id"]), identity["nba_id"]) != identity["nba_id"]
        or existing_mapped_players.get(identity["nba_id"], str(row["provider_id"])) != str(row["provider_id"])
    ]
    if conflicting_ids:
        problems.append(
            f"{len(conflicting_ids)} ESPN ids conflict with stored external id mappings "
            f"(first ids: {sorted(conflicting_ids)[:10]})"
        )

    roster_stamps = {t: (v, _try_time(v)) for t, v in snapshot["roster_fetched_at"].items()}
    stat_stamps = {p: (e["fetched_at_utc"], _try_time(e["fetched_at_utc"])) for p, e in snapshot["stats"].items()}
    bad_stamps = [k for k, (_, t) in roster_stamps.items() if t is None] + [
        k for k, (_, t) in stat_stamps.items() if t is None
    ]
    if bad_stamps:
        problems.append(f"{len(bad_stamps)} responses have a missing or unparseable fetched_at_utc")
    plan.roster_times = sorted(v for v, t in roster_stamps.values() if t is not None)
    plan.stat_times = sorted(v for v, t in stat_stamps.values() if t is not None)
    cutoff = now - timedelta(hours=max_snapshot_age_hours)
    stale_roster = [v for v in plan.roster_times if _parse_time(v) < cutoff]
    stale_stats = [v for v in plan.stat_times if _parse_time(v) < cutoff]
    if stale_roster or stale_stats:
        oldest = min(stale_roster + stale_stats, key=_parse_time)
        problems.append(
            f"{len(stale_roster)} roster and {len(stale_stats)} stat responses are older than "
            f"{max_snapshot_age_hours:g} hours before {now.isoformat()}; oldest is {oldest}"
        )

    feed_rows = [
        {"player_id": identity["nba_id"], "full_name": identity["player_full_name"], "current_team_id": row["scoutiq_team_id"]}
        for row, identity in athletes
    ]
    roster_plan = plan_roster_refresh(
        feed_rows,
        [tuple(r) for r in existing_assignments],
        team_ids,
        season=season,
        source=source,
        max_departed_fraction=max_departed_fraction,
    )
    problems.extend(roster_plan.problems)
    plan.departed, plan.moved = roster_plan.departed, roster_plan.moved
    plan.added, plan.unchanged = roster_plan.added, roster_plan.unchanged
    plan.departed_updated_at = (
        _parse_time(min(plan.roster_times, key=_parse_time))
        if plan.roster_times and all(t is not None for _, t in roster_stamps.values())
        else None
    )

    stat_ids, zero_ids = set(snapshot["stats"]), set(snapshot["none_played"])
    missing_entries = list(manifest.get("missing_stats", []))
    not_found = {e.get("provider_id") for e in missing_entries if e.get("status") == 404}
    bad_status = [e.get("provider_id") for e in missing_entries if e.get("status") != 404]
    if bad_status:
        problems.append(f"{len(bad_status)} missing_stats entries are not HTTP 404 (first ids: {bad_status[:10]})")
    stray = sorted(
        e.get("provider_id") for e in missing_entries if e.get("provider_id") not in on_roster
    )
    if stray:
        problems.append(f"{len(stray)} missing_stats entries are not on the roster (first ids: {stray[:10]})")
    unexplained = [r["provider_id"] for r in roster if not ({r["provider_id"]} & (stat_ids | zero_ids | not_found))]
    if unexplained:
        problems.append(
            f"{len(unexplained)} roster athletes have no stat response and no recorded 404 "
            f"(first ids: {unexplained[:10]})"
        )
    doubled = [
        r["provider_id"] for r in roster
        if r["provider_id"] in not_found and r["provider_id"] in (stat_ids | zero_ids)
    ]
    if doubled:
        problems.append(
            f"{len(doubled)} roster athletes have both a stat response and a recorded 404 "
            f"(first ids: {doubled[:10]})"
        )
    if counts:
        for name, actual in (
            ("roster_athletes", len(roster)),
            ("validated_stats", len(stat_ids)),
            ("missing_stats", sum(1 for e in missing_entries if e.get("status") == 404)),
            ("none_played", len(zero_ids)),
        ):
            if counts.get(name) != actual:
                problems.append(f"manifest counts.{name} is {counts.get(name)!r} but the snapshot has {actual}")

    stored = set(stored_player_ids)
    missing_stats = not_found
    none_played = zero_ids
    non_espn: list[int] = []
    older_assignments: list[tuple[int, datetime, datetime]] = []
    older_stats: list[tuple[int, datetime, datetime]] = []
    stored_times = {k: _aware(v) for k, v in (stored_team_times or {}).items()}
    for row, identity in athletes:
        nba_id = identity["nba_id"]
        team_time = snapshot["roster_fetched_at"].get(row["current_team_provider_id"])
        assigned_at = _try_time(team_time) if team_time else None
        stored_at = stored_times.get(nba_id)
        if assigned_at is not None and stored_at is not None and assigned_at < stored_at:
            older_assignments.append((nba_id, assigned_at, stored_at))
        plan.assignments.append({
            "player_id": nba_id,
            "full_name": identity["player_full_name"],
            "current_team_id": row["scoutiq_team_id"],
            "current_team_source": source,
            "current_team_updated_at": assigned_at,
        })
        if identity["is_new_player"] and nba_id not in stored:
            plan.new_players.append({"player_id": nba_id, "full_name": identity["player_full_name"]})
            plan.new_player_teams[nba_id] = row["current_team_abbreviation"]
        plan.identity_by_basis[identity["basis"]] = plan.identity_by_basis.get(identity["basis"], 0) + 1
        if identity.get("override_reason"):
            plan.identity_overrides.append(
                {"full_name": identity["player_full_name"], "nba_id": nba_id, "reason": identity["override_reason"]}
            )
        plan.external_ids.append({
            "player_id": nba_id,
            "source": SOURCE,
            "external_id": str(row["provider_id"]),
            "match_basis": identity["basis"],
            "evidence": {
                "sources": identity["sources"],
                "espn_full_name": row["full_name"],
                "espn_date_of_birth": row["date_of_birth"],
                "override_reason": identity.get("override_reason"),
            },
            "matched_at": now,
        })
        team = plan.by_roster_team.setdefault(row["current_team_abbreviation"], {"rostered": 0, "with_stats": 0})
        team["rostered"] += 1
        entry = snapshot["stats"].get(row["provider_id"])
        if entry is None:
            if row["provider_id"] in none_played:
                reason = "zero games played"
            elif row["provider_id"] in missing_stats:
                reason = "no ESPN regular-season stat record (HTTP 404)"
            else:
                reason = "no stat response in snapshot"
            plan.without_stats.append({
                "player_id": nba_id,
                "full_name": identity["player_full_name"],
                "team": row["current_team_abbreviation"],
                "reason": reason,
            })
            continue
        team["with_stats"] += 1
        fetched = _try_time(entry["fetched_at_utc"])
        if fetched is None:
            continue
        parsed = entry["parsed"]
        plan.stat_rows.append({
            "player_id": nba_id,
            "season": season,
            "team_id": None,
            "age": _age_on(row["date_of_birth"], fetched),
            "gp": parsed["gp"],
            "minutes": parsed["minutes"],
            "box": parsed["box"],
            "source": SOURCE,
            "source_fetched_at": fetched,
        })
        if nba_id in existing_season_rows:
            plan.stat_updates += 1
            stored_source, stored_fetched = existing_season_rows[nba_id]
            if stored_source != SOURCE:
                non_espn.append(nba_id)
            elif stored_fetched is not None and fetched < _aware(stored_fetched):
                older_stats.append((nba_id, fetched, _aware(stored_fetched)))
        else:
            plan.stat_inserts += 1
    if non_espn:
        problems.append(
            f"{len(non_espn)} players already have a {season} player_seasons row from another source "
            f"(first ids: {sorted(non_espn)[:10]})"
        )
    older_departed = [
        (d["player_id"], plan.departed_updated_at, stored_times[d["player_id"]])
        for d in plan.departed
        if plan.departed_updated_at is not None
        and d["player_id"] in stored_times
        and stored_times[d["player_id"]] > plan.departed_updated_at
    ]
    if older_assignments:
        problems.append(_older_problem("team assignments are older than stored current-team data", older_assignments))
    if older_departed:
        problems.append(_older_problem("departed-player clears are older than stored current-team data", older_departed))
    if older_stats:
        problems.append(_older_problem("stat rows are older than the stored ESPN row", older_stats))
    return plan


def espn_season_upsert(rows: list[dict]):
    """Upsert box-only rows; a row stamped by any other source is left untouched."""
    stmt = insert(PlayerSeason).values(rows)
    return stmt.on_conflict_do_update(
        index_elements=["player_id", "season"],
        set_={
            "age": stmt.excluded.age,
            "gp": stmt.excluded.gp,
            "minutes": stmt.excluded.minutes,
            "box": stmt.excluded.box,
            "team_id": stmt.excluded.team_id,
            "source": stmt.excluded.source,
            "source_fetched_at": stmt.excluded.source_fetched_at,
        },
        where=and_(
            PlayerSeason.source == SOURCE,
            or_(
                PlayerSeason.source_fetched_at.is_(None),
                PlayerSeason.source_fetched_at <= stmt.excluded.source_fetched_at,
            ),
        ),
    )


def apply_plan(session, plan: ImportPlan) -> None:
    if plan.new_players:
        session.execute(
            insert(Player).values(plan.new_players).on_conflict_do_nothing(index_elements=["player_id"])
        )
    if plan.assignments:
        stmt = insert(Player).values(plan.assignments)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["player_id"],
                set_={
                    "current_team_id": stmt.excluded.current_team_id,
                    "current_team_source": stmt.excluded.current_team_source,
                    "current_team_updated_at": stmt.excluded.current_team_updated_at,
                },
                where=or_(
                    Player.current_team_updated_at.is_(None),
                    Player.current_team_updated_at <= stmt.excluded.current_team_updated_at,
                ),
            )
        )
    if plan.departed and plan.departed_updated_at is not None:
        session.execute(
            update(Player)
            .where(Player.player_id.in_([d["player_id"] for d in plan.departed]))
            .where(or_(
                Player.current_team_updated_at.is_(None),
                Player.current_team_updated_at <= plan.departed_updated_at,
            ))
            .values(
                current_team_id=None,
                current_team_source=plan.source + CURRENT_TEAM_NOT_ON_ROSTER_SUFFIX,
                current_team_updated_at=plan.departed_updated_at,
            )
        )
    if plan.external_ids:
        stmt = insert(PlayerExternalId).values(plan.external_ids)
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_player_external_id_source_external",
                set_={
                    "match_basis": stmt.excluded.match_basis,
                    "evidence": stmt.excluded.evidence,
                    "matched_at": stmt.excluded.matched_at,
                },
                where=PlayerExternalId.player_id == stmt.excluded.player_id,
            )
        )
    if plan.stat_rows:
        session.execute(espn_season_upsert(plan.stat_rows))


def _summary(plan: ImportPlan, *, dry_run: bool) -> str:
    return (
        f"espn_import{' (dry run)' if dry_run else ''}: {plan.source} assigned {len(plan.assignments)}, "
        f"new players {len(plan.new_players)}, moved {len(plan.moved)}, departed {len(plan.departed)}, "
        f"stat inserts {plan.stat_inserts}, updates {plan.stat_updates}, "
        f"without stats {len(plan.without_stats)}, problems {len(plan.problems)}"
    )


def run(
    snapshot_dir: Path,
    *,
    season: str,
    identity_map_path: Path | None = None,
    dry_run: bool = False,
    max_departed_fraction: float = DEFAULT_MAX_DEPARTED_FRACTION,
    max_snapshot_age_hours: float = DEFAULT_MAX_SNAPSHOT_AGE_HOURS,
    now: datetime | None = None,
    on_plan: Callable[[ImportPlan], None] | None = None,
) -> ImportPlan:
    snapshot_dir = Path(snapshot_dir)
    snapshot = load_snapshot(snapshot_dir)
    identity_map = collect_espn_refresh._read_json(identity_map_path or snapshot_dir / "identity_map.json")
    team_ids = {t["team_id"] for t in nba.team_rows()}
    now = now or datetime.now(tz=timezone.utc)

    with get_session() as session:
        existing_assignments = [
            tuple(r) for r in session.execute(
                select(Player.player_id, Player.full_name, Player.current_team_id)
                .where(Player.current_team_id.is_not(None))
            ).all()
        ]
        existing_season_rows = {
            player_id: (source, fetched_at) for player_id, source, fetched_at in session.execute(
                select(PlayerSeason.player_id, PlayerSeason.source, PlayerSeason.source_fetched_at)
                .where(PlayerSeason.season == season)
            ).all()
        }
        stored_team_times = {
            player_id: updated_at for player_id, updated_at in session.execute(
                select(Player.player_id, Player.current_team_updated_at)
                .where(Player.current_team_updated_at.is_not(None))
            ).all()
        }
        stored_player_ids = [player_id for (player_id,) in session.execute(select(Player.player_id)).all()]
        existing_external_ids = {
            external_id: player_id for external_id, player_id in session.execute(
                select(PlayerExternalId.external_id, PlayerExternalId.player_id)
                .where(PlayerExternalId.source == SOURCE)
            ).all()
        }
        plan = build_plan(
            snapshot,
            identity_map,
            season=season,
            existing_assignments=existing_assignments,
            stored_player_ids=stored_player_ids,
            existing_season_rows=existing_season_rows,
            existing_external_ids=existing_external_ids,
            team_ids=team_ids,
            now=now,
            stored_team_times=stored_team_times,
            max_departed_fraction=max_departed_fraction,
            max_snapshot_age_hours=max_snapshot_age_hours,
        )
        if on_plan is not None:
            on_plan(plan)
        if dry_run:
            print(_summary(plan, dry_run=True))
            return plan
        if plan.problems:
            raise ImportRefused(plan.problems)
        apply_plan(session, plan)
    print(_summary(plan, dry_run=False))
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a cached ESPN snapshot.")
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--season", default="2026-27", help="in-progress season, default 2026-27")
    parser.add_argument("--identity-map", type=Path, default=None, help="default: <snapshot-dir>/identity_map.json")
    parser.add_argument("--dry-run", action="store_true", help="plan and report only; write nothing")
    parser.add_argument("--json", metavar="PATH", default=None, help="write the plan report as JSON")
    parser.add_argument("--max-departed-fraction", type=float, default=DEFAULT_MAX_DEPARTED_FRACTION)
    parser.add_argument("--max-snapshot-age-hours", type=float, default=DEFAULT_MAX_SNAPSHOT_AGE_HOURS)
    args = parser.parse_args(argv)

    def _write_report(plan: ImportPlan) -> None:
        Path(args.json).write_text(json.dumps(plan.to_dict(), indent=2) + "\n")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    try:
        plan = run(
            args.snapshot_dir,
            season=args.season,
            identity_map_path=args.identity_map,
            dry_run=args.dry_run,
            max_departed_fraction=args.max_departed_fraction,
            max_snapshot_age_hours=args.max_snapshot_age_hours,
            on_plan=_write_report if args.json else None,
        )
    except ImportRefused as exc:
        for problem in exc.problems:
            print(problem, file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.dry_run and not plan.complete:
        for problem in plan.problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
