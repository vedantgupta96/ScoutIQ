"""Transactional, idempotent, dry-run-by-default apply of the validated Sports Reference salary export.

Usage:
    python -m scoutiq.etl.apply_sportsref_salaries apply --snapshot DIR [--json PATH] [--apply --confirm SHA12]
    python -m scoutiq.etl.apply_sportsref_salaries rollback --snapshot DIR [--apply --confirm SHA12]

Writes player_team_salaries (raw per-team evidence) and, for unambiguous single-obligation players,
contracts + contract_years. Never writes player_salaries and never overwrites stored rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from scoutiq.etl.plan_sportsref_salaries import (
    DbState,
    StoredContract,
    _compare_contract,
    _counts,
    _stored_option,
    classify_identity,
    load_verified_snapshot,
    read_db_state,
)
from scoutiq.sources.nba import TEAM_ABBREV_ALIASES
from scoutiq.sources.sportsref_salary_export import ExportFormatError, ParsedExport, parse_export

SOURCE = "sportsref_export"
PLAYER_SALARIES_REASON = (
    "season totals are not derivable from per-team obligation rows; valuation pay remains the "
    "completed-season figure"
)
LOCKED_TABLES = "contracts, contract_years, player_team_salaries"
SPOT_CHECK_IDS = ("jamesle01",)

EXIT_HASH_MISMATCH = 2
EXIT_FORMAT_ERROR = 3
EXIT_CONFIRM = 4
EXIT_CONFLICT = 5
EXIT_VERIFY = 6
EXIT_MIGRATION = 7
MIGRATION_NOTE = "migration 0013_contract_source_ref is required (contracts.source_ref column is missing)"


class ApplyRefused(RuntimeError):
    pass


class ApplyVerificationError(RuntimeError):
    pass


@dataclass
class ApplyExtras:
    team_name_by_id: dict[int, str] = field(default_factory=dict)
    cap_by_season: dict[str, int] = field(default_factory=dict)
    contract_starts: dict[int, set[str]] = field(default_factory=dict)
    all_contracts: dict[int, list[StoredContract]] = field(default_factory=dict)
    existing_team_rows: list[dict] = field(default_factory=list)


def _parse_received(manifest: dict) -> datetime:
    received = datetime.fromisoformat(manifest["received_at_utc"])
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    return received.astimezone(timezone.utc)


def _resolve_abbr(team_abbr: str) -> str:
    return TEAM_ABBREV_ALIASES.get(team_abbr.upper(), team_abbr)


def _is_postgres(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def read_apply_extras(session, pids: list[int]) -> ApplyExtras:
    from sqlalchemy import desc, select
    from sqlalchemy.orm import load_only, selectinload

    from scoutiq.models import CapConstants, Contract, PlayerTeamSalary, Team

    extras = ApplyExtras()
    for tid, name in session.execute(select(Team.team_id, Team.name)):
        if name:
            extras.team_name_by_id[tid] = name
    for season, cap in session.execute(select(CapConstants.season, CapConstants.salary_cap)):
        if cap:
            extras.cap_by_season[season] = cap
    if pids:
        for contract in session.scalars(
            select(Contract)
            .where(Contract.player_id.in_(pids))
            .options(
                load_only(Contract.player_id, Contract.season_start, Contract.source, Contract.scraped_at),
                selectinload(Contract.contract_years),
            )
            .order_by(Contract.player_id, desc(Contract.season_start), desc(Contract.scraped_at))
        ):
            extras.contract_starts.setdefault(contract.player_id, set()).add(contract.season_start)
            extras.all_contracts.setdefault(contract.player_id, []).append(
                StoredContract(
                    source=contract.source,
                    scraped_at=contract.scraped_at.isoformat() if contract.scraped_at else None,
                    season_start=contract.season_start,
                    years=[
                        (cy.season, cy.aav, bool(cy.is_player_option), bool(cy.is_team_option))
                        for cy in contract.contract_years
                    ],
                )
            )
        for row in session.execute(
            select(
                PlayerTeamSalary.id,
                PlayerTeamSalary.player_id,
                PlayerTeamSalary.season,
                PlayerTeamSalary.team_name,
                PlayerTeamSalary.row_ordinal,
                PlayerTeamSalary.salary,
                PlayerTeamSalary.source_ref,
            )
            .where(PlayerTeamSalary.source == SOURCE, PlayerTeamSalary.player_id.in_(pids))
            .order_by(PlayerTeamSalary.id)
        ):
            extras.existing_team_rows.append(
                {
                    "id": row.id,
                    "player_id": row.player_id,
                    "season": row.season,
                    "team_name": row.team_name,
                    "row_ordinal": row.row_ordinal,
                    "salary": row.salary,
                    "source_ref": row.source_ref,
                }
            )
    return extras


def _team_salary_key(pid: int, season: str, team_name: str, ordinal: int) -> tuple:
    return (pid, season, SOURCE, team_name, ordinal)


def _contract_decision(
    bid: str, pid: int, name: str, row, resolved: str | None, team_id: int | None,
    state: DbState, extras: ApplyExtras, first_season: str, received_iso: str,
) -> dict:
    base = {"bbref_id": bid, "player_id": pid, "player_name": name}
    if team_id is None:
        return {**base, "action": "held", "reason": "unknown_team", "team": row.team_abbr}
    if any(y.uncertain for y in row.years):
        return {
            **base,
            "action": "held",
            "reason": "uncertain_cells",
            "team": resolved,
            "seasons": [y.season for y in row.years if y.uncertain],
        }
    schedule = [y for y in row.years if y.amount is not None]
    if not schedule:
        return {**base, "action": "held", "reason": "no_amounts", "team": resolved}
    current_id = state.players.get(pid, (name, None))[1]
    current_abbr = state.abbr_by_team.get(current_id) if current_id is not None else None
    if current_abbr is not None and current_abbr != resolved:
        return {
            **base,
            "action": "held",
            "reason": "team_differs_from_current",
            "team": resolved,
            "current_team": current_abbr,
        }
    stored = state.contracts.get(pid)
    wanted = {y.season: (y.amount, y.option) for y in schedule}
    season_start = schedule[0].season
    if stored is not None:
        stored_by = {s: (aav, _stored_option(po, to)) for s, aav, po, to in stored.years}
        if set(stored_by) & set(wanted):
            relevant = {s: v for s, v in stored_by.items() if s >= first_season}
            if relevant == wanted:
                return {**base, "action": "unchanged", "team": resolved, "season_start": stored.season_start}
            cmp_ = _compare_contract(row, stored, first_season)
            return {
                **base,
                "action": "held",
                "reason": "stored_contract_differs",
                "team": resolved,
                "stored_source": stored.source,
                "stored_season_start": stored.season_start,
                "diff": {s: v for s, v in cmp_["seasons"].items() if v["outcome"] != "same"},
            }
        overlapping = [
            {
                "season_start": c.season_start,
                "source": c.source,
                "seasons": sorted({s for s, *_ in c.years} & set(wanted)),
            }
            for c in extras.all_contracts.get(pid, [])[1:]
            if {s for s, *_ in c.years} & set(wanted)
        ]
        if overlapping:
            return {
                **base,
                "action": "held",
                "reason": "older_contract_overlaps",
                "team": resolved,
                "overlapping_contracts": overlapping,
            }
        if stored.season_start >= season_start:
            return {
                **base,
                "action": "held",
                "reason": "would_not_be_latest",
                "team": resolved,
                "season_start": season_start,
                "latest_stored_season_start": stored.season_start,
            }
    if season_start in extras.contract_starts.get(pid, set()):
        return {**base, "action": "held", "reason": "season_start_collision", "team": resolved, "season_start": season_start}
    guaranteed = row.remaining_guaranteed
    if guaranteed is None:
        return {**base, "action": "held", "reason": "guarantee_unknown", "team": resolved}
    total = sum(y.amount for y in schedule)
    firm_total = sum(y.amount for y in schedule if not y.option)
    has_options = any(y.option for y in schedule)
    if guaranteed == 0:
        basis, flags = "none_guaranteed", [False] * len(schedule)
    elif guaranteed == total:
        basis, flags = "all_guaranteed", [True] * len(schedule)
    elif has_options and guaranteed == firm_total:
        basis, flags = "option_years_unguaranteed", [not y.option for y in schedule]
    else:
        return {
            **base,
            "action": "held",
            "reason": "guarantee_unresolved",
            "team": resolved,
            "remaining_guaranteed": guaranteed,
            "amounts": {y.season: y.amount for y in schedule},
            "options": {y.season: y.option for y in schedule if y.option},
        }
    entries = []
    for idx, y in enumerate(schedule):
        cap = extras.cap_by_season.get(y.season)
        entries.append(
            {
                "season": y.season,
                "aav": y.amount,
                "cap_pct": round(y.amount / cap, 4) if cap else None,
                "option": y.option,
                "is_player_option": y.option == "player_option",
                "is_team_option": y.option == "team_option",
                "is_guaranteed": flags[idx],
            }
        )
    return {
        **base,
        "action": "insert",
        "team": resolved,
        "team_id": team_id,
        "season_start": season_start,
        "years": len(schedule),
        "total_value": sum(y.amount for y in schedule),
        "remaining_guaranteed": guaranteed,
        "guarantee_basis": basis,
        "source": SOURCE,
        "scraped_at": received_iso,
        "schedule": entries,
    }


def build_apply_plan(
    parsed: ParsedExport, state: DbState, extras: ApplyExtras, manifest: dict, snapshot_name: str
) -> dict:
    received = _parse_received(manifest)
    received_iso = received.isoformat()
    fetched_on = received.date().isoformat()
    first_season = parsed.seasons[0] if parsed.seasons else ""
    rows_by_id: dict[str, list] = {}
    for row in parsed.rows:
        rows_by_id.setdefault(row.bbref_id, []).append(row)
    distinct_ids = sorted(rows_by_id)
    matched, unmatched, not_verified, ambiguous = classify_identity(distinct_ids, state)
    existing = {
        _team_salary_key(r["player_id"], r["season"], r["team_name"], r["row_ordinal"]): r
        for r in extras.existing_team_rows
    }

    def player_name(bid: str) -> str:
        pid = matched.get(bid)
        if pid is not None and pid in state.players:
            return state.players[pid][0]
        return rows_by_id[bid][0].player_name

    ts_insert: list[dict] = []
    ts_unchanged: list[dict] = []
    ts_conflicts: list[dict] = []
    ts_uncertain: list[dict] = []
    ts_held: list[dict] = []
    ts_by_bbref: dict[str, list[dict]] = {}
    row_team: dict[tuple[str, int], tuple[str, int | None]] = {}
    for row in parsed.rows:
        bid = row.bbref_id
        resolved = _resolve_abbr(row.team_abbr)
        team_id = state.team_by_abbr.get(resolved)
        team_name = extras.team_name_by_id.get(team_id) if team_id is not None else None
        row_team[(bid, row.row_ordinal)] = (resolved, team_id)
        held = {"bbref_id": bid, "player_name": row.player_name, "row_ordinal": row.row_ordinal, "team": row.team_abbr}
        if bid in unmatched:
            ts_held.append({**held, "reason": "not_matched"})
            continue
        if bid in not_verified:
            ts_held.append({**held, "reason": "not_verified", "xref_status": not_verified[bid]})
            continue
        if bid in ambiguous:
            ts_held.append({**held, "reason": "ambiguous_identity", "player_ids": ambiguous[bid]})
            continue
        pid = matched[bid]
        if team_name is None:
            ts_held.append({**held, "player_id": pid, "reason": "unknown_team"})
            continue
        for y in row.years:
            if y.uncertain:
                ts_uncertain.append(
                    {
                        "bbref_id": bid,
                        "player_id": pid,
                        "row_ordinal": row.row_ordinal,
                        "team": resolved,
                        "season": y.season,
                        "reason": y.uncertain,
                    }
                )
                continue
            if y.amount is None:
                continue
            item = {
                "bbref_id": bid,
                "player_name": player_name(bid),
                "player_id": pid,
                "season": y.season,
                "team_name": team_name,
                "team_abbr": resolved,
                "team_id": team_id,
                "row_ordinal": row.row_ordinal,
                "salary": y.amount,
                "source": SOURCE,
                "source_ref": snapshot_name,
                "source_fetched_on": fetched_on,
            }
            stored = existing.get(_team_salary_key(pid, y.season, team_name, row.row_ordinal))
            if stored is None:
                item["action"] = "insert"
                ts_insert.append(item)
            elif stored["salary"] == y.amount:
                item["action"] = "unchanged"
                ts_unchanged.append(item)
            else:
                item["action"] = "conflict"
                ts_conflicts.append({**item, "stored_salary": stored["salary"], "stored_id": stored["id"]})
            ts_by_bbref.setdefault(bid, []).append(item)

    contract_results: dict[str, dict] = {}
    for bid in distinct_ids:
        rows = rows_by_id[bid]
        base = {"bbref_id": bid, "player_name": rows[0].player_name}
        if bid in unmatched:
            contract_results[bid] = {**base, "action": "held", "reason": "not_matched"}
        elif bid in not_verified:
            contract_results[bid] = {**base, "action": "held", "reason": "not_verified"}
        elif bid in ambiguous:
            contract_results[bid] = {**base, "action": "held", "reason": "ambiguous_identity"}
        elif len(rows) > 1:
            contract_results[bid] = {
                **base,
                "player_id": matched[bid],
                "action": "held",
                "reason": "multi_obligation",
                "rows": len(rows),
            }
        else:
            row = rows[0]
            resolved, team_id = row_team[(bid, row.row_ordinal)]
            contract_results[bid] = _contract_decision(
                bid, matched[bid], player_name(bid), row, resolved, team_id,
                state, extras, first_season, received_iso,
            )
    c_insert = [r for r in contract_results.values() if r["action"] == "insert"]
    c_unchanged = [r for r in contract_results.values() if r["action"] == "unchanged"]
    c_held = [r for r in contract_results.values() if r["action"] == "held"]

    spot_checks = {}
    for bid in SPOT_CHECK_IDS:
        if bid in rows_by_id:
            spot_checks[bid] = {
                "contract": contract_results[bid],
                "team_salary_rows": ts_by_bbref.get(bid, []),
                "team_salary_held_rows": [h for h in ts_held if h["bbref_id"] == bid],
            }

    planned = {
        "contracts": len(c_insert),
        "contract_years": sum(len(r["schedule"]) for r in c_insert),
        "player_team_salaries": len(ts_insert),
    }
    return {
        "provenance": {
            "sha256": manifest.get("sha256"),
            "snapshot": snapshot_name,
            "received_at_utc": received_iso,
            "source": SOURCE,
            "source_ref": snapshot_name,
            "source_fetched_on": fetched_on,
        },
        "planned_inserts": planned,
        "team_salaries": {
            "counts": {
                "insert": len(ts_insert),
                "unchanged": len(ts_unchanged),
                "conflict": len(ts_conflicts),
                "held_uncertain_cells": len(ts_uncertain),
                "held_rows": _counts(h["reason"] for h in ts_held),
            },
            "insert": ts_insert,
            "unchanged": ts_unchanged,
            "conflicts": ts_conflicts,
            "held_uncertain_cells": ts_uncertain,
            "held_rows": ts_held,
        },
        "contracts": {
            "counts": {
                "insert": len(c_insert),
                "unchanged": len(c_unchanged),
                "held": _counts(r["reason"] for r in c_held),
            },
            "insert": c_insert,
            "unchanged": c_unchanged,
            "held": c_held,
        },
        "player_salaries": {"written": 0, "reason": PLAYER_SALARIES_REASON},
        "spot_checks": spot_checks,
    }


def render_apply_summary(plan: dict, mode: str) -> str:
    p, ts, c = plan["provenance"], plan["team_salaries"]["counts"], plan["contracts"]["counts"]
    pi = plan["planned_inserts"]
    return "\n".join(
        [
            f"mode: {mode}",
            f"snapshot {p['snapshot']} sha256 {p['sha256']} received {p['received_at_utc']}",
            f"player_team_salaries: insert {ts['insert']}, unchanged {ts['unchanged']}, conflict {ts['conflict']}, "
            f"held uncertain cells {ts['held_uncertain_cells']}, held rows {ts['held_rows']}",
            f"contracts: insert {c['insert']}, unchanged {c['unchanged']}, held {c['held']}",
            f"planned inserts: contracts {pi['contracts']}, contract_years {pi['contract_years']}, "
            f"player_team_salaries {pi['player_team_salaries']}",
            f"player_salaries: not written ({plan['player_salaries']['reason']})",
        ]
    )


def _count_tables(session) -> dict[str, int]:
    from sqlalchemy import func, select

    from scoutiq.models import Contract, ContractYear, PlayerTeamSalary

    return {
        "contracts": session.scalar(select(func.count()).select_from(Contract)),
        "contract_years": session.scalar(select(func.count()).select_from(ContractYear)),
        "player_team_salaries": session.scalar(select(func.count()).select_from(PlayerTeamSalary)),
    }


def _read_plan(session, parsed: ParsedExport, manifest: dict, snapshot_name: str, read_only: bool):
    state = read_db_state(
        session, {r.bbref_id for r in parsed.rows}, parsed.seasons, None, read_only=read_only
    )
    pids = sorted({p for ps in state.verified_xref.values() for p in ps})
    extras = read_apply_extras(session, pids)
    return state, extras, build_apply_plan(parsed, state, extras, manifest, snapshot_name)


def _before_records(plan: dict, state: DbState, extras: ApplyExtras) -> list[dict]:
    affected = {r["player_id"] for r in plan["contracts"]["insert"]} | {
        r["player_id"] for r in plan["team_salaries"]["insert"]
    }
    out = []
    for pid in sorted(affected):
        stored = state.contracts.get(pid)
        out.append(
            {
                "player_id": pid,
                "latest_contract": (
                    {
                        "source": stored.source,
                        "season_start": stored.season_start,
                        "scraped_at": stored.scraped_at,
                        "years": [list(y) for y in stored.years],
                    }
                    if stored
                    else None
                ),
                "existing_team_salaries": [r for r in extras.existing_team_rows if r["player_id"] == pid],
            }
        )
    return out


def apply_in_transaction(session, parsed: ParsedExport, manifest: dict, snapshot_name: str, now: datetime) -> dict:
    from sqlalchemy import text

    from scoutiq.models import Contract, ContractYear, PlayerTeamSalary

    if _is_postgres(session):
        session.execute(text(f"LOCK TABLE {LOCKED_TABLES} IN SHARE ROW EXCLUSIVE MODE"))
    state, extras, plan = _read_plan(session, parsed, manifest, snapshot_name, read_only=False)
    conflicts = plan["team_salaries"]["conflicts"]
    if conflicts:
        raise ApplyRefused(f"{len(conflicts)} player_team_salaries conflict(s); nothing written")
    before = _count_tables(session)
    before_records = _before_records(plan, state, extras)
    received = _parse_received(manifest)

    contracts = []
    for item in plan["contracts"]["insert"]:
        contract = Contract(
            player_id=item["player_id"],
            team_id=item["team_id"],
            season_start=item["season_start"],
            years=item["years"],
            total_value=item["total_value"],
            source=SOURCE,
            scraped_at=received,
            source_ref=snapshot_name,
            contract_years=[
                ContractYear(
                    season=y["season"],
                    aav=y["aav"],
                    cap_pct=y["cap_pct"],
                    is_guaranteed=y["is_guaranteed"],
                    is_player_option=y["is_player_option"],
                    is_team_option=y["is_team_option"],
                )
                for y in item["schedule"]
            ],
        )
        contracts.append(contract)
    team_rows = [
        PlayerTeamSalary(
            player_id=r["player_id"],
            season=r["season"],
            team_name=r["team_name"],
            team_abbr=r["team_abbr"],
            team_id=r["team_id"],
            row_ordinal=r["row_ordinal"],
            salary=r["salary"],
            source=SOURCE,
            source_ref=r["source_ref"],
            source_fetched_on=date.fromisoformat(r["source_fetched_on"]),
            loaded_at=now,
        )
        for r in plan["team_salaries"]["insert"]
    ]
    session.add_all(contracts)
    session.add_all(team_rows)
    session.flush()
    after = _count_tables(session)
    planned = plan["planned_inserts"]
    expected = {k: before[k] + planned[k] for k in before}
    if after != expected:
        raise ApplyVerificationError(f"table counts after write {after} != expected {expected}")
    return {
        "plan": plan,
        "before_records": before_records,
        "inserted_contract_ids": [c.id for c in contracts],
        "inserted_team_salary_ids": [r.id for r in team_rows],
        "table_counts": {"before": before, "after": after},
    }


def _journal_path(snapshot: Path, prefix: str, now: datetime) -> Path:
    return snapshot / f"{prefix}-{now.strftime('%Y%m%dT%H%M%SZ')}.json"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _apply_journal(snapshot: Path, manifest: dict, confirm: str, result: dict, now: datetime, status: str) -> dict:
    plan = result["plan"]
    return {
        "status": status,
        "sha256": manifest.get("sha256"),
        "confirm": confirm,
        "snapshot": snapshot.name,
        "applied_at_utc": now.isoformat(),
        "plan_summary": {
            "planned_inserts": plan["planned_inserts"],
            "team_salaries": plan["team_salaries"]["counts"],
            "contracts": plan["contracts"]["counts"],
        },
        "before_records": result["before_records"],
        "inserted_contract_ids": result["inserted_contract_ids"],
        "inserted_team_salary_ids": result["inserted_team_salary_ids"],
        "table_counts": result["table_counts"],
    }


def _rollback_journal(snapshot: Path, manifest: dict, confirm: str, result: dict, now: datetime, status: str) -> dict:
    return {
        "status": status,
        "sha256": manifest.get("sha256"),
        "confirm": confirm,
        "snapshot": snapshot.name,
        "rolled_back_at_utc": now.isoformat(),
        "deleted_contract_ids": result["contract_ids"],
        "deleted_contract_year_ids": result["contract_year_ids"],
        "deleted_team_salary_ids": result["team_salary_ids"],
        "players": {str(k): v for k, v in result["players"].items()},
        "table_counts": result["table_counts"],
    }


def _has_source_ref(session) -> bool:
    from sqlalchemy import inspect

    return any(c["name"] == "source_ref" for c in inspect(session.connection()).get_columns("contracts"))


def select_snapshot_rows(session, snapshot_name: str, has_source_ref: bool = True) -> dict:
    from sqlalchemy import select

    from scoutiq.models import Contract, ContractYear, PlayerTeamSalary

    contracts = (
        list(
            session.scalars(
                select(Contract)
                .where(Contract.source == SOURCE, Contract.source_ref == snapshot_name)
                .order_by(Contract.id)
            )
        )
        if has_source_ref
        else []
    )
    contract_ids = [c.id for c in contracts]
    year_ids = (
        list(session.scalars(select(ContractYear.id).where(ContractYear.contract_id.in_(contract_ids))))
        if contract_ids
        else []
    )
    team_rows = list(
        session.scalars(
            select(PlayerTeamSalary)
            .where(PlayerTeamSalary.source == SOURCE, PlayerTeamSalary.source_ref == snapshot_name)
            .order_by(PlayerTeamSalary.id)
        )
    )
    players: dict[int, dict] = {}
    for c in contracts:
        players.setdefault(c.player_id, {"contracts": 0, "team_salary_rows": 0})["contracts"] += 1
    for r in team_rows:
        players.setdefault(r.player_id, {"contracts": 0, "team_salary_rows": 0})["team_salary_rows"] += 1
    return {
        "contract_ids": contract_ids,
        "contract_year_ids": year_ids,
        "team_salary_ids": [r.id for r in team_rows],
        "players": {pid: players[pid] for pid in sorted(players)},
    }


def rollback_in_transaction(session, snapshot_name: str) -> dict:
    from sqlalchemy import delete, text

    from scoutiq.models import Contract, ContractYear, PlayerTeamSalary

    if _is_postgres(session):
        session.execute(text(f"LOCK TABLE {LOCKED_TABLES} IN SHARE ROW EXCLUSIVE MODE"))
    selected = select_snapshot_rows(session, snapshot_name)
    before = _count_tables(session)
    if selected["contract_ids"]:
        session.execute(delete(ContractYear).where(ContractYear.contract_id.in_(selected["contract_ids"])))
        session.execute(delete(Contract).where(Contract.id.in_(selected["contract_ids"])))
    if selected["team_salary_ids"]:
        session.execute(delete(PlayerTeamSalary).where(PlayerTeamSalary.id.in_(selected["team_salary_ids"])))
    session.flush()
    after = _count_tables(session)
    expected = {
        "contracts": before["contracts"] - len(selected["contract_ids"]),
        "contract_years": before["contract_years"] - len(selected["contract_year_ids"]),
        "player_team_salaries": before["player_team_salaries"] - len(selected["team_salary_ids"]),
    }
    if after != expected:
        raise ApplyVerificationError(f"table counts after delete {after} != expected {expected}")
    return {**selected, "table_counts": {"before": before, "after": after}}


def _render_selected(selected: dict) -> str:
    lines = [
        f"contracts {len(selected['contract_ids'])}, contract_years {len(selected['contract_year_ids'])}, "
        f"player_team_salaries {len(selected['team_salary_ids'])}"
    ]
    lines.extend(
        f"  player {pid}: contracts {v['contracts']}, team salary rows {v['team_salary_rows']}"
        for pid, v in selected["players"].items()
    )
    return "\n".join(lines)


def _load(args) -> tuple[Path, dict, ParsedExport | None, int]:
    snapshot = Path(args.snapshot).resolve()
    try:
        html, manifest = load_verified_snapshot(snapshot)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return snapshot, {}, None, EXIT_HASH_MISMATCH
    parsed = None
    if args.command == "apply":
        try:
            parsed = parse_export(html)
        except ExportFormatError as exc:
            print(f"export format error: {exc}", file=sys.stderr)
            return snapshot, manifest, None, EXIT_FORMAT_ERROR
    return snapshot, manifest, parsed, 0


def _check_confirm(args, manifest: dict) -> bool:
    if not args.apply:
        return True
    expected = manifest["sha256"][:12]
    if args.confirm != expected:
        print(f"--apply requires --confirm {expected}; nothing written", file=sys.stderr)
        return False
    return True


def _open_session(session_factory):
    if session_factory is None:
        from scoutiq.db import SessionLocal

        session_factory = SessionLocal
    if session_factory is None:
        print("No DB engine; set DATABASE_URL.", file=sys.stderr)
        return None
    return session_factory()


def _cmd_apply(args, session_factory) -> int:
    snapshot, manifest, parsed, code = _load(args)
    if code:
        return code
    if not _check_confirm(args, manifest):
        return EXIT_CONFIRM
    session = _open_session(session_factory)
    if session is None:
        return 1
    snapshot_name = snapshot.name
    try:
        if not args.apply:
            from sqlalchemy import text

            if _is_postgres(session):
                session.execute(text("SET TRANSACTION READ ONLY"))
            _, _, plan = _read_plan(session, parsed, manifest, snapshot_name, read_only=False)
            print(render_apply_summary(plan, "dry run (no writes)"))
            if not _has_source_ref(session):
                print(f"warning: {MIGRATION_NOTE}; --apply will refuse until it is applied", file=sys.stderr)
            if args.json:
                _write_json(Path(args.json), plan)
                print(f"wrote {args.json}")
            return 0
        if not _has_source_ref(session):
            print(f"refused: {MIGRATION_NOTE}; nothing written", file=sys.stderr)
            return EXIT_MIGRATION
        now = datetime.now(timezone.utc)
        journal = _journal_path(snapshot, "apply", now)
        try:
            result = apply_in_transaction(session, parsed, manifest, snapshot_name, now)
            _write_json(journal, _apply_journal(snapshot, manifest, args.confirm, result, now, "pending"))
        except ApplyRefused as exc:
            session.rollback()
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_CONFLICT
        except (ApplyVerificationError, OSError) as exc:
            session.rollback()
            print(f"verification or journal failure, rolled back: {exc}", file=sys.stderr)
            return EXIT_VERIFY
        except Exception:
            session.rollback()
            raise
        try:
            session.commit()
        except Exception:
            try:
                _write_json(journal, _apply_journal(snapshot, manifest, args.confirm, result, now, "rolled_back"))
            except OSError:
                pass
            raise
        _write_json(journal, _apply_journal(snapshot, manifest, args.confirm, result, now, "committed"))
        print(render_apply_summary(result["plan"], "applied"))
        print(f"table counts {result['table_counts']}")
        print(f"journal {journal}")
        if args.json:
            _write_json(Path(args.json), result["plan"])
            print(f"wrote {args.json}")
        return 0
    finally:
        session.rollback()
        session.close()


def _cmd_rollback(args, session_factory) -> int:
    snapshot, manifest, _, code = _load(args)
    if code:
        return code
    if not _check_confirm(args, manifest):
        return EXIT_CONFIRM
    session = _open_session(session_factory)
    if session is None:
        return 1
    try:
        has_ref = _has_source_ref(session)
        if not args.apply:
            from sqlalchemy import text

            if _is_postgres(session):
                session.execute(text("SET TRANSACTION READ ONLY"))
            selected = select_snapshot_rows(session, snapshot.name, has_ref)
            print("rollback dry run (no writes)")
            print(_render_selected(selected))
            if not has_ref:
                print(f"warning: {MIGRATION_NOTE}; --apply will refuse until it is applied", file=sys.stderr)
            return 0
        if not has_ref:
            print(f"refused: {MIGRATION_NOTE}; nothing written", file=sys.stderr)
            return EXIT_MIGRATION
        now = datetime.now(timezone.utc)
        journal = _journal_path(snapshot, "rollback", now)
        try:
            result = rollback_in_transaction(session, snapshot.name)
            _write_json(journal, _rollback_journal(snapshot, manifest, args.confirm, result, now, "pending"))
        except (ApplyVerificationError, OSError) as exc:
            session.rollback()
            print(f"verification or journal failure, rolled back: {exc}", file=sys.stderr)
            return EXIT_VERIFY
        except Exception:
            session.rollback()
            raise
        try:
            session.commit()
        except Exception:
            try:
                _write_json(journal, _rollback_journal(snapshot, manifest, args.confirm, result, now, "rolled_back"))
            except OSError:
                pass
            raise
        _write_json(journal, _rollback_journal(snapshot, manifest, args.confirm, result, now, "committed"))
        print("rollback applied")
        print(_render_selected(result))
        print(f"table counts {result['table_counts']}")
        print(f"journal {journal}")
        return 0
    finally:
        session.rollback()
        session.close()


def main(argv: list[str] | None = None, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    apply_p = sub.add_parser("apply")
    apply_p.add_argument("--snapshot", required=True)
    apply_p.add_argument("--json")
    apply_p.add_argument("--apply", action="store_true")
    apply_p.add_argument("--confirm")
    rb = sub.add_parser("rollback")
    rb.add_argument("--snapshot", required=True)
    rb.add_argument("--apply", action="store_true")
    rb.add_argument("--confirm")
    args = parser.parse_args(argv)
    if args.command == "apply":
        return _cmd_apply(args, session_factory)
    return _cmd_rollback(args, session_factory)


if __name__ == "__main__":
    sys.exit(main())
