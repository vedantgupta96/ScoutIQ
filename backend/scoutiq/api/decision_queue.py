"""Team Decision Queue — composes existing extension, option, cap-tier, and roster-need
logic into one prioritized, read-only list of a team's highest-leverage contract, cap, and
roster questions. Deep module: DB orchestration only (contract load, extension/option
verdicts, cap tier, roster fit) so it stays unit-testable without a live DB or model
artifact — the one exception is reusing free_agency's pool-assembly helpers for option
discovery (see below), a plain function import rather than a route dependency.

Only the current season (LATEST_SEASON) is supported: every item here composes today's
contracts, rosters, valuations, and roster-fit, so `season` must be omitted or equal to
LATEST_SEASON. Anything else raises ValueError (the router maps that to 422) rather than
silently serving a historical snapshot — as-of-season composition is not implemented.

An `option` item is only emitted when the player is actually in the current entering-season
Free Agency options pool (reusing free_agency._assemble_pool / _resolve_entering), so its
`/free-agency?tab=options` destination always contains the player — a final contract year
several seasons out with an option flag is not "pending" yet and produces no item at all.

Extension items come from one batched `batch_extension_summaries` call for the whole roster
(one contracts query, one contract-years query, one valuation batch) rather than a per-player
decide_extension fan-out, so an N-player roster doesn't pay N separate contract/valuation
round trips. `team_cap_hits` is likewise computed once and shared by the cap_tier and expiring
builders. The shared batched state is threaded through the per-player item builders as one
`_QueueContext` rather than as separate positional args.

Ordering (deterministic, covered by tests):
  1. Priority band: high > medium > low.
  2. Within a band, item type rank — option < extension < expiring < cap_tier < roster_need —
     so option/extension decisions always outrank generic watch items in the same band.
  3. abs(gap_pct) descending; items with no gap_pct sort after those with one.
  4. player_id ascending; team-level items (player_id is None) sort after player items.
  5. id ascending, as a final deterministic tiebreaker.

No composite "front-office score" is computed anywhere — every item's band is explained by
its own `priority_reason`, and every item links to an existing non-trade ScoutIQ surface.
Trade Lab is out of scope for this module and is never imported here.

Per ADR-0001, a missing model value degrades an item's verdict, not the item's existence:
option and cap_tier facts are contractual and always appear; an eligible extension without a
model value appears as a low-priority contract fact rather than dropping, and
`DecisionQueue.model_unavailable` flags the run when the valuation model artifact itself was
unavailable for the whole batch.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, select

from scoutiq.api import free_agency as fa
from scoutiq.api.cap import (
    TIER_BELOW_TAX,
    TIER_FIRST_APRON,
    TIER_SECOND_APRON,
    TIER_TAXPAYER,
    SeasonCapData,
    cap_for,
    classify_tier,
    load_season_caps,
    room_to_lines,
)
from scoutiq.api.extension import ExtensionSummary, batch_extension_summaries, extension_verdict
from scoutiq.api.roster_fit import load_fit_context
from scoutiq.api.rosters import team_cap_hits
from scoutiq.api.routers import free_agency as fa_router
from scoutiq.api.season import LATEST_SEASON
from scoutiq.api.valuation import value_players
from scoutiq.model.roster_fit import profile_roster
from scoutiq.models import Contract, ContractYear, Player, Team

TYPE_OPTION = "option"
TYPE_EXTENSION = "extension"
TYPE_EXPIRING = "expiring"
TYPE_CAP_TIER = "cap_tier"
TYPE_ROSTER_NEED = "roster_need"

_TYPE_RANK = {
    TYPE_OPTION: 0,
    TYPE_EXTENSION: 1,
    TYPE_EXPIRING: 2,
    TYPE_CAP_TIER: 3,
    TYPE_ROSTER_NEED: 4,
}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

QUEUE_CAVEAT = (
    "Composes the extension, option, cap-tier, and roster-need logic already surfaced "
    "elsewhere in ScoutIQ into one read-only prioritization view. There is no mutation, "
    "assignment, completion state, or composite score — every item's band is explained by "
    "its own priority_reason, and links go to the existing ScoutIQ surface for that decision. "
    f"Only available for the current season ({LATEST_SEASON}); as-of-season composition is "
    "not implemented."
)

MODEL_UNAVAILABLE_CAVEAT = (
    " The valuation model artifact is unavailable this run; extension items for eligible "
    "players are shown as contract facts only, without a model-driven priority."
)

NO_MODEL_VALUE_CAUTION = "Model value unavailable — shown as a contract fact only."


@dataclass
class QueueItem:
    id: str
    type: str
    priority: str
    priority_reason: str
    title: str
    detail: str
    player_id: int | None
    team_id: int
    value_pct: float | None
    pay_pct: float | None
    gap_pct: float | None
    value_usd: int | None
    pay_usd: int | None
    destination: str
    season: str
    as_of: str
    caution: str | None = None


@dataclass
class DecisionQueue:
    team_id: int
    team_name: str | None
    season: str
    generated_from: str
    items: list[QueueItem]
    caveat: str
    model_unavailable: bool = False


def _gap_key(gap_pct: float | None) -> tuple[int, float]:
    if gap_pct is None:
        return (1, 0.0)
    return (0, -abs(gap_pct))


def _player_key(player_id: int | None) -> tuple[int, int]:
    if player_id is None:
        return (1, 0)
    return (0, player_id)


def _sort_key(item: QueueItem):
    return (
        _PRIORITY_RANK[item.priority],
        _TYPE_RANK[item.type],
        _gap_key(item.gap_pct),
        _player_key(item.player_id),
        item.id,
    )


# --------------------------------------------------------------------------- queue context
@dataclass
class _QueueContext:
    """Shared batched state for one build_decision_queue call, threaded through the
    per-player item builders instead of a long positional-argument list."""
    season: str
    caps: dict[str, SeasonCapData]
    salary_cap: int | None
    tax_line: int | None
    first_apron: int | None
    second_apron: int | None
    contracts_by_player: dict[int, Contract]
    years_by_contract: dict[int, list[ContractYear]]
    value_pct_by_player: dict[int, float]
    option_pool_entering_by_player: dict[int, str]
    cap_hits: dict[int, int]
    extension_summaries: dict[int, ExtensionSummary]


# --------------------------------------------------------------------------- contract lookups
def _latest_contracts_for(db, player_ids: list[int]) -> dict[int, Contract]:
    """One contract per player_id, batched for the whole roster in a single query."""
    if not player_ids:
        return {}
    contracts = db.scalars(
        select(Contract)
        .where(Contract.player_id.in_(player_ids))
        .distinct(Contract.player_id)
        .order_by(Contract.player_id, desc(Contract.season_start), desc(Contract.scraped_at))
    ).all()
    return {c.player_id: c for c in contracts}


def _contract_years_for(db, contract_ids: list[int]) -> dict[int, list[ContractYear]]:
    """Contract years for a batch of contract ids, grouped and ordered ascending by season."""
    if not contract_ids:
        return {}
    years = db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id.in_(contract_ids))
        .order_by(ContractYear.contract_id, ContractYear.season)
    ).all()
    by_contract: dict[int, list[ContractYear]] = {}
    for cy in years:
        by_contract.setdefault(cy.contract_id, []).append(cy)
    return by_contract


def _year_cap_pct(year: ContractYear, caps: dict[str, SeasonCapData]) -> float | None:
    """A contract year's cap hit as % of cap: the stored fraction, else AAV / that season's cap."""
    if year.cap_pct is not None:
        return round(float(year.cap_pct) * 100, 2)
    season_cap = cap_for(year.season, caps)
    if year.aav and season_cap:
        return round(year.aav / season_cap.salary_cap * 100, 2)
    return None


def _current_option_pool_entering(db) -> dict[int, str]:
    """Player id -> entering_season for players in the Free Agency options pool for the
    season entering next — the same pool assembly `/free-agency?tab=options` renders, reused
    so a queue option item never links to a board that doesn't list the player."""
    entering = fa_router._resolve_entering(None)
    pool = fa_router._assemble_pool(db, entering, type_filter=None, position=None)
    return {
        entry.player.player_id: entry.entering_season
        for entry in pool
        if entry.fa_type in (fa.FA_PLAYER_OPTION, fa.FA_TEAM_OPTION)
    }


