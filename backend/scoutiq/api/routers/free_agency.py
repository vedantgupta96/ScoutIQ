"""Free-agency surfaces derived from existing contract data.

Three read-only views, all built on data already in the DB (no schema change, no re-scrape):
  - GET /free-agency/board             — pending free agents for a summer, ranked by model value
  - GET /free-agency/options           — player/team option years + a pick-up/decline verdict
  - GET /free-agency/teams/{id}/targets — a team's projected cap room + affordable FA targets

Free-agency status is inferred: a player reaches the market the season after their final
contract year, and that year's option flags say how (expiring / player option / team option).
Ranking uses the production-implied valuation model at the player's latest stats season; there
is no market-price model, so a free agent's expiring AAV is shown only as a reference point.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from scoutiq.api import free_agency as fa
from scoutiq.api.cap import SeasonCapData, cap_for, classify_tier, load_season_caps, room_to_lines
from scoutiq.api.offseason import incomplete_roster_charge
from scoutiq.api.deps import DB
from scoutiq.api.roster_fit import (
    CandidateFitResponse,
    TeamNeedsResponse,
    candidate_fit_response,
    load_fit_context,
    needs_response,
)
from scoutiq.api.season import is_valid_season, next_season
from scoutiq.api.routers.players import (
    LATEST_SEASON,
    PlayerSummary,
    TeamSummary,
    _batched_summaries,
    _team_summary,
)
from scoutiq.api.routers.teams import team_cap_hits
from scoutiq.api.valuation import Valuation, value_players
from scoutiq.config import settings
from scoutiq.model.roster_fit import profile_roster, score_candidate
from scoutiq.models import Contract, ContractYear, FreeAgentRight, Player, PlayerSeason, Team

router = APIRouter(prefix="/free-agency", tags=["free-agency"])

BOARD_CAVEAT = (
    "UFA/RFA status, Bird category, cap holds, and qualifying offers use loaded Spotrac rows when "
    "available; uncovered players retain the service-time estimate. Ranking uses production-"
    "implied model value at the player's latest stats "
    "season; expiring AAV is a reference point, not a projected market price."
)
TARGETS_CAVEAT = (
    "Projected room applies the 4.5% cap escalator and counts contract salary, loaded retained cap "
    "holds, and the offseason incomplete-roster charge. It excludes dead money, draft-pick holds, "
    "exceptions, trades, and tax owed. 'Fits room' compares a target's model value (not a "
    "market price) to projected cap space. Roster fit is deterministic latest-season deficit "
    "reduction against a median-team benchmark, with recent minutes as a role proxy."
)


# --------------------------------------------------------------------------- response models
class OptionDecisionModel(BaseModel):
    fa_type: str
    deciding_party: str          # player | team
    option_cap_pct: float
    value_pct: float | None
    gap_pct: float | None
    verdict: str
    tone: str                    # positive | negative | neutral
    rationale: str


class FreeAgentEntry(PlayerSummary):
    age: int | None
    fa_type: str                 # expiring | player-option | team-option
    rfa_estimate: bool
    seasons_played: int
    expiring_season: str         # final season of the current contract
    entering_season: str         # season the player would be on a new deal
    expiring_aav_usd: int | None
    expiring_cap_pct: float | None
    value_pct: float | None
    lo_pct: float | None
    hi_pct: float | None
    value_usd: int | None        # value_pct applied to the entering-season cap
    valuation_season: str | None
    valuation_status: str        # ready | unavailable
    option: OptionDecisionModel | None = None
    fa_status: Literal["ufa", "rfa"]
    fa_status_source: Literal["spotrac", "estimated"]
    rights_team: TeamSummary | None = None
    bird_rights: Literal["bird", "early-bird", "non-bird", "two-way"] | None = None
    qualifying_offer_usd: int | None = None
    cap_hold_usd: int | None = None


class FreeAgencyBoardResponse(BaseModel):
    entering_season: str
    type: str
    items: list[FreeAgentEntry]
    total: int
    limit: int
    offset: int
    caveat: str


class FreeAgencyOptionsResponse(BaseModel):
    entering_season: str
    items: list[FreeAgentEntry]
    total: int
    limit: int
    offset: int
    caveat: str


class ProjectedCapContext(BaseModel):
    season: str
    is_projected: bool
    salary_cap: int | None
    tax_line: int | None
    first_apron: int | None
    second_apron: int | None
    committed_payroll_usd: int
    contract_payroll_usd: int
    cap_holds_usd: int
    incomplete_roster_charges_usd: int
    incomplete_roster_spots: int
    tier: str
    room_to_cap: int | None            # cap space; negative = over the cap
    room_to_tax: int | None
    room_to_first_apron: int | None
    room_to_second_apron: int | None


class TeamFaTarget(FreeAgentEntry):
    fits_room: bool | None             # model value ≤ projected cap space
    fit: CandidateFitResponse


class TeamFaTargetsResponse(BaseModel):
    team: TeamSummary
    entering_season: str
    cap_context: ProjectedCapContext
    committed_player_count: int
    needs: TeamNeedsResponse
    targets: list[TeamFaTarget]
    limit: int
    caveat: str


_TARGET_POOL_TTL_SECONDS = 300
_target_pool_cache: dict[tuple[object, str, str | None], tuple[float, list[FreeAgentEntry]]] = {}
_target_pool_cache_lock = threading.Lock()


# --------------------------------------------------------------------------- internal assembly
@dataclass
class _PoolEntry:
    player: Player
    last_year: ContractYear
    expiring_season: str
    entering_season: str
    fa_type: str
    seasons_played: int
    latest_season_row: PlayerSeason | None


def _latest_contract_per_player(db: DB) -> list[Contract]:
    """One contract per player — the most recent by season_start, then scrape time."""
    return db.scalars(
        select(Contract)
        .distinct(Contract.player_id)
        .order_by(Contract.player_id, desc(Contract.season_start), desc(Contract.scraped_at))
    ).all()


def _assemble_pool(
    db: DB, entering: str, *, type_filter: str | None, position: str | None
) -> list[_PoolEntry]:
    """Players whose current contract ends the season before `entering`, with option context."""
    target_expiry = fa.prev_season(entering)
    if target_expiry is None:
        return []

    contracts = _latest_contract_per_player(db)
    by_contract_id = {c.id: c for c in contracts}
    if not by_contract_id:
        return []

    # Final contract year per contract → determines expiry season + option flags.
    last_year_by_contract: dict[int, ContractYear] = {}
    for cy in db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id.in_(by_contract_id.keys()))
        .order_by(ContractYear.contract_id, ContractYear.season)
    ).all():
        last_year_by_contract[cy.contract_id] = cy  # ordered ascending → last wins = max season

    # Two ways a contract lands a player in the summer entering `entering`:
    #   - it ends the prior season (final year == prev_season) → straight expiring (UFA/RFA),
    #   - OR its final year IS `entering` and is an option → declining it opens `entering`.
    # An option on the prior season is a past decision, so those are treated as expiring.
    matched: list[tuple[Contract, ContractYear, str]] = []
    for cid, last_year in last_year_by_contract.items():
        is_option = last_year.is_player_option or last_year.is_team_option
        if last_year.season == target_expiry:
            matched.append((by_contract_id[cid], last_year, fa.FA_EXPIRING))
        elif last_year.season == entering and is_option:
            fa_type = fa.free_agent_type(last_year.is_player_option, last_year.is_team_option)
            matched.append((by_contract_id[cid], last_year, fa_type))
    if not matched:
        return []

    player_ids = [c.player_id for c, _, _ in matched]
    players = {
        p.player_id: p
        for p in db.scalars(select(Player).where(Player.player_id.in_(player_ids))).all()
    }

    # Latest stats row (for features/age) and completed-season count (RFA heuristic), batched.
    latest_row_by_player: dict[int, PlayerSeason] = {
        row.player_id: row
        for row in db.scalars(
            select(PlayerSeason)
            .where(PlayerSeason.player_id.in_(player_ids))
            .distinct(PlayerSeason.player_id)
            .order_by(PlayerSeason.player_id, desc(PlayerSeason.season))
        ).all()
    }
    seasons_played_by_player: dict[int, int] = dict(
        db.execute(
            select(PlayerSeason.player_id, func.count())
            .where(PlayerSeason.player_id.in_(player_ids))
            .group_by(PlayerSeason.player_id)
        ).all()
    )

    pool: list[_PoolEntry] = []
    for contract, last_year, fa_type in matched:
        player = players.get(contract.player_id)
        if player is None:
            continue
        if type_filter and fa_type != type_filter:
            continue
        if position and not (player.position or "").lower().startswith(position.lower()):
            continue
        pool.append(
            _PoolEntry(
                player=player,
                last_year=last_year,
                expiring_season=last_year.season,
                entering_season=entering,
                fa_type=fa_type,
                seasons_played=seasons_played_by_player.get(contract.player_id, 0),
                latest_season_row=latest_row_by_player.get(contract.player_id),
            )
        )
    return pool


def _value_pool(db: DB, pool: list[_PoolEntry]) -> dict[int, Valuation]:
    """Batch model valuation for every pool player with a latest stats season."""
    targets = [
        (e.player.player_id, e.latest_season_row.season)
        for e in pool
        if e.latest_season_row is not None
    ]
    valuations = value_players(db, targets)
    return {
        player_id: valuations[(player_id, season)]
        for player_id, season in targets
        if (player_id, season) in valuations
    }


def _entry_models(
    db: DB,
    pool: list[_PoolEntry],
    caps: dict[str, SeasonCapData],
    *,
    with_option: bool,
) -> list[FreeAgentEntry]:
    """Turn assembled pool entries into API models, valued and (optionally) with an option verdict."""
    summaries = _batched_summaries([e.player for e in pool], db)
    value_by_player = _value_pool(db, pool)
    entering_cap = cap_for(pool[0].entering_season, caps) if pool else None
    entering_salary_cap = entering_cap.salary_cap if entering_cap else None
    rights_rows = (
        db.scalars(
            select(FreeAgentRight)
            .where(FreeAgentRight.player_id.in_([e.player.player_id for e in pool]))
            .where(FreeAgentRight.entering_season == pool[0].entering_season)
        ).all()
        if pool
        else []
    )
    rights_by_player = {row.player_id: row for row in rights_rows}
    rights_team_ids = {row.rights_team_id for row in rights_rows if row.rights_team_id}
    rights_teams = (
        {
            team.team_id: _team_summary(team)
            for team in db.scalars(
                select(Team).where(Team.team_id.in_(rights_team_ids))
            ).all()
        }
        if rights_team_ids
        else {}
    )

    entries: list[FreeAgentEntry] = []
    for e in pool:
        pid = e.player.player_id
        right = rights_by_player.get(pid)
        summary = summaries[pid]
        pred = value_by_player.get(pid)
        value_pct = pred.value_pct if pred else None

        # expiring pay as % of cap: stored fraction if present, else AAV / expiry-season cap
        expiry_cap = cap_for(e.expiring_season, caps)
        expiry_salary_cap = expiry_cap.salary_cap if expiry_cap else None
        if e.last_year.cap_pct is not None:
            expiring_cap_pct = round(float(e.last_year.cap_pct) * 100, 2)
        elif e.last_year.aav and expiry_salary_cap:
            expiring_cap_pct = round(e.last_year.aav / expiry_salary_cap * 100, 2)
        else:
            expiring_cap_pct = None

        value_usd = (
            int(round(value_pct / 100 * entering_salary_cap))
            if (value_pct is not None and entering_salary_cap)
            else None
        )

        option = None
        if (
            with_option
            and e.fa_type in (fa.FA_PLAYER_OPTION, fa.FA_TEAM_OPTION)
            and expiring_cap_pct is not None
        ):
            verdict = fa.option_decision(value_pct, expiring_cap_pct, e.fa_type)
            option = OptionDecisionModel(
                fa_type=verdict.fa_type,
                deciding_party=verdict.deciding_party,
                option_cap_pct=verdict.option_cap_pct,
                value_pct=verdict.value_pct,
                gap_pct=verdict.gap_pct,
                verdict=verdict.verdict,
                tone=verdict.tone,
                rationale=verdict.rationale,
            )

        entries.append(
            FreeAgentEntry(
                **summary.model_dump(),
                age=e.latest_season_row.age if e.latest_season_row else None,
                fa_type=e.fa_type,
                rfa_estimate=fa.rfa_estimate(e.seasons_played),
                seasons_played=e.seasons_played,
                expiring_season=e.expiring_season,
                entering_season=e.entering_season,
                expiring_aav_usd=e.last_year.aav,
                expiring_cap_pct=expiring_cap_pct,
                value_pct=value_pct,
                lo_pct=pred.lo_pct if pred else None,
                hi_pct=pred.hi_pct if pred else None,
                value_usd=value_usd,
                valuation_season=e.latest_season_row.season if e.latest_season_row else None,
                valuation_status="ready" if pred else "unavailable",
                option=option,
                fa_status=(
                    right.fa_status
                    if right and right.fa_status
                    else "rfa" if fa.rfa_estimate(e.seasons_played) else "ufa"
                ),
                fa_status_source="spotrac" if right and right.fa_status else "estimated",
                rights_team=rights_teams.get(right.rights_team_id) if right else None,
                bird_rights=right.bird_rights if right else None,
                qualifying_offer_usd=right.qualifying_offer_usd if right else None,
                cap_hold_usd=right.cap_hold_usd if right else None,
            )
        )
    return entries


def _sorted_by_value(entries: list[FreeAgentEntry]) -> list[FreeAgentEntry]:
    """Most valuable first; unvalued players sink to the bottom, then alphabetical."""
    return sorted(
        entries,
        key=lambda x: (x.value_pct is not None, x.value_pct or 0.0, x.full_name),
        reverse=True,
    )


def _target_pool_entries(
    db: DB,
    entering: str,
    position: str | None,
    caps: dict[str, SeasonCapData],
) -> list[FreeAgentEntry]:
    """Cache the static market pool while keeping team fit and cap checks live."""
    bind = db.get_bind() if hasattr(db, "get_bind") else db
    cache_key = (bind, entering, position)
    now = time.monotonic()
    with _target_pool_cache_lock:
        cached = _target_pool_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]

    pool = _assemble_pool(db, entering, type_filter=None, position=position)
    entries = _sorted_by_value(_entry_models(db, pool, caps, with_option=False))
    with _target_pool_cache_lock:
        _target_pool_cache[cache_key] = (now + _TARGET_POOL_TTL_SECONDS, entries)
        expired = [key for key, (expires_at, _) in _target_pool_cache.items() if expires_at <= now]
        for key in expired:
            _target_pool_cache.pop(key, None)
    return entries


def _resolve_entering(season: str | None) -> str:
    """Default to the next free-agency summer; validate an explicit season."""
    if season is None:
        return next_season(settings.CURRENT_SEASON) or next_season(LATEST_SEASON)
    if not is_valid_season(season):
        raise HTTPException(
            status_code=422, detail="season must be a 'YYYY-YY' label, e.g. '2026-27'."
        )
    return season


def _player_id_set(value: str | None, field: str) -> set[int]:
    if value is None or not value.strip():
        return set()
    try:
        player_ids = {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be comma-separated player IDs.") from exc
    if len(player_ids) > 10 or any(player_id <= 0 for player_id in player_ids):
        raise HTTPException(status_code=422, detail=f"{field} must contain 1-10 positive player IDs.")
    return player_ids


# --------------------------------------------------------------------------- endpoints
@router.get("/board", response_model=FreeAgencyBoardResponse)
def get_free_agency_board(
    season: str | None = Query(None, description="Entering season, e.g. '2026-27'. Defaults to next summer."),
    type: str | None = Query(None, description="Filter: expiring | player-option | team-option."),
    position: str | None = Query(None, min_length=1, max_length=8),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: DB = None,
):
    """Players reaching free agency in `season`, ranked by production-implied model value."""
    entering = _resolve_entering(season)
    if type is not None and type not in fa.FA_TYPES:
        raise HTTPException(
            status_code=422, detail=f"type must be one of {', '.join(fa.FA_TYPES)}."
        )

    caps = load_season_caps(db)
    pool = _assemble_pool(db, entering, type_filter=type, position=position)
    entries = _sorted_by_value(_entry_models(db, pool, caps, with_option=False))
    page = entries[offset : offset + limit]
    return FreeAgencyBoardResponse(
        entering_season=entering,
        type=type or "all",
        items=page,
        total=len(entries),
        limit=limit,
        offset=offset,
        caveat=BOARD_CAVEAT,
    )


@router.get("/options", response_model=FreeAgencyOptionsResponse)
def get_free_agency_options(
    season: str | None = Query(None, description="Entering season, e.g. '2026-27'. Defaults to next summer."),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: DB = None,
):
    """Player/team option years for `season`, each with a pick-up/decline recommendation."""
    entering = _resolve_entering(season)
    caps = load_season_caps(db)

    pool = [
        e
        for e in _assemble_pool(db, entering, type_filter=None, position=None)
        if e.fa_type in (fa.FA_PLAYER_OPTION, fa.FA_TEAM_OPTION)
    ]
    entries = _sorted_by_value(_entry_models(db, pool, caps, with_option=True))
    page = entries[offset : offset + limit]
    return FreeAgencyOptionsResponse(
        entering_season=entering,
        items=page,
        total=len(entries),
        limit=limit,
        offset=offset,
        caveat=BOARD_CAVEAT,
    )


@router.get("/teams/{team_id}/targets", response_model=TeamFaTargetsResponse)
def get_team_fa_targets(
    team_id: int,
    season: str | None = Query(None, description="Entering season, e.g. '2026-27'. Defaults to next summer."),
    position: str | None = Query(None, min_length=1, max_length=8),
    sort: Literal["fit", "value"] = Query("fit"),
    add: str | None = Query(None, description="Comma-separated staged player IDs to add to the fit roster."),
    remove: str | None = Query(None, description="Comma-separated staged player IDs to remove from the fit roster."),
    limit: int = Query(15, ge=1, le=50),
    db: DB = None,
):
    """A team's projected cap room for `season` plus the top FA targets that fit it."""
    entering = _resolve_entering(season)
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found.")

    caps = load_season_caps(db)
    entering_cap = cap_for(entering, caps)
    salary_cap = entering_cap.salary_cap if entering_cap else None
    tax_line = entering_cap.tax_line if entering_cap else None
    first_apron = entering_cap.first_apron if entering_cap else None
    second_apron = entering_cap.second_apron if entering_cap else None

    # Committed payroll = guaranteed contract salary already on the books for `entering`.
    roster_ids = [
        p.player_id
        for p in db.scalars(select(Player).where(Player.current_team_id == team_id)).all()
    ]
    cap_hits, _ = team_cap_hits(db, roster_ids, entering)
    contract_payroll = sum(cap_hits.values())
    rights = db.scalars(
        select(FreeAgentRight)
        .where(FreeAgentRight.rights_team_id == team_id)
        .where(FreeAgentRight.entering_season == entering)
    ).all()
    retained_holds = {
        row.player_id: row.cap_hold_usd
        for row in rights
        if row.cap_hold_usd and row.player_id not in cap_hits
    }
    cap_holds = sum(retained_holds.values())
    incomplete, incomplete_spots = (
        incomplete_roster_charge(salary_cap, len(cap_hits) + len(retained_holds))
        if salary_cap
        else (0, 0)
    )
    committed = contract_payroll + cap_holds + incomplete
    add_ids = _player_id_set(add, "add")
    remove_ids = _player_id_set(remove, "remove")
    fit_roster_ids = (set(cap_hits) - remove_ids) | add_ids

    tier = classify_tier(committed, tax_line, first_apron, second_apron)
    rooms = room_to_lines(
        committed, salary_cap=salary_cap, tax_line=tax_line, first_apron=first_apron, second_apron=second_apron
    )
    cap_context = ProjectedCapContext(
        season=entering,
        is_projected=entering_cap.is_projected if entering_cap else False,
        salary_cap=salary_cap,
        tax_line=tax_line,
        first_apron=first_apron,
        second_apron=second_apron,
        committed_payroll_usd=committed,
        contract_payroll_usd=contract_payroll,
        cap_holds_usd=cap_holds,
        incomplete_roster_charges_usd=incomplete,
        incomplete_roster_spots=incomplete_spots,
        tier=tier,
        room_to_cap=rooms.room_to_cap,
        room_to_tax=rooms.room_to_tax,
        room_to_first_apron=rooms.room_to_first_apron,
        room_to_second_apron=rooms.room_to_second_apron,
    )

    room_to_cap = cap_context.room_to_cap
    ranked = [
        entry
        for entry in _target_pool_entries(db, entering, position, caps)
        if entry.player_id not in add_ids
    ]
    fit_context = load_fit_context(db, LATEST_SEASON)
    needs = needs_response(profile_roster(fit_context, fit_roster_ids), LATEST_SEASON)

    targets = [
        TeamFaTarget(
            **entry.model_dump(),
            fits_room=(entry.value_usd <= room_to_cap) if (entry.value_usd is not None and room_to_cap is not None) else None,
            fit=candidate_fit_response(
                score_candidate(fit_context, fit_roster_ids, entry.player_id)
            ),
        )
        for entry in ranked
    ]
    if sort == "fit":
        targets.sort(
            key=lambda entry: (entry.fit.fit_score, entry.value_pct or 0.0),
            reverse=True,
        )
    targets = targets[:limit]
    return TeamFaTargetsResponse(
        team=_team_summary(team),
        entering_season=entering,
        cap_context=cap_context,
        committed_player_count=len(cap_hits),
        needs=needs,
        targets=targets,
        limit=limit,
        caveat=TARGETS_CAVEAT,
    )
