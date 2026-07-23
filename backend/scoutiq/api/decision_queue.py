"""Team Decision Queue — composes existing extension, option, cap-tier, and roster-need
logic into one prioritized, read-only list of a team's highest-leverage contract, cap, and
roster questions. Deep module: no router imports; DB orchestration only (contract load,
extension/option verdicts, cap tier, roster fit) so it stays unit-testable without a live DB
or model artifact.

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
option and cap_tier facts are contractual and always appear; only extension's priority band
(which is genuinely model-driven) is pulled out of the high band when value_pct is None.
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
from scoutiq.api.extension import decide_extension
from scoutiq.api.roster_fit import load_fit_context
from scoutiq.api.rosters import team_cap_hits
from scoutiq.api.season import LATEST_SEASON
from scoutiq.api.valuation import value_player_detail
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
    "its own priority_reason, and links go to the existing ScoutIQ surface for that decision."
)


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


# --------------------------------------------------------------------------- contract lookups
def _latest_contract(db, player_id: int) -> Contract | None:
    return db.scalars(
        select(Contract)
        .where(Contract.player_id == player_id)
        .order_by(desc(Contract.season_start), desc(Contract.scraped_at))
        .limit(1)
    ).first()


def _contract_years(db, contract_id: int) -> list[ContractYear]:
    return db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id == contract_id)
        .order_by(ContractYear.season)
    ).all()


def _year_cap_pct(year: ContractYear, caps: dict[str, SeasonCapData]) -> float | None:
    """A contract year's cap hit as % of cap: the stored fraction, else AAV / that season's cap."""
    if year.cap_pct is not None:
        return round(float(year.cap_pct) * 100, 2)
    season_cap = cap_for(year.season, caps)
    if year.aav and season_cap:
        return round(year.aav / season_cap.salary_cap * 100, 2)
    return None


def _latest_value_pct(db, player_id: int) -> float | None:
    """Model value at the latest loaded season, degrading to None on any valuation failure —
    missing stats (LookupError) or a missing model artifact (FileNotFoundError) alike, so one
    player's model gap never breaks the rest of the queue."""
    try:
        valuation, _features, _attribution = value_player_detail(db, player_id, LATEST_SEASON)
    except (LookupError, FileNotFoundError):
        return None
    return valuation.value_pct


# --------------------------------------------------------------------------- option / expiring
def _option_item(
    db, player: Player, team_id: int, season: str, final_year: ContractYear, caps: dict[str, SeasonCapData]
) -> QueueItem:
    fa_type = fa.free_agent_type(final_year.is_player_option, final_year.is_team_option)
    option_cap_pct = _year_cap_pct(final_year, caps)
    verdict = None
    if option_cap_pct is not None:
        value_pct = _latest_value_pct(db, player.player_id)
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
        id=f"option:{team_id}:{player.player_id}:{season}",
        type=TYPE_OPTION,
        priority="high",
        priority_reason=f"An option decision is pending for {season}.",
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
        season=season,
        as_of=season,
        caution=caution,
    )


def _expiring_item(player: Player, team_id: int, season: str, final_year: ContractYear) -> QueueItem:
    pay_pct = round(float(final_year.cap_pct) * 100, 2) if final_year.cap_pct is not None else None
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


def _option_or_expiring_item(
    db, player: Player, team_id: int, season: str, caps: dict[str, SeasonCapData]
) -> QueueItem | None:
    contract = _latest_contract(db, player.player_id)
    if contract is None:
        return None
    years = _contract_years(db, contract.id)
    if not years:
        return None

    final_year = years[-1]  # ordered ascending by season -> last row is the max season
    if final_year.season < season:
        return None

    if final_year.is_player_option or final_year.is_team_option:
        return _option_item(db, player, team_id, season, final_year, caps)
    if final_year.season == season:
        return _expiring_item(player, team_id, season, final_year)
    return None