# --------------------------------------------------------------------------- option / expiring
def _option_item(
    player: Player,
    team_id: int,
    final_year: ContractYear,
    entering_season: str,
    ctx: _QueueContext,
    value_pct: float | None,
) -> QueueItem:
    fa_type = fa.free_agent_type(final_year.is_player_option, final_year.is_team_option)
    option_cap_pct = _year_cap_pct(final_year, ctx.caps)
    verdict = None
    if option_cap_pct is not None:
        verdict = fa.option_decision(value_pct, option_cap_pct, fa_type)

    if verdict is not None:
        title = f"{player.full_name}: {verdict.verdict}"
        detail = verdict.rationale
        caution = None if verdict.value_pct is not None else "No model value available; decision fact only."
        value_pct_out = verdict.value_pct
        pay_pct_out = verdict.option_cap_pct
        gap_pct = verdict.gap_pct
    else:
        readable_type = fa_type.replace("-", " ")
        title = f"{player.full_name}: option decision pending"
        detail = f"{player.full_name}'s {final_year.season} year is a {readable_type}; its salary could not be sized as % of cap."
        caution = f"No cap data available for {final_year.season} to size this option."
        value_pct_out = None
        pay_pct_out = None
        gap_pct = None

    return QueueItem(
        id=f"option:{team_id}:{player.player_id}:{ctx.season}",
        type=TYPE_OPTION,
        priority="high",
        priority_reason=f"An option decision is pending for the {entering_season} offseason.",
        title=title,
        detail=detail,
        player_id=player.player_id,
        team_id=team_id,
        value_pct=value_pct_out,
        pay_pct=pay_pct_out,
        gap_pct=gap_pct,
        value_usd=None,
        pay_usd=final_year.aav,
        destination="/free-agency?tab=options",
        season=ctx.season,
        as_of=final_year.season,
        caution=caution,
    )


