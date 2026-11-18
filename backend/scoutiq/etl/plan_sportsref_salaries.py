"""Dry-run planner for the Sports Reference salary-schedule export. There is no apply path.

Usage:
    python -m scoutiq.etl.plan_sportsref_salaries snapshot --input PATH [--snapshot-root DIR]
    python -m scoutiq.etl.plan_sportsref_salaries plan --snapshot DIR [--json PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scoutiq.api.financial_status import contract_coverage
from scoutiq.config import settings
from scoutiq.sources.bbref import normalize_name
from scoutiq.sources.nba import TEAM_ABBREV_ALIASES
from scoutiq.sources.sportsref_salary_export import (
    LEGEND_EVIDENCE,
    ExportFormatError,
    ParsedExport,
    parse_export,
)

PARSER_MODULE = "scoutiq.sources.sportsref_salary_export"
CLAIMED_SOURCE = "Sports Reference (Basketball-Reference) player contracts table export"
SOURCE_PAGE = "https://www.basketball-reference.com/contracts/players.html"
SLUG_CONFLICT_NOTE = (
    "a verified crosswalk row maps this player to a different BBRef id; one of them may be wrong "
    "- resolve before any apply; not assigned"
)
EXPORT_TIME_NOTE = "Unknown: the export carries no timestamp, and file-system times are not source times."


@dataclass
class StoredContract:
    source: str
    scraped_at: str | None
    season_start: str
    years: list[tuple[str, int | None, bool, bool]]


@dataclass
class NameCandidate:
    player_id: int
    full_name: str
    current_team_id: int | None
    xref_status: str | None
    xref_slug: str | None


@dataclass
class DbState:
    verified_xref: dict[str, list[int]] = field(default_factory=dict)
    other_xref: dict[str, str] = field(default_factory=dict)
    players: dict[int, tuple[str, int | None]] = field(default_factory=dict)
    team_by_abbr: dict[str, int] = field(default_factory=dict)
    abbr_by_team: dict[int, str] = field(default_factory=dict)
    contracts: dict[int, StoredContract] = field(default_factory=dict)
    player_salaries: list[tuple[int, str, int | None]] = field(default_factory=list)
    team_salaries: list[tuple[int, str, str | None, int]] = field(default_factory=list)
    name_candidates: dict[str, list[NameCandidate]] = field(default_factory=dict)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_dir_name(digest: str) -> str:
    return f"sportsref-salaries-{digest[:12]}"


def take_snapshot(input_path: Path, snapshot_root: Path, now: datetime | None = None) -> tuple[Path, bool]:
    data = input_path.read_bytes()
    digest = sha256_bytes(data)
    target = snapshot_root / snapshot_dir_name(digest)
    if target.exists():
        manifest_path = target / "manifest.json"
        stored_path = target / "input.html"
        if not manifest_path.is_file() or not stored_path.is_file():
            raise RuntimeError(f"existing snapshot {target} is incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored_hash = sha256_bytes(stored_path.read_bytes())
        if stored_hash != manifest.get("sha256") or stored_hash != digest:
            raise RuntimeError(f"existing snapshot {target} does not match the input; refusing to overwrite")
        return target, False
    snapshot_root.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    stored = target / "input.html"
    shutil.copyfile(input_path, stored)
    os.chmod(stored, 0o444)
    received = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manifest = {
        "sha256": digest,
        "bytes": len(data),
        "original_filename": input_path.name,
        "received_at_utc": received.isoformat(),
        "claimed_source": CLAIMED_SOURCE,
        "source_page": SOURCE_PAGE,
        "export_time": None,
        "export_time_note": EXPORT_TIME_NOTE,
        "parser": PARSER_MODULE,
        "legend_evidence": LEGEND_EVIDENCE,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target, True


def load_verified_snapshot(snapshot_dir: Path) -> tuple[str, dict]:
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    data = (snapshot_dir / "input.html").read_bytes()
    if sha256_bytes(data) != manifest.get("sha256"):
        raise ValueError(f"input.html in {snapshot_dir} does not match the manifest sha256")
    return data.decode("utf-8", errors="replace"), manifest


def read_db_state(
    session, bbref_ids: set[str], seasons: list[str], export_names: dict[str, str] | None = None
) -> DbState:
    from sqlalchemy import desc, select, text

    from scoutiq.models import Contract, Player, PlayerSalary, PlayerTeamSalary, PlayerXref, Team

    session.execute(text("SET TRANSACTION READ ONLY"))
    state = DbState()
    ids = sorted(bbref_ids)
    for slug, pid, status in session.execute(
        select(PlayerXref.bbref_slug, PlayerXref.player_id, PlayerXref.status).where(
            PlayerXref.bbref_slug.in_(ids)
        )
    ):
        if status == "verified":
            state.verified_xref.setdefault(slug, []).append(pid)
        else:
            state.other_xref[slug] = status
    for slug in state.verified_xref:
        state.verified_xref[slug].sort()
    for abbr, tid in session.execute(select(Team.abbreviation, Team.team_id)):
        if abbr:
            state.team_by_abbr[abbr] = tid
            state.abbr_by_team[tid] = abbr
    pids = sorted({p for ps in state.verified_xref.values() for p in ps})
    for pid, name, team_id in session.execute(
        select(Player.player_id, Player.full_name, Player.current_team_id).where(Player.player_id.in_(pids))
    ):
        state.players[pid] = (name, team_id)
    from sqlalchemy.orm import selectinload

    for contract in session.scalars(
        select(Contract)
        .where(Contract.player_id.in_(pids))
        .options(selectinload(Contract.contract_years))
        .order_by(Contract.player_id, desc(Contract.season_start), desc(Contract.scraped_at))
    ):
        if contract.player_id in state.contracts:
            continue
        state.contracts[contract.player_id] = StoredContract(
            source=contract.source,
            scraped_at=contract.scraped_at.isoformat() if contract.scraped_at else None,
            season_start=contract.season_start,
            years=[
                (cy.season, cy.aav, bool(cy.is_player_option), bool(cy.is_team_option))
                for cy in contract.contract_years
            ],
        )
    if pids and seasons:
        for pid, season, salary in session.execute(
            select(PlayerSalary.player_id, PlayerSalary.season, PlayerSalary.salary).where(
                PlayerSalary.player_id.in_(pids), PlayerSalary.season.in_(seasons)
            )
        ):
            state.player_salaries.append((pid, season, salary))
        for pid, season, abbr, salary in session.execute(
            select(
                PlayerTeamSalary.player_id,
                PlayerTeamSalary.season,
                PlayerTeamSalary.team_abbr,
                PlayerTeamSalary.salary,
            ).where(PlayerTeamSalary.player_id.in_(pids), PlayerTeamSalary.season.in_(seasons))
        ):
            state.team_salaries.append((pid, season, abbr, salary))
    wanted = {normalize_name(n) for bid, n in (export_names or {}).items() if bid not in state.verified_xref}
    if wanted:
        for pid, name, team_id, status, slug in session.execute(
            select(Player.player_id, Player.full_name, Player.current_team_id, PlayerXref.status, PlayerXref.bbref_slug)
            .select_from(Player)
            .outerjoin(PlayerXref, PlayerXref.player_id == Player.player_id)
        ):
            norm = normalize_name(name)
            if norm in wanted:
                state.name_candidates.setdefault(norm, []).append(NameCandidate(pid, name, team_id, status, slug))
        for cands in state.name_candidates.values():
            cands.sort(key=lambda c: c.player_id)
    state.player_salaries.sort(key=lambda r: (r[0], r[1]))
    state.team_salaries.sort(key=lambda r: (r[0], r[1], r[2] or "", r[3]))
    return state


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def _stored_option(po: bool, to: bool) -> str | None:
    if po and to:
        return "both"
    if po:
        return "player_option"
    if to:
        return "team_option"
    return None


def _row_schedule(row) -> dict:
    return {
        y.season: {"amount": y.amount, "option": y.option, "blank": y.blank} for y in row.years
    }


def _compare_contract(row, stored: StoredContract, first_season: str) -> dict:
    stored_by_season = {s: (aav, po, to) for s, aav, po, to in stored.years}
    export_by_season = {y.season: y for y in row.years}
    seasons: dict[str, dict] = {}
    for season in sorted(set(stored_by_season) | set(export_by_season)):
        y = export_by_season.get(season)
        in_export = y is not None and not y.blank
        s = stored_by_season.get(season)
        if y is not None and y.uncertain:
            seasons[season] = {"outcome": "uncertain_in_export", "reason": y.uncertain}
        elif in_export and s is None:
            seasons[season] = {"outcome": "missing_in_stored", "export": y.amount, "export_option": y.option}
        elif in_export:
            aav, po, to = s
            so = _stored_option(po, to)
            if aav != y.amount:
                seasons[season] = {
                    "outcome": "amount_differs",
                    "stored": aav,
                    "export": y.amount,
                    "stored_option": so,
                    "export_option": y.option,
                }
            elif so != y.option:
                seasons[season] = {
                    "outcome": "option_differs",
                    "amount": y.amount,
                    "stored_option": so,
                    "export_option": y.option,
                }
            else:
                seasons[season] = {"outcome": "same", "amount": y.amount, "option": y.option}
        elif s is not None and season >= first_season:
            seasons[season] = {"outcome": "missing_in_export", "stored": s[0], "stored_option": _stored_option(s[1], s[2])}
    return {
        "source": stored.source,
        "scraped_at": stored.scraped_at,
        "stored_seasons": sorted(stored_by_season),
        "coverage": contract_coverage(sorted(stored_by_season), current_season=first_season),
        "seasons": seasons,
    }


def build_plan(parsed: ParsedExport, state: DbState, manifest: dict) -> dict:
    first_season = parsed.seasons[0] if parsed.seasons else ""
    rows_by_id: dict[str, list] = {}
    for row in parsed.rows:
        rows_by_id.setdefault(row.bbref_id, []).append(row)
    distinct_ids = sorted(rows_by_id)

    matched: dict[str, int] = {}
    unmatched: list[str] = []
    not_verified: dict[str, str] = {}
    ambiguous: dict[str, list[int]] = {}
    for bid in distinct_ids:
        pids = state.verified_xref.get(bid, [])
        if len(pids) == 1:
            matched[bid] = pids[0]
        elif len(pids) > 1:
            ambiguous[bid] = sorted(pids)
        elif bid in state.other_xref:
            not_verified[bid] = state.other_xref[bid]
        else:
            unmatched.append(bid)

    multi_ids = sorted(b for b, rs in rows_by_id.items() if len(rs) > 1)
    multi = [
        {
            "bbref_id": bid,
            "player_name": rows_by_id[bid][0].player_name,
            "rows": [
                {
                    "row_ordinal": r.row_ordinal,
                    "team": r.team_abbr,
                    "remaining_guaranteed": r.remaining_guaranteed,
                    "schedule": _row_schedule(r),
                }
                for r in rows_by_id[bid]
            ],
        }
        for bid in multi_ids
    ]

    unknown_teams: dict[str, int] = {}
    team_differs = []
    no_current_team = []
    for r in parsed.rows:
        resolved = TEAM_ABBREV_ALIASES.get(r.team_abbr.upper(), r.team_abbr)
        if resolved not in state.team_by_abbr:
            unknown_teams[r.team_abbr] = unknown_teams.get(r.team_abbr, 0) + 1
        pid = matched.get(r.bbref_id)
        if pid is None or pid not in state.players:
            continue
        current_id = state.players[pid][1]
        current_abbr = state.abbr_by_team.get(current_id) if current_id is not None else None
        entry = {
            "bbref_id": r.bbref_id,
            "player_id": pid,
            "row_ordinal": r.row_ordinal,
            "obligation_team_source": r.team_abbr,
            "obligation_team": resolved,
        }
        if current_abbr is None:
            no_current_team.append({**entry, "note": "player has no current roster team on file"})
        elif current_abbr != resolved:
            team_differs.append(
                {**entry, "current_team": current_abbr, "note": "obligation team differs from current roster team"}
            )
    team_differs.sort(key=lambda d: (d["bbref_id"], d["row_ordinal"]))
    no_current_team.sort(key=lambda d: (d["bbref_id"], d["row_ordinal"]))

    unmatched_evidence = []
    cand_no_xref = cand_not_found = cand_mismatch = cand_conflict = cand_other = 0
    slug_conflicts = []
    for bid in sorted(unmatched):
        name = rows_by_id[bid][0].player_name
        cands = state.name_candidates.get(normalize_name(name), [])
        for c in cands:
            if c.xref_status is None:
                cand_no_xref += 1
            elif c.xref_status == "not_found":
                cand_not_found += 1
            elif c.xref_status == "mismatch":
                cand_mismatch += 1
            elif c.xref_status == "verified":
                cand_conflict += 1
                slug_conflicts.append(
                    {
                        "bbref_id": bid,
                        "player_name": name,
                        "player_id": c.player_id,
                        "stored_verified_slug": c.xref_slug,
                    }
                )
            else:
                cand_other += 1
        has_conflict = any(c.xref_status == "verified" for c in cands)
        if has_conflict:
            category, note = "verified_slug_conflict", SLUG_CONFLICT_NOTE
        elif cands:
            category, note = "exact_name_candidates", "candidate only - not assigned"
        else:
            category, note = "no_player_record", None
        unmatched_evidence.append(
            {
                "bbref_id": bid,
                "player_name": name,
                "team": rows_by_id[bid][0].team_abbr,
                "category": category,
                "note": note,
                "candidates": [
                    {
                        "player_id": c.player_id,
                        "full_name": c.full_name,
                        "current_team": state.abbr_by_team.get(c.current_team_id) if c.current_team_id is not None else None,
                        "xref_status": c.xref_status,
                        "xref_slug": c.xref_slug,
                    }
                    for c in cands
                ],
            }
        )
    unmatched_summary = {
        "exact_name_candidates": sum(1 for e in unmatched_evidence if e["category"] == "exact_name_candidates"),
        "verified_slug_conflict": sum(1 for e in unmatched_evidence if e["category"] == "verified_slug_conflict"),
        "no_player_record": sum(1 for e in unmatched_evidence if e["category"] == "no_player_record"),
        "candidates_without_xref_row": cand_no_xref,
        "candidates_xref_not_found": cand_not_found,
        "candidates_xref_mismatch": cand_mismatch,
        "candidates_verified_slug_conflict": cand_conflict,
        "candidates_other_status": cand_other,
    }

    comparisons = []
    no_stored = []
    not_compared = []
    outcome_values: list[str] = []
    for bid in distinct_ids:
        if bid not in matched:
            continue
        pid = matched[bid]
        if len(rows_by_id[bid]) > 1:
            not_compared.append({"bbref_id": bid, "rows": len(rows_by_id[bid])})
            continue
        stored = state.contracts.get(pid)
        if stored is None:
            no_stored.append(bid)
            continue
        cmp_ = _compare_contract(rows_by_id[bid][0], stored, first_season)
        outcome_values.extend(v["outcome"] for v in cmp_["seasons"].values())
        comparisons.append(
            {"bbref_id": bid, "player_id": pid, "player_name": state.players.get(pid, (rows_by_id[bid][0].player_name,))[0], **cmp_}
        )
    comparison_summary = {
        "players_compared": len(comparisons),
        "players_without_stored_contract": len(no_stored),
        "players_with_any_difference": sum(
            1 for c in comparisons if any(v["outcome"] != "same" for v in c["seasons"].values())
        ),
        "season_outcomes": _counts(outcome_values),
        "coverage": _counts(c["coverage"] for c in comparisons),
    }

    single_pid_to_row = {matched[b]: rows_by_id[b][0] for b in distinct_ids if b in matched and len(rows_by_id[b]) == 1}
    alias = lambda abbr: TEAM_ABBREV_ALIASES.get((abbr or "").upper(), (abbr or "").upper())
    not_compared = [
        {"bbref_id": bid, "rows": len(rows_by_id[bid])} for bid in multi_ids if bid in matched
    ]

    ps_details = []
    ps_by_key = {(p, s_): sal for p, s_, sal in state.player_salaries}
    for pid, row in sorted(single_pid_to_row.items()):
        for y in row.years:
            has_stored = (pid, y.season) in ps_by_key
            stored_sal = ps_by_key.get((pid, y.season))
            base = {"player_id": pid, "bbref_id": row.bbref_id, "season": y.season}
            if y.uncertain:
                ps_details.append({**base, "outcome": "uncertain_in_export", "reason": y.uncertain})
            elif y.blank:
                if has_stored:
                    ps_details.append({**base, "outcome": "extra_in_stored", "stored": stored_sal})
            elif not has_stored:
                ps_details.append({**base, "outcome": "missing_in_stored", "export": y.amount})
            elif stored_sal != y.amount:
                ps_details.append({**base, "outcome": "amount_differs", "stored": stored_sal, "export": y.amount})
            else:
                ps_details.append({**base, "outcome": "same", "amount": y.amount})

    stored_ts: dict[tuple, list[tuple[int, int]]] = {}
    for idx, (pid, season, abbr, salary) in enumerate(state.team_salaries):
        stored_ts.setdefault((pid, season, alias(abbr)), []).append((idx, salary))
    consumed: set[int] = set()
    ts_details = []
    for pid, row in sorted(single_pid_to_row.items()):
        team = alias(row.team_abbr)
        for y in row.years:
            base = {
                "player_id": pid,
                "bbref_id": row.bbref_id,
                "season": y.season,
                "team": team,
                "team_source": row.team_abbr,
            }
            candidates = [c for c in stored_ts.get((pid, y.season, team), []) if c[0] not in consumed]
            if y.uncertain:
                ts_details.append({**base, "outcome": "uncertain_in_export", "reason": y.uncertain})
                for key, items in stored_ts.items():
                    if key[0] == pid and key[1] == y.season:
                        consumed.update(i for i, _ in items)
                continue
            if y.blank:
                continue
            exact = next((c for c in candidates if c[1] == y.amount), None)
            if exact is not None:
                consumed.add(exact[0])
                ts_details.append({**base, "outcome": "same", "amount": y.amount})
            elif candidates:
                consumed.add(candidates[0][0])
                ts_details.append({**base, "outcome": "amount_differs", "stored": candidates[0][1], "export": y.amount})
            else:
                ts_details.append({**base, "outcome": "missing_in_stored", "export": y.amount})
    single_pids = set(single_pid_to_row)
    for idx, (pid, season, abbr, salary) in enumerate(state.team_salaries):
        if pid in single_pids and idx not in consumed:
            ts_details.append(
                {
                    "player_id": pid,
                    "bbref_id": single_pid_to_row[pid].bbref_id,
                    "season": season,
                    "team": alias(abbr),
                    "team_source": abbr,
                    "outcome": "extra_in_stored",
                    "stored": salary,
                }
            )
    ts_details.sort(key=lambda d: (d["player_id"], d["season"], d["team"], d["outcome"]))

    return {
        "provenance": {
            "sha256": manifest.get("sha256"),
            "bytes": manifest.get("bytes"),
            "original_filename": manifest.get("original_filename"),
            "received_at_utc": manifest.get("received_at_utc"),
            "claimed_source": manifest.get("claimed_source"),
            "source_page": manifest.get("source_page"),
            "export_time": manifest.get("export_time"),
            "export_time_note": manifest.get("export_time_note"),
            "parser": manifest.get("parser"),
            "legend_evidence": manifest.get("legend_evidence"),
            "parser_problem_count": len(parsed.problems),
        },
        "coverage": {
            "rows": len(parsed.rows),
            "distinct_ids": len(distinct_ids),
            "distinct_teams": len({r.team_abbr for r in parsed.rows}),
            "seasons": list(parsed.seasons),
            "option_markers": _counts(y.option for r in parsed.rows for y in r.years if y.option),
            "blank_cells": sum(1 for r in parsed.rows for y in r.years if y.blank),
            "uncertain_cells": sum(1 for r in parsed.rows for y in r.years if y.uncertain),
            "explicit_zero_cells": sum(1 for r in parsed.rows for y in r.years if y.amount == 0 and not y.blank),
            "rows_with_remaining_guaranteed": sum(1 for r in parsed.rows if r.remaining_guaranteed is not None),
            "skipped_rows": parsed.skipped_rows,
        },
        "identity": {
            "matched": len(matched),
            "unmatched": sorted(unmatched),
            "unmatched_evidence_summary": unmatched_summary,
            "unmatched_evidence": unmatched_evidence,
            "verified_slug_conflicts": slug_conflicts,
            "not_verified": dict(sorted(not_verified.items())),
            "ambiguous": dict(sorted(ambiguous.items())),
        },
        "multi_obligation_players": multi,
        "team_checks": {
            "unknown_team_abbreviations": dict(sorted(unknown_teams.items())),
            "team_differs_from_current": team_differs,
            "no_current_team": no_current_team,
        },
        "stored_contract_comparison": {
            "summary": comparison_summary,
            "players_without_stored_contract": sorted(no_stored),
            "not_compared_multi_obligation": sorted(not_compared, key=lambda d: d["bbref_id"]),
            "not_compared_multi_obligation_count": len(not_compared),
            "players": comparisons,
        },
        "player_salaries_comparison": {
            "stored_rows_for_export_seasons": len(state.player_salaries),
            "summary": _counts(d["outcome"] for d in ps_details),
            "details": ps_details,
            "not_compared_multi_obligation": not_compared,
            "not_compared_multi_obligation_count": len(not_compared),
        },
        "team_salary_rows_comparison": {
            "stored_rows_for_export_seasons": len(state.team_salaries),
            "summary": _counts(d["outcome"] for d in ts_details),
            "details": ts_details,
            "not_compared_multi_obligation": not_compared,
            "not_compared_multi_obligation_count": len(not_compared),
        },
        "problems": list(parsed.problems),
    }


def _table_line(label: str, section: dict) -> str:
    outcomes = ("same", "amount_differs", "missing_in_stored", "extra_in_stored", "uncertain_in_export")
    counts = ", ".join(f"{o} {section['summary'].get(o, 0)}" for o in outcomes)
    return (
        f"{label}: stored rows {section['stored_rows_for_export_seasons']}; {counts}; "
        f"not compared (multi-obligation) {section['not_compared_multi_obligation_count']}"
    )


def render_summary(plan: dict) -> str:
    p, c, i = plan["provenance"], plan["coverage"], plan["identity"]
    s = plan["stored_contract_comparison"]["summary"]
    lines = [
        f"sha256 {p['sha256']} ({p['bytes']} bytes), received {p['received_at_utc']}, export time: {p['export_time']}",
        f"rows {c['rows']}, distinct ids {c['distinct_ids']}, teams {c['distinct_teams']}, seasons {', '.join(c['seasons'])}",
        f"option markers {c['option_markers']}, blank cells {c['blank_cells']}, explicit $0 {c['explicit_zero_cells']}, uncertain {c['uncertain_cells']}, "
        f"rows with remaining_guaranteed {c['rows_with_remaining_guaranteed']}, skipped rows {c['skipped_rows']}",
        f"identity: matched {i['matched']}, unmatched {len(i['unmatched'])}, "
        f"not_verified {len(i['not_verified'])}, ambiguous {len(i['ambiguous'])}",
        f"multi-obligation players {len(plan['multi_obligation_players'])}",
        f"unknown team abbreviations {len(plan['team_checks']['unknown_team_abbreviations'])}, "
        f"team differs from current {len(plan['team_checks']['team_differs_from_current'])}, "
        f"no current team {len(plan['team_checks']['no_current_team'])}",
        f"unmatched evidence {i['unmatched_evidence_summary']}",
        f"stored contracts: compared {s['players_compared']}, no stored contract {s['players_without_stored_contract']}, "
        f"with differences {s['players_with_any_difference']}",
        f"  coverage {s['coverage']}",
        f"  season outcomes {s['season_outcomes']}",
        _table_line("player_salaries", plan["player_salaries_comparison"]),
        _table_line("player_team_salaries", plan["team_salary_rows_comparison"]),
        f"parser problems {len(plan['problems'])}",
    ]
    lines.extend(f"  - {msg}" for msg in plan["problems"][:20])
    return "\n".join(lines)


def _cmd_snapshot(args) -> int:
    root = Path(args.snapshot_root) if args.snapshot_root else settings.DATA_DIR / "snapshots"
    try:
        target, created = take_snapshot(Path(args.input).expanduser(), root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"snapshot {'created' if created else 'unchanged (reused)'}: {target}")
    return 0


def _cmd_plan(args) -> int:
    snapshot = Path(args.snapshot)
    try:
        html, manifest = load_verified_snapshot(snapshot)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        parsed = parse_export(html)
    except ExportFormatError as exc:
        print(f"export format error: {exc}", file=sys.stderr)
        return 3
    from scoutiq.db import SessionLocal

    if SessionLocal is None:
        print("No DB engine; set DATABASE_URL.", file=sys.stderr)
        return 1
    session = SessionLocal()
    try:
        state = read_db_state(
            session,
            {r.bbref_id for r in parsed.rows},
            parsed.seasons,
            {r.bbref_id: r.player_name for r in parsed.rows},
        )
    finally:
        session.rollback()
        session.close()
    plan = build_plan(parsed, state, manifest)
    print(render_summary(plan))
    if args.json:
        Path(args.json).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--input", required=True)
    snap.add_argument("--snapshot-root")
    plan = sub.add_parser("plan")
    plan.add_argument("--snapshot", required=True)
    plan.add_argument("--json")
    args = parser.parse_args(argv)
    return _cmd_snapshot(args) if args.command == "snapshot" else _cmd_plan(args)


if __name__ == "__main__":
    sys.exit(main())
