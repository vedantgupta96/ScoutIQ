"""Load per-team BBRef salary rows and the contract-decision salary attributions (SCO-44).

Source salary rows are insert-only evidence: a stored row is never updated or deleted, and a
stored row whose salary differs from the source is reported as a conflict, never overwritten.
`player_salaries` is not touched.
Stored attribution records take part in attribution the same way: a stored signing the cache no longer
produces still counts toward the signing team's signings, and stored evidence counts are only ever
raised, so evidence of ambiguity is never lost across runs. Default is a read-only dry run; `--apply` writes in one
transaction and refuses when the tables are missing or any conflict exists.

Usage:
    python -m scoutiq.etl.load_team_salaries
    python -m scoutiq.etl.load_team_salaries --json --limit-pages 50
    python -m scoutiq.etl.load_team_salaries --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path

from scoutiq.config import settings
from scoutiq.etl.contract_decision_events import (
    BbrefPage,
    attribute_events,
    build_events,
    fetched_range,
    load_bbref_pages,
    render_report,
    set_in_window,
)
from scoutiq.etl.salary_attribution import ATTRIBUTED, RULE_VERSION, UNRESOLVED_REASONS, SigningFacts
from scoutiq.sources.contract_events import SalaryRow
from scoutiq.sources.nba import team_id_for_abbreviation

SOURCE = "bbref"
CONFLICT_TEXT_CAP = 50

TeamSalaryKey = tuple[int, str, str, str, int]
SeasonEvidence = dict[tuple[int, str], list[tuple[TeamSalaryKey, SalaryRow]]]


@dataclass
class TeamSalaryPlan:
    source_pages: int = 0
    source_rows: int = 0
    fetched_on: dict = field(default_factory=lambda: {"min": None, "max": None})
    skipped_unverified_pages: int = 0
    skipped_unverified_rows: int = 0
    planned_rows: int = 0
    unmapped_team_rows: int = 0
    empty_team_name_rows: int = 0
    to_insert: list[dict] = field(default_factory=list)
    unchanged: list[TeamSalaryKey] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    stored_not_in_source: list[TeamSalaryKey] = field(default_factory=list)


@dataclass
class AttributionPlan:
    to_insert: list[dict] = field(default_factory=list)
    to_update: list[dict] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)


@dataclass
class DbState:
    xref: dict[str, int]
    tables_present: bool
    team_salaries: dict[TeamSalaryKey, tuple[int, str | None, int]]
    attributions: dict[str, dict]


@dataclass
class LoadPlan:
    team_salaries: TeamSalaryPlan
    attributions: AttributionPlan
    tables_present: bool
    attribution_events: int
    attributions_by_status: dict
    unresolved_by_reason: dict
    stored_team_salary_count: int
    stored_attribution_count: int
    events_with_stored_only_evidence: int = 0
    events_with_stored_signing_evidence: int = 0
    promotions: int = 0


def _keyed_page_rows(page: BbrefPage, pid: int) -> list[tuple[TeamSalaryKey, SalaryRow]]:
    ordinals: Counter = Counter()
    keyed: list[tuple[TeamSalaryKey, SalaryRow]] = []
    for row in page.salary_rows:
        ordinal = ordinals[(row.season, row.team)]
        ordinals[(row.season, row.team)] += 1
        keyed.append(((pid, row.season, SOURCE, row.team, ordinal), row))
    return keyed


def plan_team_salary_rows(
    pages: list[BbrefPage],
    xref: dict[str, int],
    existing: dict[TeamSalaryKey, tuple[int, str | None, int]],
    team_id_for: Callable[[str | None], int | None],
) -> TeamSalaryPlan:
    plan = TeamSalaryPlan(source_pages=len(pages), fetched_on=fetched_range(pages))
    seen: set[TeamSalaryKey] = set()
    for page in pages:
        plan.source_rows += len(page.salary_rows)
        pid = xref.get(page.slug)
        if pid is None:
            plan.skipped_unverified_pages += 1
            plan.skipped_unverified_rows += len(page.salary_rows)
            continue
        fetched_on = date.fromisoformat(page.fetched_on) if page.fetched_on else None
        for key, row in _keyed_page_rows(page, pid):
            ordinal = key[4]
            seen.add(key)
            team_id = team_id_for(row.team_abbr)
            plan.planned_rows += 1
            if team_id is None:
                plan.unmapped_team_rows += 1
            if not row.team:
                plan.empty_team_name_rows += 1
            stored = existing.get(key)
            if stored is None:
                plan.to_insert.append(
                    {
                        "player_id": pid,
                        "season": row.season,
                        "team_name": row.team,
                        "team_abbr": row.team_abbr,
                        "team_id": team_id,
                        "row_ordinal": ordinal,
                        "salary": row.salary,
                        "source": SOURCE,
                        "source_ref": page.slug,
                        "source_fetched_on": fetched_on,
                    }
                )
            elif stored[0] != row.salary:
                plan.conflicts.append(
                    {
                        "player_id": pid,
                        "season": row.season,
                        "team_name": row.team,
                        "row_ordinal": ordinal,
                        "stored_salary": stored[0],
                        "source_salary": row.salary,
                        "stored_id": stored[2],
                        "source_ref": page.slug,
                    }
                )
            else:
                plan.unchanged.append(key)
    plan.stored_not_in_source = sorted(k for k in existing if k not in seen)
    return plan


def reconcile_season_evidence(
    pages: list[BbrefPage],
    xref: dict[str, int],
    stored: dict[TeamSalaryKey, tuple[int, str | None, int]],
    stored_not_in_source: list[TeamSalaryKey],
) -> SeasonEvidence:
    evidence: SeasonEvidence = {}
    for page in pages:
        pid = xref.get(page.slug)
        if pid is None:
            continue
        for key, row in _keyed_page_rows(page, pid):
            evidence.setdefault((key[0], key[1]), []).append((key, row))
    for key in sorted(stored_not_in_source):
        salary, team_abbr, _id = stored[key]
        evidence.setdefault((key[0], key[1]), []).append((key, SalaryRow(key[1], key[3], salary, team_abbr)))
    return evidence


def attributed_row_keys(events: list, evidence: SeasonEvidence) -> dict[str, TeamSalaryKey]:
    keys: dict[str, TeamSalaryKey] = {}
    for ev in events:
        att = ev.attribution
        if att is not None and att.status == ATTRIBUTED:
            keys[ev.event_key] = evidence[(ev.player_id, ev.first_paid_season)][att.row_index][0]
    return keys


def plan_attributions(
    events: list,
    existing: dict[str, dict],
    fetched_on_by_slug: dict[str, str | None] | None = None,
    row_keys: dict[str, TeamSalaryKey] | None = None,
) -> AttributionPlan:
    fetched = fetched_on_by_slug or {}
    keys = row_keys or {}
    plan = AttributionPlan()
    produced: set[str] = set()
    for ev in events:
        att = ev.attribution
        if att is None:
            continue
        produced.add(ev.event_key)
        row_key = keys.get(ev.event_key)
        item = {
            "event_key": ev.event_key,
            "player_id": ev.player_id,
            "signing_date": ev.signing_date,
            "kind": ev.kind,
            "team_name": ev.team,
            "first_paid_season": ev.first_paid_season,
            "status": att.status,
            "reason": att.reason,
            "salary": att.salary,
            "rule_version": RULE_VERSION,
            "evidence": att.evidence,
            "source": SOURCE,
            "source_ref": ev.slug,
            "source_fetched_on": date.fromisoformat(fetched[ev.slug]) if fetched.get(ev.slug) else None,
            "row_key": row_key,
        }
        stored = existing.get(ev.event_key)
        if stored is None:
            plan.to_insert.append(item)
        elif (
            stored["status"],
            stored["reason"],
            stored["salary"],
            stored["rule_version"],
            stored["row_key"],
        ) == (att.status, att.reason, att.salary, RULE_VERSION, row_key):
            plan.unchanged.append(ev.event_key)
        else:
            plan.to_update.append(item)
    plan.orphaned = sorted(k for k in existing if k not in produced)
    return plan


def _evidence_dict(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def read_db_state(conn) -> DbState:
    from sqlalchemy import inspect, text

    xref = {
        r.bbref_slug: int(r.player_id)
        for r in conn.execute(
            text(
                "select bbref_slug, player_id from player_xref "
                "where status = 'verified' and bbref_slug is not null"
            )
        )
    }
    inspector = inspect(conn)
    present = inspector.has_table("player_team_salaries") and inspector.has_table(
        "salary_decision_attributions"
    )
    if not present:
        return DbState(xref, False, {}, {})
    team_salaries = {
        (int(r.player_id), r.season, r.source, r.team_name, int(r.row_ordinal)): (
            int(r.salary),
            r.team_abbr,
            int(r.id),
        )
        for r in conn.execute(
            text(
                "select id, player_id, season, source, team_name, row_ordinal, salary, team_abbr "
                "from player_team_salaries where source = :source"
            ),
            {"source": SOURCE},
        )
    }
    attributions = {
        r.event_key: {
            "status": r.status,
            "reason": r.reason,
            "salary": None if r.salary is None else int(r.salary),
            "rule_version": r.rule_version,
            "player_id": int(r.player_id),
            "first_paid_season": r.first_paid_season,
            "team_name": r.team_name,
            "evidence": _evidence_dict(r.evidence),
            "row_key": None
            if r.ts_id is None
            else (int(r.ts_player_id), r.ts_season, r.ts_source, r.ts_team_name, int(r.ts_row_ordinal)),
        }
        for r in conn.execute(
            text(
                "select a.event_key, a.status, a.reason, a.salary, a.rule_version, "
                "a.player_id, a.first_paid_season, a.team_name, a.evidence, "
                "s.id as ts_id, s.player_id as ts_player_id, s.season as ts_season, "
                "s.source as ts_source, s.team_name as ts_team_name, s.row_ordinal as ts_row_ordinal "
                "from salary_decision_attributions a "
                "left join player_team_salaries s on s.id = a.team_salary_id"
            )
        )
    }
    return DbState(xref, True, team_salaries, attributions)


def default_db_reader() -> DbState:
    from sqlalchemy import text

    from scoutiq.db import engine

    if engine is None:
        raise RuntimeError("DATABASE_URL is empty; the loader needs the DB to plan.")
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        state = read_db_state(conn)
        conn.rollback()
    return state


def build_plan(
    raw_dir: Path,
    limit_pages: int | None,
    db_reader: Callable[[], DbState],
    pages: list[BbrefPage] | None = None,
) -> LoadPlan:
    if pages is None:
        pages = load_bbref_pages(raw_dir, limit_pages)
    state = db_reader()
    team_salary_plan = plan_team_salary_rows(
        pages, state.xref, state.team_salaries, team_id_for_abbreviation
    )
    evidence = reconcile_season_evidence(
        pages, state.xref, state.team_salaries, team_salary_plan.stored_not_in_source
    )
    stored_only = {(k[0], k[1]) for k in team_salary_plan.stored_not_in_source}
    events, _candidate = build_events(pages, state.xref)
    set_in_window(events, settings.seasons[1:])
    produced = {
        e.event_key
        for e in events
        if e.in_window and e.kind != "extension" and e.form_class == "standard_form" and e.first_paid_season is not None
    }
    orphan_signings = Counter(
        (a.get("player_id"), a.get("first_paid_season"), a.get("team_name"))
        for key, a in state.attributions.items()
        if key not in produced
    )
    adjusted: set[str] = set()

    def adjust(ev, facts: SigningFacts) -> SigningFacts:
        counts = {
            "team_signings_in_season": facts.team_signings_in_season
            + orphan_signings[(ev.player_id, ev.first_paid_season, ev.team)],
            "prior_terminations_by_team": facts.prior_terminations_by_team,
            "prior_service_with_team": facts.prior_service_with_team,
            "prior_releases_team_unknown": facts.prior_releases_team_unknown,
        }
        stored = state.attributions.get(ev.event_key)
        if stored is not None:
            stored_evidence = stored.get("evidence") or {}
            counts = {k: max(v, int(stored_evidence.get(k) or 0)) for k, v in counts.items()}
        adjusted_facts = replace(facts, **counts)
        if adjusted_facts != facts:
            adjusted.add(ev.event_key)
        return adjusted_facts

    attribute_events(
        events,
        {p.slug: p for p in pages},
        lambda ev: [row for _key, row in evidence.get((ev.player_id, ev.first_paid_season), [])],
        adjust,
    )
    scoped = [e for e in events if e.in_window and e.attribution is not None]
    attribution_plan = plan_attributions(
        scoped,
        state.attributions,
        {p.slug: p.fetched_on for p in pages},
        attributed_row_keys(scoped, evidence),
    )
    promotions = sum(
        1
        for item in attribution_plan.to_update
        if state.attributions[item["event_key"]]["status"] == "unresolved" and item["status"] == ATTRIBUTED
    )
    by_status = Counter(e.attribution.status for e in scoped)
    by_reason = Counter(e.attribution.reason for e in scoped if e.attribution.status != ATTRIBUTED)
    return LoadPlan(
        team_salaries=team_salary_plan,
        attributions=attribution_plan,
        tables_present=state.tables_present,
        attribution_events=len(scoped),
        attributions_by_status={s: by_status[s] for s in (ATTRIBUTED, "unresolved")},
        unresolved_by_reason={r: by_reason[r] for r in UNRESOLVED_REASONS},
        stored_team_salary_count=len(state.team_salaries),
        stored_attribution_count=len(state.attributions),
        events_with_stored_only_evidence=sum(
            1 for e in scoped if (e.player_id, e.first_paid_season) in stored_only
        ),
        events_with_stored_signing_evidence=len(adjusted),
        promotions=promotions,
    )


def plan_report(plan: LoadPlan, mode: str) -> dict:
    ts, at = plan.team_salaries, plan.attributions
    return {
        "mode": mode,
        "tables_present": plan.tables_present,
        "source": {
            "pages": ts.source_pages,
            "rows": ts.source_rows,
            "fetched_on": ts.fetched_on,
            "skipped_unverified_pages": ts.skipped_unverified_pages,
            "skipped_unverified_rows": ts.skipped_unverified_rows,
            "planned_rows": ts.planned_rows,
        },
        "team_salary_rows": {
            "to_insert": len(ts.to_insert),
            "unchanged": len(ts.unchanged),
            "conflicts": len(ts.conflicts),
            "stored_not_in_source": len(ts.stored_not_in_source),
            "unmapped_team_rows": ts.unmapped_team_rows,
            "empty_team_name_rows": ts.empty_team_name_rows,
        },
        "attributions": {
            "rule_version": RULE_VERSION,
            "events": plan.attribution_events,
            "by_status": plan.attributions_by_status,
            "unresolved_by_reason": plan.unresolved_by_reason,
            "to_insert": len(at.to_insert),
            "to_update": len(at.to_update),
            "unchanged": len(at.unchanged),
            "orphaned": len(at.orphaned),
            "events_with_stored_only_evidence": plan.events_with_stored_only_evidence,
            "events_with_stored_signing_evidence": plan.events_with_stored_signing_evidence,
            "promotions": plan.promotions,
        },
        "conflicts": ts.conflicts,
    }


class ApplyRefused(RuntimeError):
    pass


def check_applicable(plan: LoadPlan) -> None:
    if not plan.tables_present:
        raise ApplyRefused("player_team_salaries / salary_decision_attributions do not exist; run alembic upgrade head")
    if plan.team_salaries.conflicts:
        raise ApplyRefused(f"{len(plan.team_salaries.conflicts)} stored salary rows conflict with the source")


def apply_plan(session, plan: LoadPlan, now: datetime) -> dict:
    from sqlalchemy import insert, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from scoutiq.models import PlayerTeamSalary, SalaryDecisionAttribution

    check_applicable(plan)

    if plan.team_salaries.to_insert:
        session.execute(
            insert(PlayerTeamSalary), [{**r, "loaded_at": now} for r in plan.team_salaries.to_insert]
        )
        session.flush()

    ids = {
        (r.player_id, r.season, r.source, r.team_name, r.row_ordinal): r.id
        for r in session.execute(
            select(
                PlayerTeamSalary.id,
                PlayerTeamSalary.player_id,
                PlayerTeamSalary.season,
                PlayerTeamSalary.source,
                PlayerTeamSalary.team_name,
                PlayerTeamSalary.row_ordinal,
            ).where(PlayerTeamSalary.source == SOURCE)
        )
    }
    rows = []
    for item in plan.attributions.to_insert + plan.attributions.to_update:
        row = {k: v for k, v in item.items() if k != "row_key"}
        row["team_salary_id"] = None
        if item["row_key"] is not None:
            row["team_salary_id"] = ids.get(item["row_key"])
            if row["team_salary_id"] is None:
                raise ApplyRefused(f"no stored salary row for attribution {item['event_key']}")
        row["computed_at"] = now
        rows.append(row)
    if rows:
        stmt = pg_insert(SalaryDecisionAttribution)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["event_key"],
                set_={
                    c: stmt.excluded[c]
                    for c in rows[0]
                    if c != "event_key"
                },
            ),
            rows,
        )
    return {
        "player_team_salaries": {
            "before": plan.stored_team_salary_count,
            "after": plan.stored_team_salary_count + len(plan.team_salaries.to_insert),
        },
        "salary_decision_attributions": {
            "before": plan.stored_attribution_count,
            "after": plan.stored_attribution_count + len(plan.attributions.to_insert),
        },
    }


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="load_team_salaries",
        description="Load per-team BBRef salary rows and decision salary attributions (SCO-44).",
    )
    ap.add_argument("--raw-dir", type=Path, default=None, help="cache dir (default settings.RAW_DIR)")
    ap.add_argument("--limit-pages", type=int, default=None, help="parse only the first N pages")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--apply", action="store_true", help="write the plan (default is a read-only dry run)")
    return ap


def _print_report(report: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return
    shown = dict(report)
    conflicts = shown.pop("conflicts")
    if len(conflicts) > CONFLICT_TEXT_CAP:
        shown["conflicts_shown"] = f"first {CONFLICT_TEXT_CAP} of {len(conflicts)}"
    shown["conflicts"] = conflicts[:CONFLICT_TEXT_CAP]
    print(render_report(shown))


def main(argv: list[str] | None = None, db_reader: Callable[[], DbState] | None = None) -> int:
    args = _parser().parse_args(argv)
    raw_dir = args.raw_dir if args.raw_dir is not None else settings.RAW_DIR
    pages = load_bbref_pages(raw_dir, args.limit_pages)
    if not pages:
        print(f"No Basketball-Reference pages found in {raw_dir}.", file=sys.stderr)
        return 1
    plan = build_plan(raw_dir, args.limit_pages, db_reader or default_db_reader, pages=pages)
    if not args.apply:
        _print_report(plan_report(plan, "dry_run"), args.json)
        return 0
    try:
        check_applicable(plan)
        from scoutiq.db import get_session

        now = datetime.now(tz=timezone.utc)
        with get_session() as session:
            counts = apply_plan(session, plan, now)
    except ApplyRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    _print_report({**plan_report(plan, "applied"), "counts": counts}, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