def _expiring_item(
    player: Player,
    team_id: int,
    final_year: ContractYear,
    ctx: _QueueContext,
) -> QueueItem:
    season = ctx.season
    if final_year.cap_pct is not None:
        pay_pct = round(float(final_year.cap_pct) * 100, 2)
    else:
        season_cap = cap_for(season, ctx.caps)
        salary_cap = season_cap.salary_cap if season_cap else None
        cap_hit = ctx.cap_hits.get(player.player_id)
        pay_pct = round(cap_hit / salary_cap * 100, 2) if (cap_hit and salary_cap) else None
    reason = f"Final guaranteed year is {season}; reaches free agency after it."
    return QueueItem(
        id=f"expiring:{team_id}:{player.player_id}:{season}",
        type=TYPE_EXPIRING,
        priority="medium",
        priority_reason=reason,
        title=f"{player.full_name}: contract expiring",
        detail=f"{player.full_name}'s {reason[0].lower()}{reason[1:]}",
        player_id=player.player_id,
        team_id=team_id,
        value_pct=None,
        pay_pct=pay_pct,
        gap_pct=None,
        value_usd=None,
        pay_usd=final_year.aav,
        destination="/free-agency",
        season=season,
        as_of=season,
        caution=None,
    )


def _option_or_expiring_item(player: Player, team_id: int, ctx: _QueueContext) -> QueueItem | None:
    contract = ctx.contracts_by_player.get(player.player_id)
    if contract is None:
        return None
    years = ctx.years_by_contract.get(contract.id, [])
    if not years:
        return None

    final_year = years[-1]  # ordered ascending by season -> last row is the max season
    if final_year.season < ctx.season:
        return None

    entering_season = ctx.option_pool_entering_by_player.get(player.player_id)
    if entering_season is not None:
        return _option_item(
            player, team_id, final_year, entering_season, ctx, ctx.value_pct_by_player.get(player.player_id)
        )
    if final_year.season == ctx.season:
        return _expiring_item(player, team_id, final_year, ctx)
    return None


# --------------------------------------------------------------------------- extension
_EXTENSION_PRIORITY = {
    "Extend now": "high",
    "Fair — extend at market or wait": "medium",
    "Extend at market": "medium",
    "Don't extend": "low",
}


def _extension_item(player: Player, team_id: int, ctx: _QueueContext) -> QueueItem | None:
    summary = ctx.extension_summaries.get(player.player_id)
    if summary is None or not summary.eligible:
        return None

    if summary.has_model_value:
        verdict, _tone, rationale, gap_pct = extension_verdict(summary.value_pct, summary.current_pay_pct)
        return QueueItem(
            id=f"extension:{team_id}:{player.player_id}:{ctx.season}",
            type=TYPE_EXTENSION,
            priority=_EXTENSION_PRIORITY.get(verdict, "low"),
            priority_reason=rationale,
            title=f"{player.full_name}: {verdict}",
            detail=rationale,
            player_id=player.player_id,
            team_id=team_id,
            value_pct=summary.value_pct,
            pay_pct=summary.current_pay_pct,
            gap_pct=gap_pct,
            value_usd=None,
            pay_usd=None,
            destination=f"/players/{player.player_id}",
            season=ctx.season,
            as_of=ctx.season,
            caution=None,
        )

    detail = (
        f"{player.full_name} has a guaranteed contract year remaining after {LATEST_SEASON}, "
        "but no model value is available to size an extension verdict."
    )
    return QueueItem(
        id=f"extension:{team_id}:{player.player_id}:{ctx.season}",
        type=TYPE_EXTENSION,
        priority="low",
        priority_reason=detail,
        title=f"{player.full_name}: extension eligible",
        detail=detail,
        player_id=player.player_id,
        team_id=team_id,
        value_pct=None,
        pay_pct=summary.current_pay_pct,
        gap_pct=None,
        value_usd=None,
        pay_usd=None,
        destination=f"/players/{player.player_id}",
        season=ctx.season,
        as_of=ctx.season,
        caution=NO_MODEL_VALUE_CAUTION,
    )