# --------------------------------------------------------------------------- extension
_EXTENSION_PRIORITY = {
    "Extend now": "high",
    "Fair — extend at market or wait": "medium",
    "Extend at market": "medium",
    "Don't extend": "low",
    "No model value": "low",
}


def _extension_item(db, player: Player, team_id: int, season: str) -> QueueItem | None:
    try:
        decision = decide_extension(db, player.player_id)
    except (LookupError, FileNotFoundError):
        return None
    if not decision.eligible:
        return None

    priority = _EXTENSION_PRIORITY.get(decision.verdict, "low")
    caution = None
    if decision.value_pct is None:
        caution = "No model value available; extension eligibility is factual, the verdict is not."

    return QueueItem(
        id=f"extension:{team_id}:{player.player_id}:{season}",
        type=TYPE_EXTENSION,
        priority=priority,
        priority_reason=decision.rationale,
        title=f"{player.full_name}: {decision.verdict}",
        detail=decision.rationale,
        player_id=player.player_id,
        team_id=team_id,
        value_pct=decision.value_pct,
        pay_pct=decision.current_pay_pct,
        gap_pct=decision.gap_pct,
        value_usd=decision.projected_aav_usd,
        pay_usd=None,
        destination=f"/players/{player.player_id}",
        season=season,
        as_of=decision.value_season,
        caution=caution,
    )


def _player_items(
    db, player: Player, team_id: int, season: str, caps: dict[str, SeasonCapData]
) -> list[QueueItem]:
    items: list[QueueItem] = []
    option_or_expiring = _option_or_expiring_item(db, player, team_id, season, caps)
    if option_or_expiring is not None:
        items.append(option_or_expiring)
    extension_item = _extension_item(db, player, team_id, season)
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


def _cap_tier_item(
    db, team: Team, team_id: int, season: str, roster: list[Player], caps: dict[str, SeasonCapData]
) -> QueueItem:
    team_name = team.name or f"Team {team_id}"
    cap_data = cap_for(season, caps)
    salary_cap = cap_data.salary_cap if cap_data else None
    tax_line = cap_data.tax_line if cap_data else None
    first_apron = cap_data.first_apron if cap_data else None
    second_apron = cap_data.second_apron if cap_data else None

    roster_ids = [p.player_id for p in roster]
    cap_hits, _pay_source = team_cap_hits(db, roster_ids, season)
    payroll = sum(cap_hits.values())

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
        destination=f"/teams/{team_id}",
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
        destination="/free-agency?tab=targets",
        season=season,
        as_of=LATEST_SEASON,
        caution=top.caution,
    )


# --------------------------------------------------------------------------- assembly
def build_decision_queue(db, team_id: int, season: str | None = None) -> DecisionQueue:
    """Assemble, band, and order a team's decision queue for `season` (defaults to LATEST_SEASON).

    Raises LookupError if the team does not exist; the router maps that to a 404. Every other
    per-item failure (missing contract, missing valuation, missing model artifact) degrades that
    one item rather than raising, so the queue as a whole never 500s on one player's gap.
    """
    team = db.get(Team, team_id)
    if team is None:
        raise LookupError(f"Team {team_id} not found.")
    target_season = season or LATEST_SEASON

    roster = db.scalars(select(Player).where(Player.current_team_id == team_id)).all()
    caps = load_season_caps(db)

    items: list[QueueItem] = []
    for player in roster:
        items.extend(_player_items(db, player, team_id, target_season, caps))

    items.append(_cap_tier_item(db, team, team_id, target_season, roster, caps))
    need_item = _roster_need_item(db, team_id, roster, target_season)
    if need_item is not None:
        items.append(need_item)

    items.sort(key=_sort_key)

    return DecisionQueue(
        team_id=team_id,
        team_name=team.name,
        season=target_season,
        generated_from="latest" if target_season == LATEST_SEASON else target_season,
        items=items,
        caveat=QUEUE_CAVEAT,
    )
