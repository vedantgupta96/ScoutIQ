"""Reproducible read-only probe auditing historical contract-decision data coverage
(feasibility spike, SCO-20).

Joins cached Basketball-Reference transaction logs and Spotrac contract pages to the
local DB (salaries, caps, prior-season production, stored contracts) and reports, per
season and form class, how many signing decisions could be turned into a labeled
training row — and why the rest cannot. Reads only local cache files and runs SELECTs
inside a READ ONLY transaction; no network, no DB writes. `--cache-only` skips the DB.

Usage:
    python -m scoutiq.etl.check_contract_decision_coverage --cache-only
    python -m scoutiq.etl.check_contract_decision_coverage
    python -m scoutiq.etl.check_contract_decision_coverage --json --limit-pages 50
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import ceil
from pathlib import Path
from statistics import median

from scoutiq.config import settings
from scoutiq.etl.contract_decision_events import (
    PROGRESS_EVERY,
    BbrefPage,
    CapRow,
    DecisionEvent,
    SeasonRow,
    _fetched_on,
    attribute_events,
    build_events,
    fetched_range,
    load_bbref_pages,
    render_report as render_text,
    set_in_window,
    team_signings as _team_signings,
)
from scoutiq.etl.salary_attribution import ATTRIBUTED, RULE_VERSION, UNRESOLVED_REASONS
from scoutiq.model.features import primary_position
from scoutiq.sources.contract_events import (
    SEASON_OPENERS,
    SIGNING_KINDS,
    SpotracContract,
    league_year,
    normalize_person_name,
    parse_spotrac_contracts,
    parse_spotrac_player_name,
    spotrac_form_class,
)

CAPPED_EXCEPTIONS = frozenset(
    {
        "non-taxpayer-mle",
        "taxpayer-mle",
        "room-mle",
        "bi-annual",
        "second-round",
        "minimum",
        "rookie-scale",
        "hardship",
        "qualifying-offer",
        "early-bird",
        "non-bird",
    }
)
OPEN_MECHANISMS = frozenset({"cap-space", "bird", "sign-and-trade"})
STRUCTURE_TIERS = {
    "two_way": "mechanical",
    "ten_day": "mechanical",
    "exhibit": "mechanical",
    "substitution": "mechanical",
    "rookie_scale": "mechanical",
    "max": "censored",
    "near_minimum": "censored",
    "no_constraint_identified": "no_constraint_identified",
    "rookie_extension": "extension_rules",
    "veteran_extension": "extension_rules",
    "unclassified_no_salary": "unclassified",
}
AGE_BUCKETS = ("<=22", "23-25", "26-28", "29-31", "32+", "unknown")


@dataclass(frozen=True)
class SpotracPage:
    file: str
    name: str | None
    contracts: list[SpotracContract]
    paywalled: bool
    fetched_on: str | None = None


@dataclass(frozen=True)
class StoredContract:
    player_id: int
    season_start: str
    years: int
    source: str
    total_value: int | None
    team_id: int | None
    year_rows: int = 0
    has_player_option: bool = False
    has_team_option: bool = False
    has_non_guaranteed_year: bool = False


@dataclass
class ProbeInputs:
    seasons: list[str]
    bbref_pages: list[BbrefPage]
    spotrac_pages: list[SpotracPage]
    xref: dict[str, int]
    players: dict[int, tuple[str, str | None]]
    salaries: dict[tuple[int, str], int]
    caps: dict[str, CapRow]
    player_seasons: dict[tuple[int, str], SeasonRow]
    contracts: list[StoredContract]
    inventory: dict


def load_cache(
    raw_dir: Path, limit_pages: int | None = None
) -> tuple[list[BbrefPage], list[SpotracPage]]:
    spotrac_files = sorted((raw_dir / "spotrac").glob("player_*.html"))
    bbref = load_bbref_pages(raw_dir, limit_pages)
    if limit_pages is not None:
        spotrac_files = spotrac_files[:limit_pages]

    spotrac: list[SpotracPage] = []
    for i, path in enumerate(spotrac_files, 1):
        html = path.read_text(encoding="utf-8", errors="replace")
        spotrac.append(
            SpotracPage(
                file=path.name,
                name=parse_spotrac_player_name(html),
                contracts=parse_spotrac_contracts(html),
                paywalled="sign up today" in html.lower(),
                fetched_on=_fetched_on(path),
            )
        )
        if i % PROGRESS_EVERY == 0:
            print(f"spotrac {i}/{len(spotrac_files)}", file=sys.stderr)
    return bbref, spotrac


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(conn, sql: str) -> list[dict]:
    from sqlalchemy import text

    return [
        {k: _plain(v) for k, v in row._mapping.items()} for row in conn.execute(text(sql))
    ]


_INVENTORY_SQL = {
    "row_counts": """
        select 'players' as table_name, count(*) as n from players
        union all select 'player_xref', count(*) from player_xref
        union all select 'player_seasons', count(*) from player_seasons
        union all select 'player_salaries', count(*) from player_salaries
        union all select 'contracts', count(*) from contracts
        union all select 'contract_years', count(*) from contract_years
        union all select 'free_agent_rights', count(*) from free_agent_rights
        union all select 'cap_constants', count(*) from cap_constants
        order by table_name""",
    "contracts_by_source": """
        select source, count(*) as n, count(distinct player_id) as players,
               count(team_id) as with_team_id, count(total_value) as with_total_value,
               min(scraped_at) as min_scraped_at, max(scraped_at) as max_scraped_at
        from contracts group by source order by source""",
    "contracts_by_season_source": """
        select season_start, source, count(*) as n
        from contracts group by season_start, source order by season_start, source""",
    "contracts_per_player": """
        select c as contracts_per_player, count(*) as players
        from (select player_id, count(*) as c from contracts group by player_id) t
        group by c order by c""",
    "contract_years_by_season": """
        select season, count(*) as n, count(aav) as with_aav, count(cap_pct) as with_cap_pct,
               count(*) filter (where is_player_option) as player_options,
               count(*) filter (where is_team_option) as team_options,
               count(*) filter (where not is_guaranteed) as non_guaranteed
        from contract_years group by season order by season""",
    "player_salaries_by_season_source": """
        select season, source, count(*) as n, count(salary) as with_salary
        from player_salaries group by season, source order by season, source""",
    "free_agent_rights_by_season_status": """
        select entering_season, fa_status, count(*) as n
        from free_agent_rights group by entering_season, fa_status
        order by entering_season, fa_status""",
    "xref_by_status": """
        select status, count(*) as n from player_xref group by status order by status""",
}


def load_db() -> dict:
    from sqlalchemy import text

    from scoutiq.db import engine

    if engine is None:
        raise RuntimeError("DATABASE_URL is empty; use --cache-only to run without a DB.")

    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        xref = {
            r["bbref_slug"]: int(r["player_id"])
            for r in _rows(
                conn,
                "select bbref_slug, player_id from player_xref "
                "where status = 'verified' and bbref_slug is not null",
            )
        }
        players = {
            int(r["player_id"]): (r["full_name"], r["position"])
            for r in _rows(conn, "select player_id, full_name, position from players")
        }
        salaries = {
            (int(r["player_id"]), r["season"]): int(r["salary"])
            for r in _rows(
                conn,
                "select player_id, season, salary from player_salaries "
                "where salary is not null order by id",
            )
        }
        caps = {
            r["season"]: CapRow(r["salary_cap"], r["max_25"], r["max_30"], r["max_35"])
            for r in _rows(
                conn, "select season, salary_cap, max_25, max_30, max_35 from cap_constants"
            )
        }
        player_seasons = {
            (int(r["player_id"]), r["season"]): SeasonRow(
                r["age"], r["gp"], r["minutes"], bool(r["has_bpm"])
            )
            for r in _rows(
                conn,
                "select player_id, season, age, gp, minutes, "
                "jsonb_exists(advanced, 'BPM') as has_bpm from player_seasons order by id",
            )
        }
        contracts = [
            StoredContract(
                int(r["player_id"]),
                r["season_start"],
                int(r["years"]),
                r["source"],
                r["total_value"],
                r["team_id"],
                int(r["year_rows"]),
                bool(r["has_player_option"]),
                bool(r["has_team_option"]),
                bool(r["has_non_guaranteed_year"]),
            )
            for r in _rows(
                conn,
                "select c.player_id, c.season_start, c.years, c.source, c.total_value, c.team_id, "
                "count(cy.id) as year_rows, "
                "coalesce(bool_or(cy.is_player_option), false) as has_player_option, "
                "coalesce(bool_or(cy.is_team_option), false) as has_team_option, "
                "coalesce(bool_or(not cy.is_guaranteed), false) as has_non_guaranteed_year "
                "from contracts c left join contract_years cy on cy.contract_id = c.id "
                "group by c.id order by c.id",
            )
        ]
        inventory = {name: _rows(conn, sql) for name, sql in _INVENTORY_SQL.items()}
        conn.rollback()
    return {
        "xref": xref,
        "players": players,
        "salaries": salaries,
        "caps": caps,
        "player_seasons": player_seasons,
        "contracts": contracts,
        "inventory": inventory,
    }


def _by_key(counter: Counter) -> dict:
    return {str(k): counter[k] for k in sorted(counter, key=str)}


def _by_count(counter: Counter) -> dict:
    return {str(k): v for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))}


def _by_int_key(counter: Counter) -> dict:
    return {str(k): counter[k] for k in sorted(counter)}


def _is_max(salary: int, cap: CapRow, tolerance: float) -> bool:
    if cap.max_35 and salary > cap.max_35:
        return True
    return any(
        m and abs(salary - m) / m <= tolerance for m in (cap.max_25, cap.max_30, cap.max_35)
    )


def _age_bucket(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age <= 22:
        return "<=22"
    if age <= 25:
        return "23-25"
    if age <= 28:
        return "26-28"
    if age <= 31:
        return "29-31"
    return "32+"


def _bbref_cache_section(pages: list[BbrefPage]) -> dict:
    kinds: Counter = Counter()
    by_year: dict[int, Counter] = defaultdict(Counter)
    unparseable = 0
    for page in pages:
        for t in page.transactions:
            kinds[t.kind] += 1
            if t.kind in SIGNING_KINDS:
                if t.date is None:
                    unparseable += 1
                elif league_year(t.date) >= 2010:
                    by_year[league_year(t.date)][t.kind] += 1
    return {
        "pages": len(pages),
        "pages_without_transactions": sum(1 for p in pages if not p.transactions),
        "unparseable_dates": unparseable,
        "cache_fetched_range": fetched_range(pages),
        "kind_counts": _by_count(kinds),
        "signing_events_by_league_year": {
            str(y): _by_count(by_year[y]) for y in sorted(by_year)
        },
    }


def _spotrac_cache_section(pages: list[SpotracPage]) -> dict:
    contracts = [c for p in pages for c in p.contracts]
    labels = Counter(c.type_label for c in contracts)
    using = Counter(c.signed_using or "(empty)" for c in contracts)
    fa = Counter(c.fa_status or "(none)" for c in contracts)
    presence = {
        name: sum(1 for c in contracts if getattr(c, name) is not None)
        for name in ("years", "total_value", "aav", "gtd_at_sign", "total_gtd", "signed_using", "fa_year")
    }
    return {
        "pages": len(pages),
        "paywalled_pages": sum(1 for p in pages if p.paywalled),
        "cache_fetched_range": fetched_range(pages),
        "contracts_total": len(contracts),
        "contracts_with_terms": sum(1 for c in contracts if c.years is not None and c.aav is not None),
        "type_label_counts": _by_count(labels),
        "signed_using_counts": _by_count(using),
        "fa_status_counts": _by_count(fa),
        "field_presence": presence,
        "contracts_by_first_season": _by_key(Counter(c.first_season for c in contracts)),
        "contracts_per_page": _by_int_key(Counter(len(p.contracts) for p in pages)),
    }


def build_cache_only_report(bbref: list[BbrefPage], spotrac: list[SpotracPage]) -> dict:
    return {
        "sources": {
            "bbref": _bbref_cache_section(bbref),
            "spotrac": _spotrac_cache_section(spotrac),
        }
    }


def _link_spotrac(
    inputs: ProbeInputs, events: list[DecisionEvent]
) -> tuple[dict, dict[int, list[SpotracContract]], dict]:
    name_index: dict[str, set[int]] = defaultdict(set)
    for pid, (full_name, _pos) in inputs.players.items():
        if full_name:
            name_index[normalize_person_name(full_name)].add(pid)

    matched = ambiguous = unmatched = 0
    by_pid: dict[int, list[SpotracContract]] = defaultdict(list)
    for page in inputs.spotrac_pages:
        pids = name_index.get(normalize_person_name(page.name), set()) if page.name else set()
        if len(pids) == 1:
            matched += 1
            by_pid[next(iter(pids))].extend(page.contracts)
        elif len(pids) > 1:
            ambiguous += 1
        else:
            unmatched += 1
    by_pid = {pid: list(dict.fromkeys(cs)) for pid, cs in by_pid.items()}

    event_pids = {e.player_id for e in events}
    page_pids = {inputs.xref[p.slug] for p in inputs.bbref_pages if p.slug in inputs.xref}

    ev_groups: dict[tuple, list[DecisionEvent]] = defaultdict(list)
    for ev in events:
        if ev.kind != "extension" and ev.first_paid_season and ev.player_id in by_pid:
            ev_groups[(ev.player_id, ev.first_paid_season, ev.form_class)].append(ev)
    ct_groups: dict[tuple, list[SpotracContract]] = defaultdict(list)
    for pid, contracts in by_pid.items():
        if pid not in page_pids:
            continue
        for c in contracts:
            form = spotrac_form_class(c.type_label)
            if form != "extension":
                ct_groups[(pid, c.first_season, form)].append(c)
    link = {"linked": 0, "ambiguous": 0, "event_only": 0, "contract_only": 0}
    for key in sorted(set(ev_groups) | set(ct_groups)):
        evs, cts = ev_groups.get(key, []), ct_groups.get(key, [])
        if evs and cts:
            if len(evs) == 1 and len(cts) == 1:
                evs[0].contract = cts[0]
                link["linked"] += 1
            else:
                link["ambiguous"] += 1
        elif evs:
            link["event_only"] += 1
        else:
            link["contract_only"] += 1

    ext_link = {"linked": 0, "contract_unlinked": 0, "event_unlinked": 0}
    for pid in sorted(by_pid):
        pending = sorted(
            (e for e in events if e.player_id == pid and e.kind == "extension"),
            key=lambda e: (e.signing_date, e.order),
        ) if pid in event_pids else []
        exts = sorted(
            (c for c in by_pid[pid] if spotrac_form_class(c.type_label) == "extension"),
            key=lambda c: c.start_year,
        )
        for c in exts:
            cands = [
                e
                for e in pending
                if e.contract is None and c.start_year - 3 <= e.signing_league_year < c.start_year
            ]
            if cands and pid in page_pids:
                chosen = cands[-1]
                chosen.first_paid_season = c.first_season
                chosen.first_paid_season_source = "spotrac"
                chosen.contract = c
                ext_link["linked"] += 1
            elif pid in page_pids:
                ext_link["contract_unlinked"] += 1
        ext_link["event_unlinked"] += sum(1 for e in pending if e.contract is None)

    for ev in events:
        others = [c for c in by_pid.get(ev.player_id, []) if c is not ev.contract]
        ev.fa_year_match = any(
            c.fa_year == ev.signing_league_year and c.fa_status is not None for c in others
        )
        ev.rfa_at_signing_known = any(
            c.fa_status == "rfa" and c.fa_year == ev.signing_league_year for c in others
        )

    stats = {
        "matched": matched,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "link": link,
        "ext_link": ext_link,
        "events_on_players_without_spotrac_page": sum(
            1 for e in events if e.player_id not in by_pid
        ),
    }
    return stats, by_pid, {"page_pids": page_pids}


def _label_and_structure(
    inputs: ProbeInputs, events: list[DecisionEvent], min_proxy_pct: float, max_tolerance: float
) -> None:
    first_standard: dict[int, int] = {}
    for ev in sorted(events, key=lambda e: (e.signing_date, e.order)):
        if ev.form_class == "standard_form":
            first_standard.setdefault(ev.player_id, ev.order)

    for ev in events:
        pos = inputs.players.get(ev.player_id, (None, None))[1]
        ev.position = primary_position(pos)
        ev.prior = inputs.player_seasons.get((ev.player_id, ev.performance_season))
        ev.age = ev.prior.age if ev.prior else None
        if ev.first_paid_season is not None:
            ev.first_year_salary = inputs.salaries.get((ev.player_id, ev.first_paid_season))
            ev.cap = inputs.caps.get(ev.first_paid_season)
        if ev.has_salary and ev.cap_ok:
            ev.first_year_pct = ev.first_year_salary / ev.cap.salary_cap
        if ev.contract is not None and ev.contract.aav is not None and ev.cap_ok:
            ev.aav_pct = ev.contract.aav / ev.cap.salary_cap
        if ev.kind == "extension" and ev.has_salary and ev.cap is not None:
            ev.at_max = _is_max(ev.first_year_salary, ev.cap, max_tolerance)

        if ev.kind == "two_way":
            ev.structure = "two_way"
        elif ev.kind in ("ten_day", "exhibit", "substitution"):
            ev.structure = ev.kind
        elif ev.kind == "extension":
            rookie = ev.draft_round == 1 and ev.signing_league_year - (ev.draft_year or 0) == 3
            ev.structure = "rookie_extension" if rookie and ev.draft_year else "veteran_extension"
        elif (
            ev.form_class == "standard_form"
            and ev.draft_round == 1
            and ev.draft_year is not None
            and first_standard.get(ev.player_id) == ev.order
            and ev.signing_league_year - ev.draft_year <= 3
        ):
            ev.structure = "rookie_scale"
        elif ev.form_class == "standard_form" and ev.has_salary and ev.cap_ok:
            if _is_max(ev.first_year_salary, ev.cap, max_tolerance):
                ev.structure = "max"
            elif ev.first_year_pct <= min_proxy_pct:
                ev.structure = "near_minimum"
            else:
                ev.structure = "no_constraint_identified"
        else:
            ev.structure = "unclassified_no_salary"
        ev.tier = STRUCTURE_TIERS[ev.structure]


def _funnel_counts(evs: list[DecisionEvent]) -> dict:
    usable = [e for e in evs if e.usable]
    unconstrained = [e for e in usable if e.structure == "no_constraint_identified"]
    exact = [e for e in usable if e.contract is not None and e.has_terms]
    return {
        "events": len(evs),
        "unambiguous": sum(1 for e in evs if not e.label_ambiguous),
        "no_other_form_signing": sum(
            1 for e in evs if e.season_other_form_signings == 0 and not e.entry_combines_forms
        ),
        "has_salary": sum(1 for e in evs if e.has_salary),
        "salary_single_team": sum(1 for e in evs if e.has_salary and not e.salary_multi_team),
        "salary_multi_team": sum(1 for e in evs if e.salary_multi_team),
        "has_cap": sum(1 for e in evs if e.cap_ok),
        "has_prior_row": sum(1 for e in evs if e.prior is not None),
        "has_prior_bpm": sum(1 for e in evs if e.has_prior_bpm),
        "prior_qualified": sum(1 for e in evs if e.prior_qualified),
        "usable": len(usable),
        "usable_unconstrained": len(unconstrained),
        "usable_unconstrained_offseason": sum(1 for e in unconstrained if e.phase == "offseason"),
        "usable_with_exact_terms": len(exact),
        "usable_unconstrained_with_exact_terms": sum(
            1 for e in exact if e.structure == "no_constraint_identified"
        ),
    }


def _extension_counts(evs: list[DecisionEvent]) -> dict:
    usable = [
        e
        for e in evs
        if e.first_paid_season is not None
        and e.has_salary
        and not e.salary_multi_team
        and e.cap_ok
        and e.has_prior_bpm
    ]
    return {
        "events": len(evs),
        "first_paid_season_resolved": sum(1 for e in evs if e.first_paid_season is not None),
        "has_salary": sum(1 for e in evs if e.has_salary),
        "salary_multi_team": sum(1 for e in evs if e.salary_multi_team),
        "has_cap": sum(1 for e in evs if e.first_paid_season is not None and e.cap_ok),
        "has_prior_bpm": sum(1 for e in evs if e.has_prior_bpm),
        "usable": len(usable),
        "usable_with_exact_terms": sum(1 for e in usable if e.contract is not None and e.has_terms),
        "rookie_extension": sum(1 for e in evs if e.structure == "rookie_extension"),
        "veteran_extension": sum(1 for e in evs if e.structure == "veteran_extension"),
        "at_max": sum(1 for e in evs if e.at_max),
    }


def _breakdowns(evs: list[DecisionEvent]) -> dict:
    return {
        "n": len(evs),
        "age_bucket": {b: sum(1 for e in evs if _age_bucket(e.age) == b) for b in AGE_BUCKETS},
        "position": _by_key(Counter(e.position or "unknown" for e in evs)),
        "kind": _by_key(Counter(e.kind for e in evs)),
        "phase": _by_key(Counter(e.phase for e in evs)),
    }


def _present_counts(
    evs: list[DecisionEvent], stored_options: dict[tuple[int, str], list[StoredContract]]
) -> dict:
    def sp(getter):
        return sum(1 for e in evs if e.contract is not None and getter(e.contract) is not None)

    def stored(e: DecisionEvent) -> list[StoredContract]:
        if e.first_paid_season is None:
            return []
        return stored_options.get((e.player_id, e.first_paid_season), [])

    def split(e: DecisionEvent) -> tuple[int, int] | None:
        c = e.contract
        if c is None or c.gtd_at_sign is None or c.total_value is None:
            return None
        return c.gtd_at_sign, c.total_value

    known = [x for x in map(split, evs) if x is not None]

    return {
        "n": len(evs),
        "signing_date": len(evs),
        "signing_team": sum(1 for e in evs if e.team is not None),
        "prior_team": sum(1 for e in evs if e.prior_team is not None),
        "transaction_type": len(evs),
        "first_paid_season": sum(1 for e in evs if e.first_paid_season is not None),
        "first_year_salary": sum(1 for e in evs if e.has_salary),
        "cap_denominator": sum(1 for e in evs if e.cap_ok),
        "first_year_pct": sum(1 for e in evs if e.first_year_pct is not None),
        "years": sp(lambda c: c.years),
        "total_value": sp(lambda c: c.total_value),
        "aav": sp(lambda c: c.aav),
        "aav_pct": sum(1 for e in evs if e.aav_pct is not None),
        "gtd_at_sign": sp(lambda c: c.gtd_at_sign),
        "signed_using": sp(lambda c: c.signed_using),
        "option_years_stored": sum(1 for e in evs if stored(e)),
        "stored_with_player_option": sum(
            1 for e in evs if any(c.has_player_option for c in stored(e))
        ),
        "stored_with_team_option": sum(1 for e in evs if any(c.has_team_option for c in stored(e))),
        "stored_with_non_guaranteed_year": sum(
            1 for e in evs if any(c.has_non_guaranteed_year for c in stored(e))
        ),
        "guarantee_split_known": len(known),
        "fully_guaranteed_at_sign": sum(1 for g, t in known if g >= t),
        "partially_guaranteed_at_sign": sum(1 for g, t in known if 0 < g < t),
        "non_guaranteed_at_sign": sum(1 for g, t in known if g == 0),
        "rfa_status_known": sum(1 for e in evs if e.fa_year_match),
        "rfa_at_signing_known": sum(1 for e in evs if e.rfa_at_signing_known),
        "age": sum(1 for e in evs if e.age is not None),
        "position": sum(1 for e in evs if e.position is not None),
        "prior_production_row": sum(1 for e in evs if e.prior is not None),
        "prior_bpm": sum(1 for e in evs if e.has_prior_bpm),
    }


def _table(rule: list[bool], proxy: list[bool]) -> dict:
    pairs = list(zip(rule, proxy))
    return {
        "tp": sum(1 for r, p in pairs if r and p),
        "fp": sum(1 for r, p in pairs if r and not p),
        "fn": sum(1 for r, p in pairs if not r and p),
        "tn": sum(1 for r, p in pairs if not r and not p),
    }


def _waived_before_opener(ev: DecisionEvent) -> bool:
    if ev.next_kind not in ("waived", "released") or ev.next_date is None:
        return False
    opener = SEASON_OPENERS.get(ev.signing_season)
    if opener is not None:
        return ev.next_date <= opener
    return ev.next_date - ev.signing_date <= timedelta(days=45)


def _missing_reasons(
    inputs: ProbeInputs, std: list[DecisionEvent], page_by_slug: dict[str, BbrefPage]
) -> dict:
    no_salary = [e for e in std if not e.has_salary]
    salary_reasons: Counter = Counter({"waived_before_opener": 0, "no_salary_rows_on_page": 0, "other": 0})
    for e in no_salary:
        if _waived_before_opener(e):
            salary_reasons["waived_before_opener"] += 1
        elif not page_by_slug[e.slug].salary_rows:
            salary_reasons["no_salary_rows_on_page"] += 1
        else:
            salary_reasons["other"] += 1

    seasons_by_pid: dict[int, set[int]] = defaultdict(set)
    for pid, season in inputs.player_seasons:
        seasons_by_pid[pid].add(int(season[:4]))
    first_year = int(inputs.seasons[0][:4])
    no_prior = [e for e in std if e.prior is None]
    prior_reasons: Counter = Counter(
        {"before_data_window": 0, "no_earlier_nba_season": 0, "gap_before_signing": 0}
    )
    for e in no_prior:
        perf_year = int(e.performance_season[:4])
        if perf_year < first_year:
            prior_reasons["before_data_window"] += 1
        elif not any(y < perf_year for y in seasons_by_pid.get(e.player_id, ())):
            prior_reasons["no_earlier_nba_season"] += 1
        else:
            prior_reasons["gap_before_signing"] += 1

    camp = [e for e in std if _waived_before_opener(e)]
    return {
        "first_year_salary": {"n": len(no_salary), **_by_key(salary_reasons)},
        "prior_production": {"n": len(no_prior), **_by_key(prior_reasons)},
        "camp_deals_suspected": len(camp),
        "camp_deals_suspected_by_season": _by_key(Counter(e.first_paid_season for e in camp)),
        "camp_deals_suspected_usable": sum(1 for e in camp if e.usable),
    }


def _multi_team_salary(inputs: ProbeInputs) -> dict:
    out = {
        "db_equals_sum": 0,
        "db_equals_max_row": 0,
        "db_equals_other_row": 0,
        "db_matches_none": 0,
        "db_missing": 0,
        "player_seasons_with_multiple_team_rows": 0,
    }
    for page in inputs.bbref_pages:
        pid = inputs.xref.get(page.slug)
        if pid is None:
            continue
        by_season: dict[str, list[int]] = defaultdict(list)
        for r in page.salary_rows:
            by_season[r.season].append(r.salary)
        for season, vals in by_season.items():
            if len(vals) < 2:
                continue
            out["player_seasons_with_multiple_team_rows"] += 1
            db = inputs.salaries.get((pid, season))
            if db is None:
                out["db_missing"] += 1
            elif db == sum(vals):
                out["db_equals_sum"] += 1
            elif db == max(vals):
                out["db_equals_max_row"] += 1
            elif db in vals:
                out["db_equals_other_row"] += 1
            else:
                out["db_matches_none"] += 1
    return out


def _is_attributed(e: DecisionEvent) -> bool:
    return e.attribution is not None and e.attribution.status == ATTRIBUTED


def _reason_counts(evs: list[DecisionEvent]) -> dict:
    counts = Counter(e.attribution.reason for e in evs if e.attribution is not None and not _is_attributed(e))
    return {r: counts[r] for r in UNRESOLVED_REASONS}


def _v1_label_effect(inputs: ProbeInputs) -> dict:
    stored_differs = 0
    seasons = 0
    gaps: list[float] = []
    for page in inputs.bbref_pages:
        pid = inputs.xref.get(page.slug)
        if pid is None:
            continue
        by_season: dict[str, list[int]] = defaultdict(list)
        for r in page.salary_rows:
            by_season[r.season].append(r.salary)
        for season, vals in by_season.items():
            stored = inputs.salaries.get((pid, season))
            if len(vals) < 2 or stored is None:
                continue
            seasons += 1
            if stored != sum(vals):
                stored_differs += 1
            cap = inputs.caps.get(season)
            if cap is not None and cap.salary_cap:
                gaps.append((sum(vals) - stored) / cap.salary_cap * 100)
    ordered = sorted(gaps)
    return {
        "player_seasons": seasons,
        "stored_differs_from_row_sum": stored_differs,
        "gap_pct_of_cap": {
            "n": len(ordered),
            "median": round(median(ordered), 2) if ordered else None,
            "p90": round(ordered[ceil(0.9 * len(ordered)) - 1], 2) if ordered else None,
            "over_1_point": sum(1 for g in ordered if g > 1.0),
        },
        "note": "row sum is shown only to size the gap; it is not a valid season label when rows mix contracts",
    }


def _attribution_section(
    inputs: ProbeInputs, std: list[DecisionEvent], otherwise_usable: list[DecisionEvent]
) -> dict:
    attributed = [e for e in std if _is_attributed(e)]
    ambiguous = [e for e in std if e.label_ambiguous]
    multi = [e for e in std if e.salary_multi_team]
    other_form = [e for e in std if e.season_other_form_signings > 0 or e.entry_combines_forms]
    usable = [e for e in std if e.usable]
    usable_not_attributed = [e for e in usable if not _is_attributed(e)]
    with_attribution = [e for e in attributed if e.cap_ok and e.has_prior_bpm]
    return {
        "rule_version": RULE_VERSION,
        "events": len(std),
        "attributed": len(attributed),
        "unresolved": len(std) - len(attributed),
        "unresolved_by_reason": _reason_counts(std),
        "ambiguous_signings": {
            "events": len(ambiguous),
            "attributed": sum(1 for e in ambiguous if _is_attributed(e)),
            "previously_reported_resolvable": sum(1 for e in ambiguous if e.per_team_salary_resolvable),
        },
        "multi_team_salary": {
            "events": len(multi),
            "attributed": sum(1 for e in multi if _is_attributed(e)),
            "otherwise_usable": len(otherwise_usable),
            "otherwise_usable_attributed": sum(1 for e in otherwise_usable if _is_attributed(e)),
        },
        "other_form_excluded": {
            "events": len(other_form),
            "attributed": sum(1 for e in other_form if _is_attributed(e)),
        },
        "usable_today": len(usable),
        "usable_with_attribution": len(with_attribution),
        "newly_usable": sum(1 for e in with_attribution if not e.usable),
        "usable_today_not_attributed": len(usable_not_attributed),
        "usable_today_not_attributed_by_reason": _reason_counts(usable_not_attributed),
        "usable_and_attributed_salary_differs": sum(
            1 for e in usable if _is_attributed(e) and e.attribution.salary != e.first_year_salary
        ),
        "in_season_attributed": sum(1 for e in attributed if e.phase == "in_season"),
        "v1_label_effect": _v1_label_effect(inputs),
    }


def build_report(
    inputs: ProbeInputs, *, min_proxy_pct: float = 0.025, max_tolerance: float = 0.015
) -> dict:
    window = inputs.seasons[1:]
    events, candidate = build_events(inputs.bbref_pages, inputs.xref)
    raw_events = candidate["n_events"]
    duplicates = raw_events - len(events)

    set_in_window(events, window)

    groups: dict[tuple, list[DecisionEvent]] = defaultdict(list)
    for ev in events:
        if ev.in_window and ev.kind != "extension" and ev.form_class == "standard_form":
            groups[(ev.player_id, ev.first_paid_season)].append(ev)
    page_by_slug = {p.slug: p for p in inputs.bbref_pages}
    ambiguous_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    team_signings = _team_signings(events)
    attribute_events(events, page_by_slug)
    for evs in ambiguous_groups.values():
        for ev in evs:
            ev.label_ambiguous = True
            rows = page_by_slug[ev.slug].salary_rows
            ev.per_team_salary_resolvable = (
                ev.team is not None
                and sum(1 for r in rows if r.season == ev.first_paid_season and r.team == ev.team) == 1
                and team_signings[(ev.player_id, ev.first_paid_season, ev.team)] == 1
                and not ev.entry_combines_forms
            )

    multi_team = {
        (inputs.xref[p.slug], season)
        for p in inputs.bbref_pages
        if p.slug in inputs.xref
        for season, n in Counter(r.season for r in p.salary_rows).items()
        if n >= 2
    }
    link_stats, by_pid, aux = _link_spotrac(inputs, events)
    page_pids = aux["page_pids"]
    for ev in events:
        ev.salary_multi_team = (
            ev.first_paid_season is not None and (ev.player_id, ev.first_paid_season) in multi_team
        )
    _label_and_structure(inputs, events, min_proxy_pct, max_tolerance)

    std = [e for e in events if e.in_window and e.kind != "extension" and e.form_class == "standard_form"]
    ext = [e for e in events if e.in_window and e.kind == "extension"]
    other_forms = [e for e in events if e.in_window and e.kind != "extension" and e.form_class != "standard_form"]
    all_window = [e for e in events if e.in_window]
    usable_std = [e for e in std if e.usable]
    usable_unconstrained = [e for e in usable_std if e.structure == "no_constraint_identified"]

    kinds_all: Counter = Counter()
    signing_on_unmatched = unparseable = 0
    for page in inputs.bbref_pages:
        for t in page.transactions:
            kinds_all[t.kind] += 1
            if t.kind in SIGNING_KINDS:
                if t.date is None:
                    unparseable += 1
                if page.slug not in inputs.xref:
                    signing_on_unmatched += 1
    cache_bbref = _bbref_cache_section(inputs.bbref_pages)
    bbref_section = {
        "pages": len(inputs.bbref_pages),
        "pages_without_transactions": cache_bbref["pages_without_transactions"],
        "pages_without_verified_xref": sum(
            1 for p in inputs.bbref_pages if p.slug not in inputs.xref
        ),
        "signing_events_on_unmatched_pages": signing_on_unmatched,
        "unparseable_dates": unparseable,
        "duplicates_collapsed": duplicates,
        "cache_fetched_range": cache_bbref["cache_fetched_range"],
        "kind_counts": cache_bbref["kind_counts"],
        "signing_events_by_league_year": cache_bbref["signing_events_by_league_year"],
        "multi_team_salary": _multi_team_salary(inputs),
    }
    spotrac_section = _spotrac_cache_section(inputs.spotrac_pages)
    spotrac_section.update(
        {
            "pages_matched": link_stats["matched"],
            "pages_unmatched": link_stats["unmatched"],
            "pages_ambiguous": link_stats["ambiguous"],
        }
    )

    by_season = []
    for s in window:
        row = {"season": s}
        row.update(_funnel_counts([e for e in std if e.first_paid_season == s]))
        by_season.append(row)
    funnel_total = _funnel_counts(std)

    other_rows = []
    for s in window + [None]:
        sub = [e for e in other_forms if s is None or e.first_paid_season == s]
        row = {"season": s or "total"}
        for form in ("two_way", "short_form"):
            fe = [e for e in sub if e.form_class == form]
            row[f"{form}_events"] = len(fe)
            row[f"{form}_has_salary"] = sum(1 for e in fe if e.has_salary)
        other_rows.append(row)

    ext_rows = []
    for s in window:
        row = {"season": s}
        row.update(_extension_counts([e for e in ext if e.signing_season == s]))
        ext_rows.append(row)
    gaps = Counter(
        int(e.first_paid_season[:4]) - e.signing_league_year
        for e in ext
        if e.first_paid_season is not None
    )

    stored_options: dict[tuple[int, str], list[StoredContract]] = defaultdict(list)
    for c in inputs.contracts:
        if c.source == "spotrac" and c.year_rows > 0:
            stored_options[(c.player_id, c.season_start)].append(c)

    def tiers(evs):
        return {
            "structure": _by_key(Counter(e.structure for e in evs)),
            "tier": _by_key(Counter(e.tier for e in evs)),
        }

    structure_by_season = {
        s: _by_key(Counter(e.structure for e in usable_std if e.first_paid_season == s))
        for s in window
    }

    linked_std = [
        e for e in events if e.contract is not None and e.form_class == "standard_form"
        and e.kind != "extension" and e.has_salary
    ]
    proxy = {
        "near_minimum_vs_signed_using_minimum": _table(
            [e.structure == "near_minimum" for e in linked_std],
            [e.contract.signed_using == "minimum" for e in linked_std],
        ),
        "rookie_scale_vs_spotrac": _table(
            [e.structure == "rookie_scale" for e in linked_std],
            [e.contract.signed_using == "rookie-scale" for e in linked_std],
        ),
        "max_vs_spotrac": _table(
            [e.structure == "max" for e in linked_std],
            ["maximum" in e.contract.type_label for e in linked_std],
        ),
    }

    by_pid_std: dict[int, set[str]] = defaultdict(set)
    by_pid_short: dict[int, set[str]] = defaultdict(set)
    ext_years: dict[int, list[int]] = defaultdict(list)
    for e in events:
        if e.kind == "extension":
            ext_years[e.player_id].append(e.signing_league_year)
        elif e.form_class == "standard_form":
            by_pid_std[e.player_id].add(e.first_paid_season)
        else:
            by_pid_short[e.player_id].add(e.first_paid_season)
    audit_cats = (
        "standard_signing_same_season",
        "extension_signed_earlier",
        "two_way_or_short_form_same_season",
        "no_event_found",
        "no_bbref_page",
    )
    audit_total: Counter = Counter({c: 0 for c in audit_cats})
    audit_by_season: dict[str, Counter] = defaultdict(lambda: Counter({c: 0 for c in audit_cats}))
    for c in inputs.contracts:
        start = int(c.season_start[:4])
        if c.season_start in by_pid_std.get(c.player_id, ()):
            cat = "standard_signing_same_season"
        elif any(start - 3 <= y < start for y in ext_years.get(c.player_id, ())):
            cat = "extension_signed_earlier"
        elif c.season_start in by_pid_short.get(c.player_id, ()):
            cat = "two_way_or_short_form_same_season"
        elif c.player_id in page_pids:
            cat = "no_event_found"
        else:
            cat = "no_bbref_page"
        audit_total[cat] += 1
        audit_by_season[c.season_start][cat] += 1
    stored_starts = {(c.player_id, c.season_start) for c in inputs.contracts}
    without_stored = []
    for s in window:
        sub = [e for e in std if e.first_paid_season == s]
        without_stored.append(
            {
                "season": s,
                "standard_form_events": len(sub),
                "without_stored_contract": sum(
                    1 for e in sub if (e.player_id, s) not in stored_starts
                ),
            }
        )

    otherwise_usable = [
        e
        for e in std
        if e.salary_multi_team
        and not e.label_ambiguous
        and e.has_salary
        and e.cap_ok
        and e.has_prior_bpm
    ]
    other_form = [e for e in std if e.season_other_form_signings > 0 or e.entry_combines_forms]
    other_form_otherwise_usable = [
        e
        for e in other_form
        if not e.label_ambiguous
        and e.has_salary
        and not e.salary_multi_team
        and e.cap_ok
        and e.has_prior_bpm
    ]
    combined_entry = [e for e in std if e.entry_combines_forms]
    combined_entry_otherwise_usable = [
        e
        for e in combined_entry
        if e.season_other_form_signings == 0
        and not e.label_ambiguous
        and e.has_salary
        and not e.salary_multi_team
        and e.cap_ok
        and e.has_prior_bpm
    ]
    by_cause = {
        "other_signing_same_season": 0,
        "waiver_or_release_same_season": 0,
        "trade_only": 0,
        "unexplained": 0,
    }
    trade_only: list[DecisionEvent] = []
    for e in otherwise_usable:
        if e.season_other_signings > 0 or e.entry_combines_forms:
            by_cause["other_signing_same_season"] += 1
        elif e.season_waivers > 0:
            by_cause["waiver_or_release_same_season"] += 1
        elif e.season_trades > 0:
            by_cause["trade_only"] += 1
            trade_only.append(e)
        else:
            by_cause["unexplained"] += 1
    row_sum_recoverable = 0
    for e in trade_only:
        row_teams = {r.team for r in page_by_slug[e.slug].salary_rows if r.season == e.first_paid_season}
        if e.team is not None and row_teams <= {e.team, *e.season_trade_destinations}:
            row_sum_recoverable += 1
    unconstrained_linked = [e for e in usable_unconstrained if e.contract is not None]
    using = Counter(e.contract.signed_using or "(empty)" for e in unconstrained_linked)
    evidence = {
        "n": len(usable_unconstrained),
        "with_spotrac_link": len(unconstrained_linked),
        "signed_using_counts": _by_count(using),
        "signed_using_capped": sum(
            1 for e in unconstrained_linked if e.contract.signed_using in CAPPED_EXCEPTIONS
        ),
        "signed_using_open": sum(
            1 for e in unconstrained_linked if e.contract.signed_using in OPEN_MECHANISMS
        ),
        "signed_using_unknown": sum(
            1
            for e in unconstrained_linked
            if e.contract.signed_using not in CAPPED_EXCEPTIONS | OPEN_MECHANISMS
        ),
        "rfa_at_signing_known": sum(1 for e in usable_unconstrained if e.rfa_at_signing_known),
        "fa_status_known": sum(1 for e in usable_unconstrained if e.fa_year_match),
    }

    return {
        "meta": {
            "seasons": {"first": inputs.seasons[0], "last": inputs.seasons[-1], "n": len(inputs.seasons)},
            "min_proxy_pct": min_proxy_pct,
            "max_tolerance": max_tolerance,
            "definitions": {
                "league_year": "calendar year of the most recent league-year rollover on or before the date; rollover is July 1 except 2020-10-12 and 2021-07-21 (COVID-shifted)",
                "first_paid_season": "season label of the league year of signing; extensions resolve only via a linked Spotrac extension contract",
                "performance_season": "last completed season as of the signing date (league_year - 1)",
                "phase": "offseason = signed before that season's opening night (SEASON_OPENERS); in_season otherwise; Jul-Sep fallback when the opener is unknown",
                "usable": "one standard signing in the player-season, no other signing of any form (two-way, 10-day, Exhibit, substitution) by the player in that league year, whether as a separate transaction row or described within the same entry (for example two 10-day contracts then a rest-of-season contract, or an in-season two-way conversion), because the stored season salary would combine the deals, stored first-year salary from a single-team season, cap present, prior-season BPM present",
                "per_team_resolvable": "an ambiguous signing has one salary row for the signing team in that season and no other signing of any form with that team in that season, and the signing's own entry does not combine forms",
                "guarantees": "option flags come from stored contract_years (current deals only); contract_years.is_guaranteed is derived as 'not an option year' by the loader and is NOT a guarantee measure; partial guarantees are measured only at contract level from Spotrac guarantee-at-signing vs total value",
                "multi_team_recoverable": "an otherwise-usable multi-team signing counts as recoverable by summing per-team salary rows only when the season's extra rows are explained by trades alone: no other signing of any form, whether a separate transaction row or a deal of another form described within the signing's own entry, and no waiver, release or waiver claim, in that league year; every per-team salary row that season must also belong to the signing team or a team the player was traded to after the signing in that league year, since a row from any other team is pay from a different contract",
                "tiers": "mechanical (rule-set pay), censored (max/near-minimum), extension_rules (negotiated but bounded by extension eligibility, length, raise and maximum rules), no_constraint_identified (no rule fired; NOT affirmatively market-set — RFA and exception status are mostly unknown), unclassified",
                "spotrac_link_units": "link counts are per (player, first season, form class) group; event_only/contract_only are limited to players with a verified BBRef page and a matched Spotrac page",
            },
        },
        "inventory": inputs.inventory,
        "sources": {"bbref": bbref_section, "spotrac": spotrac_section},
        "funnel_standard_form": {"by_season": by_season, "total": funnel_total},
        "funnel_other_forms": other_rows,
        "extensions": {
            "by_signing_season": ext_rows,
            "total": _extension_counts(ext),
            "gap_seasons_distribution": _by_int_key(gaps),
        },
        "structure": {
            "all_in_window": tiers(all_window),
            "usable_standard_form": tiers(usable_std),
            "by_season_usable_standard_form": structure_by_season,
        },
        "breakdowns": {
            "usable_standard_form": _breakdowns(usable_std),
            "usable_unconstrained": _breakdowns(usable_unconstrained),
        },
        "field_missingness": {
            "standard_form": _present_counts(std, stored_options),
            "extension": _present_counts(ext, stored_options),
        },
        "missing_reasons": _missing_reasons(inputs, std, page_by_slug),
        "dedup": {
            "duplicates_collapsed": duplicates,
            "ambiguous_events": sum(len(v) for v in ambiguous_groups.values()),
            "multi_team_salary_events": sum(1 for e in std if e.salary_multi_team),
            "multi_team_salary_events_otherwise_usable": len(otherwise_usable),
            "multi_team_salary_otherwise_usable_by_cause": by_cause,
            "multi_team_salary_recoverable_by_row_sum": row_sum_recoverable,
            "multi_team_salary_trade_only_unrelated_team_row": len(trade_only) - row_sum_recoverable,
            "other_form_signing_events": len(other_form),
            "other_form_signing_events_otherwise_usable": len(other_form_otherwise_usable),
            "combined_entry_events": len(combined_entry),
            "combined_entry_events_by_kind": {
                k: sum(1 for e in combined_entry if e.kind == k)
                for k in ("rest_of_season", "conversion", "standard")
            },
            "combined_entry_events_otherwise_usable": len(combined_entry_otherwise_usable),
            "ambiguous_player_seasons": len(ambiguous_groups),
            "ambiguous_resolvable_by_per_team_salary": sum(
                1 for v in ambiguous_groups.values() for e in v if e.per_team_salary_resolvable
            ),
            "spotrac_link_non_extension": link_stats["link"],
            "spotrac_link_extension": link_stats["ext_link"],
            "events_on_players_without_spotrac_page": link_stats["events_on_players_without_spotrac_page"],
        },
        "proxy_validation": proxy,
        "constraint_evidence": evidence,
        "stored_contract_audit": {
            "total": _by_key(audit_total),
            "by_season_start": {s: _by_key(audit_by_season[s]) for s in sorted(audit_by_season)},
            "events_without_stored_contract": without_stored,
        },
        "candidate_key": candidate,
        "per_team_attribution": _attribution_section(inputs, std, otherwise_usable),
    }


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="check_contract_decision_coverage",
        description="Read-only audit of historical contract-decision data coverage (SCO-20).",
    )
    ap.add_argument("--raw-dir", type=Path, default=None, help="cache dir (default settings.RAW_DIR)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--cache-only", action="store_true", help="skip the DB; sources section only")
    ap.add_argument("--limit-pages", type=int, default=None, help="parse only the first N pages per source")
    ap.add_argument("--min-proxy-pct", type=float, default=0.025)
    ap.add_argument("--max-tolerance", type=float, default=0.015)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    raw_dir = args.raw_dir if args.raw_dir is not None else settings.RAW_DIR
    bbref, spotrac = load_cache(raw_dir, args.limit_pages)
    if not bbref:
        print(f"No Basketball-Reference pages found in {raw_dir}.", file=sys.stderr)
        return 1
    if args.cache_only:
        report = build_cache_only_report(bbref, spotrac)
    else:
        db = load_db()
        inputs = ProbeInputs(
            seasons=settings.seasons, bbref_pages=bbref, spotrac_pages=spotrac, **db
        )
        report = build_report(
            inputs, min_proxy_pct=args.min_proxy_pct, max_tolerance=args.max_tolerance
        )
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