def _player_items(player: Player, team_id: int, ctx: _QueueContext) -> list[QueueItem]:
    items: list[QueueItem] = []
    option_or_expiring = _option_or_expiring_item(player, team_id, ctx)
    if option_or_expiring is not None:
        items.append(option_or_expiring)
    extension_item = _extension_item(player, team_id, ctx)
    if extension_item is not None:
        items.append(extension_item)
    return items


# --------------------------------------------------------------------------- cap tier
_CAP_TIER_PRIORITY = {
    TIER_SECOND_APRON: "high",
    TIER_FIRST_APRON: "medium",
    TIER_TAXPAYER: "medium",
    TIER_BELOW_TAX: "low",
}
_CAP_TIER_LABEL = {
    TIER_SECOND_APRON: "second apron",
    TIER_FIRST_APRON: "first apron",
    TIER_TAXPAYER: "taxpayer",
    TIER_BELOW_TAX: "below the tax line",
}
# The next line a tier could cross, used to phrase "how close" in the priority reason.
_NEAREST_LINE = {
    TIER_SECOND_APRON: "second apron",
    TIER_FIRST_APRON: "second apron",
    TIER_TAXPAYER: "first apron",
    TIER_BELOW_TAX: "tax line",
}


def _nearest_room(tier: str, rooms) -> float | None:
    if tier in (TIER_SECOND_APRON, TIER_FIRST_APRON):
        return rooms.room_to_second_apron
    if tier == TIER_TAXPAYER:
        return rooms.room_to_first_apron
    return rooms.room_to_tax


def _cap_tier_item(team: Team, team_id: int, roster: list[Player], ctx: _QueueContext) -> QueueItem:
    team_name = team.name or f"Team {team_id}"
    season = ctx.season
    salary_cap = ctx.salary_cap
    tax_line = ctx.tax_line
    first_apron = ctx.first_apron
    second_apron = ctx.second_apron

    payroll = sum(ctx.cap_hits.get(p.player_id, 0) for p in roster)

    tier = classify_tier(payroll, tax_line, first_apron, second_apron)
    rooms = room_to_lines(
        payroll, salary_cap=salary_cap, tax_line=tax_line, first_apron=first_apron, second_apron=second_apron
    )
    tier_label = _CAP_TIER_LABEL[tier]

    caution = None
    if tax_line is None:
        caution = f"Cap constants for {season} are not loaded; tier defaults to below-tax and room is unavailable."
        reason = f"{team_name}'s cap tier for {season} could not be classified without loaded cap constants."
    else:
        room = _nearest_room(tier, rooms)
        line_name = _NEAREST_LINE[tier]
        if room is None:
            reason = f"{team_name} is in the {tier_label} tier for {season}, an unknown margin to the {line_name}."
        else:
            direction = "over" if room < 0 else "below"
            reason = (
                f"{team_name} is in the {tier_label} tier for {season} — "
                f"${abs(room) / 1e6:,.1f}M {direction} the {line_name}."
            )

    pay_pct = round(payroll / salary_cap * 100, 2) if salary_cap else None
    detail = f"Payroll for {season} is ${payroll / 1e6:,.1f}M"
    detail += f" ({pay_pct}% of the cap)." if pay_pct is not None else "."

    return QueueItem(
        id=f"cap_tier:{team_id}:team:{season}",
        type=TYPE_CAP_TIER,
        priority=_CAP_TIER_PRIORITY[tier],
        priority_reason=reason,
        title=f"{team_name} cap tier: {tier_label}",
        detail=detail,
        player_id=None,
        team_id=team_id,
        value_pct=None,
        pay_pct=pay_pct,
        gap_pct=None,
        value_usd=None,
        pay_usd=payroll,
        destination=f"/teams?team={team_id}",
        season=season,
        as_of=season,
        caution=caution,
    )


# --------------------------------------------------------------------------- roster need
_ROSTER_NEED_PRIORITY = {"critical": "medium", "need": "low"}


