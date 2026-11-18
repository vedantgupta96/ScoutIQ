"""Shared contract-decision event building and report rendering (SCO-44).

Durable home for the Basketball-Reference cache reader, decision-event construction and the
per-team salary attribution driver, used by the coverage probe and the salary loader.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from scoutiq.etl.salary_attribution import Attribution, SigningFacts, attribute_salary
from scoutiq.sources.contract_events import (
    SIGNING_KINDS,
    SalaryRow,
    SpotracContract,
    Transaction,
    entry_combines_forms,
    event_form_class,
    league_year,
    parse_bbref_salary_rows,
    parse_bbref_transactions,
    parse_draft,
    season_label,
    signing_phase,
)

BBREF_SLUG_RE = re.compile(r"^[a-z]+[0-9]{2}\.html$")
PROGRESS_EVERY = 300
PRIOR_LINK_KINDS = SIGNING_KINDS + ("draft", "claimed", "traded")


@dataclass(frozen=True)
class BbrefPage:
    slug: str
    transactions: list[Transaction]
    salary_rows: list[SalaryRow]
    fetched_on: str | None = None


@dataclass(frozen=True)
class SeasonRow:
    age: int | None
    gp: int | None
    minutes: float | None
    has_bpm: bool


@dataclass(frozen=True)
class CapRow:
    salary_cap: int | None
    max_25: int | None
    max_30: int | None
    max_35: int | None


@dataclass
class DecisionEvent:
    player_id: int
    slug: str
    signing_date: date
    kind: str
    form_class: str
    team: str | None
    prior_team: str | None
    same_team: bool
    signing_league_year: int
    signing_season: str
    phase: str
    first_paid_season: str | None
    performance_season: str
    draft_year: int | None
    draft_round: int | None
    event_key: str
    text: str
    season_other_signings: int = 0
    season_other_form_signings: int = 0
    entry_combines_forms: bool = False
    season_waivers: int = 0
    season_trades: int = 0
    season_trade_destinations: tuple[str, ...] = ()
    next_kind: str | None = None
    next_date: date | None = None
    first_paid_season_source: str | None = None
    label_ambiguous: bool = False
    per_team_salary_resolvable: bool | None = None
    contract: SpotracContract | None = None
    rfa_at_signing_known: bool = False
    fa_year_match: bool = False
    first_year_salary: int | None = None
    cap: CapRow | None = None
    first_year_pct: float | None = None
    aav_pct: float | None = None
    prior: SeasonRow | None = None
    age: int | None = None
    position: str | None = None
    structure: str = "unclassified_no_salary"
    tier: str = "unclassified"
    at_max: bool = False
    in_window: bool = False
    order: int = 0
    salary_multi_team: bool = False
    prior_terminations_by_team: int = 0
    prior_releases_team_unknown: int = 0
    prior_service_with_team: int = 0
    attribution: Attribution | None = None

    @property
    def has_terms(self) -> bool:
        return (
            self.contract is not None
            and self.contract.years is not None
            and self.contract.aav is not None
        )

    @property
    def cap_ok(self) -> bool:
        return self.cap is not None and bool(self.cap.salary_cap)

    @property
    def has_salary(self) -> bool:
        return self.first_year_salary is not None

    @property
    def has_prior_bpm(self) -> bool:
        return self.prior is not None and self.prior.has_bpm

    @property
    def prior_qualified(self) -> bool:
        p = self.prior
        return bool(p and (p.gp or 0) >= 20 and (p.minutes or 0) >= 500)

    @property
    def salary_single_decision(self) -> bool:
        return (
            not self.label_ambiguous
            and self.season_other_form_signings == 0
            and not self.entry_combines_forms
        )

    @property
    def usable(self) -> bool:
        return (
            self.salary_single_decision
            and self.has_salary
            and not self.salary_multi_team
            and self.cap_ok
            and self.has_prior_bpm
        )

def _fetched_on(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def fetched_range(pages) -> dict:
    days = [p.fetched_on for p in pages if p.fetched_on]
    return {"min": min(days) if days else None, "max": max(days) if days else None}

def load_bbref_pages(raw_dir: Path, limit_pages: int | None = None) -> list[BbrefPage]:
    bbref_files = sorted(p for p in raw_dir.glob("*.html") if BBREF_SLUG_RE.match(p.name))
    if limit_pages is not None:
        bbref_files = bbref_files[:limit_pages]
    bbref: list[BbrefPage] = []
    for i, path in enumerate(bbref_files, 1):
        html = path.read_text(encoding="utf-8", errors="replace")
        bbref.append(
            BbrefPage(
                slug=path.stem,
                transactions=parse_bbref_transactions(html),
                salary_rows=parse_bbref_salary_rows(html),
                fetched_on=_fetched_on(path),
            )
        )
        if i % PROGRESS_EVERY == 0:
            print(f"bbref {i}/{len(bbref_files)}", file=sys.stderr)
    return bbref


def _team_slug(team: str | None) -> str:
    if team is None:
        return "unknown"
    return re.sub(r"[^a-z0-9]+", "-", team.lower()).strip("-") or "unknown"


def build_events(pages: list[BbrefPage], xref: dict[str, int]) -> tuple[list[DecisionEvent], dict]:
    raw: list[DecisionEvent] = []
    for page in pages:
        pid = xref.get(page.slug)
        if pid is None:
            continue
        dated = sorted((t for t in page.transactions if t.date is not None), key=lambda t: t.date)
        draft = next((parse_draft(t.text) for t in dated if t.kind == "draft"), None)
        for i, t in enumerate(dated):
            if t.kind not in SIGNING_KINDS:
                continue
            prior_team = next(
                (
                    p.team
                    for p in reversed(dated[:i])
                    if p.kind in PRIOR_LINK_KINDS and p.team is not None
                ),
                None,
            )
            sly = league_year(t.date)
            signing_season = season_label(sly)
            raw.append(
                DecisionEvent(
                    player_id=pid,
                    slug=page.slug,
                    signing_date=t.date,
                    kind=t.kind,
                    form_class=event_form_class(t.kind),
                    team=t.team,
                    prior_team=prior_team,
                    same_team=prior_team is not None and prior_team == t.team,
                    signing_league_year=sly,
                    signing_season=signing_season,
                    phase=signing_phase(t.date),
                    season_other_signings=sum(
                        1 for j, o in enumerate(dated) if j != i and o.kind in SIGNING_KINDS and league_year(o.date) == sly
                    ),
                    season_other_form_signings=sum(
                        1
                        for j, o in enumerate(dated)
                        if j != i
                        and o.kind in SIGNING_KINDS
                        and league_year(o.date) == sly
                        and event_form_class(o.kind) not in ("standard_form", "extension")
                    ),
                    entry_combines_forms=entry_combines_forms(t.text, t.kind)
                    or (t.kind == "conversion" and signing_phase(t.date) == "in_season"),
                    season_waivers=sum(
                        1
                        for j, o in enumerate(dated)
                        if j != i and o.kind in ("waived", "released", "claimed") and league_year(o.date) == sly
                    ),
                    season_trades=sum(
                        1 for j, o in enumerate(dated) if j != i and o.kind == "traded" and league_year(o.date) == sly
                    ),
                    season_trade_destinations=tuple(
                        o.team
                        for o in dated
                        if o.kind == "traded"
                        and league_year(o.date) == sly
                        and o.date >= t.date
                        and o.team is not None
                    ),
                    prior_terminations_by_team=sum(
                        1
                        for o in dated
                        if o.kind == "waived"
                        and o.team == t.team
                        and league_year(o.date) == sly
                        and o.date < t.date
                    ),
                    prior_service_with_team=sum(
                        1
                        for o in dated
                        if t.team is not None
                        and league_year(o.date) == sly
                        and o.date < t.date
                        and (
                            (o.kind == "traded" and o.from_team == t.team)
                            or (o.kind in ("traded", "claimed") and o.team == t.team)
                        )
                    ),
                    prior_releases_team_unknown=sum(
                        1
                        for o in dated
                        if o.kind == "released" and league_year(o.date) == sly and o.date < t.date
                    ),
                    next_kind=dated[i + 1].kind if i + 1 < len(dated) else None,
                    next_date=dated[i + 1].date if i + 1 < len(dated) else None,
                    first_paid_season=None if t.kind == "extension" else signing_season,
                    performance_season=season_label(sly - 1),
                    draft_year=draft.year if draft else None,
                    draft_round=draft.round if draft else None,
                    event_key=f"{pid}:{t.date.isoformat()}:{t.kind}:{_team_slug(t.team)}",
                    text=t.text,
                )
            )
    seen: dict[str, str] = {}
    events: list[DecisionEvent] = []
    identical = variant = 0
    for ev in raw:
        if ev.event_key in seen:
            if seen[ev.event_key] == ev.text:
                identical += 1
            else:
                variant += 1
            continue
        seen[ev.event_key] = ev.text
        ev.order = len(events)
        events.append(ev)
    candidate = {
        "definition": "player_id:signing_date:kind:team",
        "n_events": len(raw),
        "n_distinct_keys": len(seen),
        "collisions": identical + variant,
        "duplicates_identical": identical,
        "duplicates_text_variant": variant,
    }
    return events, candidate


def set_in_window(events: list[DecisionEvent], window: list[str]) -> None:
    for ev in events:
        if ev.kind == "extension":
            ev.in_window = ev.signing_season in window
        else:
            ev.in_window = ev.first_paid_season in window


def team_signings(events: list[DecisionEvent]) -> Counter:
    return Counter(
        (e.player_id, e.first_paid_season, e.team)
        for e in events
        if e.kind != "extension" and e.first_paid_season is not None
    )


def attribute_events(
    events: list[DecisionEvent],
    pages_by_slug: dict[str, BbrefPage],
    season_rows_for: Callable[[DecisionEvent], Sequence[SalaryRow]] | None = None,
    adjust_facts: Callable[[DecisionEvent, SigningFacts], SigningFacts] | None = None,
) -> None:
    signings = team_signings(events)
    for ev in events:
        if ev.kind == "extension" or ev.form_class != "standard_form" or ev.first_paid_season is None:
            continue
        if season_rows_for is not None:
            rows = season_rows_for(ev)
        else:
            rows = [r for r in pages_by_slug[ev.slug].salary_rows if r.season == ev.first_paid_season]
        facts = SigningFacts(
            event_key=ev.event_key,
            team=ev.team,
            first_paid_season=ev.first_paid_season,
            entry_combines_forms=ev.entry_combines_forms,
            team_signings_in_season=signings[(ev.player_id, ev.first_paid_season, ev.team)],
            prior_terminations_by_team=ev.prior_terminations_by_team,
            prior_service_with_team=ev.prior_service_with_team,
            prior_releases_team_unknown=ev.prior_releases_team_unknown,
            in_season=ev.phase == "in_season",
        )
        if adjust_facts is not None:
            facts = adjust_facts(ev, facts)
        ev.attribution = attribute_salary(facts, rows)

def _scalar(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return "-" if v is None else str(v)


def _is_scalar(v) -> bool:
    return not isinstance(v, (dict, list))


def _grid(rows: list[list[str]], indent: str) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return [
        indent + "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths)))
        for r in rows
    ]


def _render(name: str, value, depth: int, out: list[str]) -> None:
    indent = "  " * depth
    if isinstance(value, list):
        if value and all(isinstance(r, dict) and all(_is_scalar(x) for x in r.values()) for r in value):
            cols = list(value[0])
            out.append(f"{indent}{name}")
            out.extend(_grid([cols] + [[_scalar(r.get(c)) for c in cols] for r in value], indent + "  "))
        else:
            out.append(f"{indent}{name}: {json.dumps(value, default=str)}")
        return
    if not isinstance(value, dict):
        out.append(f"{indent}{name}: {_scalar(value)}")
        return
    if value and all(_is_scalar(x) for x in value.values()):
        out.append(f"{indent}{name}")
        out.extend(_grid([[str(k), _scalar(v)] for k, v in value.items()], indent + "  "))
        return
    if value and all(isinstance(x, dict) and all(_is_scalar(y) for y in x.values()) for x in value.values()):
        cols: list[str] = []
        for x in value.values():
            cols.extend(c for c in x if c not in cols)
        out.append(f"{indent}{name}")
        out.extend(
            _grid(
                [[""] + cols] + [[str(k)] + [_scalar(x.get(c)) for c in cols] for k, x in value.items()],
                indent + "  ",
            )
        )
        return
    out.append(f"{indent}{name}")
    for k, v in value.items():
        _render(str(k), v, depth + 1, out)


def render_report(report: dict) -> str:
    out: list[str] = []
    for name, value in report.items():
        out.append("")
        out.append(f"== {name} ==")
        if isinstance(value, dict):
            for k, v in value.items():
                _render(str(k), v, 0, out)
        else:
            _render(name, value, 0, out)
    return "\n".join(out).lstrip("\n") + "\n"