def _roster_need_item(db, team_id: int, roster: list[Player], season: str) -> QueueItem | None:
    roster_ids = {p.player_id for p in roster}
    if not roster_ids:
        return None

    context = load_fit_context(db, LATEST_SEASON)
    profile = profile_roster(context, roster_ids)
    if not profile.needs:
        return None

    top = profile.needs[0]  # profile_roster sorts needs by deficit_pct descending
    if top.status == "covered":
        return None

    priority = _ROSTER_NEED_PRIORITY.get(top.status, "low")
    return QueueItem(
        id=f"roster_need:{team_id}:team:{season}",
        type=TYPE_ROSTER_NEED,
        priority=priority,
        priority_reason=f"{top.label} is the team's largest measured roster deficit ({top.status}).",
        title=f"Roster need: {top.label}",
        detail=f"{top.label} coverage is {top.coverage_pct}% of the league benchmark, a {top.deficit_pct}-point deficit.",
        player_id=None,
        team_id=team_id,
        value_pct=None,
        pay_pct=None,
        gap_pct=None,
        value_usd=None,
        pay_usd=None,
        destination=f"/free-agency?tab=targets&team={team_id}",
        season=season,
        as_of=LATEST_SEASON,
        caution=top.caution,
    )


# --------------------------------------------------------------------------- assembly
def build_decision_queue(db, team_id: int, season: str | None = None) -> DecisionQueue:
    """Assemble, band, and order a team's decision queue. `season` must be omitted or equal
    to LATEST_SEASON — every item here composes today's contracts, rosters, valuations, and
    roster-fit, so as-of-season composition is not implemented for any other value.

    Raises ValueError if `season` is provided and isn't LATEST_SEASON (the router maps that to
    422), and LookupError if the team does not exist (the router maps that to 404). Every other
    per-item failure (missing contract, missing valuation, missing model artifact) degrades that
    one item rather than raising, so the queue as a whole never 500s on one player's gap.
    """
    if season is not None and season != LATEST_SEASON:
        raise ValueError(
            f"decision-queue is only available for the current season {LATEST_SEASON}; "
            "as-of-season composition is not implemented."
        )
    team = db.get(Team, team_id)
    if team is None:
        raise LookupError(f"Team {team_id} not found.")
    target_season = LATEST_SEASON

    roster = db.scalars(select(Player).where(Player.current_team_id == team_id)).all()
    roster_ids = [p.player_id for p in roster]
    caps = load_season_caps(db)
    cap_data = cap_for(target_season, caps)

    contracts_by_player = _latest_contracts_for(db, roster_ids)
    years_by_contract = _contract_years_for(db, [c.id for c in contracts_by_player.values()])
    valuations = value_players(db, [(pid, LATEST_SEASON) for pid in roster_ids])
    value_pct_by_player = {pid: v.value_pct for (pid, _season), v in valuations.items()}
    option_pool_entering_by_player = _current_option_pool_entering(db)
    cap_hits, _pay_source = team_cap_hits(db, roster_ids, target_season)
    extension_summaries = batch_extension_summaries(db, roster_ids)

    eligible_summaries = [s for s in extension_summaries.values() if s.eligible]
    model_unavailable = bool(eligible_summaries) and all(not s.has_model_value for s in eligible_summaries)

    ctx = _QueueContext(
        season=target_season,
        caps=caps,
        salary_cap=cap_data.salary_cap if cap_data else None,
        tax_line=cap_data.tax_line if cap_data else None,
        first_apron=cap_data.first_apron if cap_data else None,
        second_apron=cap_data.second_apron if cap_data else None,
        contracts_by_player=contracts_by_player,
        years_by_contract=years_by_contract,
        value_pct_by_player=value_pct_by_player,
        option_pool_entering_by_player=option_pool_entering_by_player,
        cap_hits=cap_hits,
        extension_summaries=extension_summaries,
    )

    items: list[QueueItem] = []
    for player in roster:
        items.extend(_player_items(player, team_id, ctx))

    items.append(_cap_tier_item(team, team_id, roster, ctx))
    need_item = _roster_need_item(db, team_id, roster, target_season)
    if need_item is not None:
        items.append(need_item)

    items.sort(key=_sort_key)

    caveat = QUEUE_CAVEAT + (MODEL_UNAVAILABLE_CAVEAT if model_unavailable else "")

    return DecisionQueue(
        team_id=team_id,
        team_name=team.name,
        season=target_season,
        generated_from="latest",
        items=items,
        caveat=caveat,
        model_unavailable=model_unavailable,
    )
