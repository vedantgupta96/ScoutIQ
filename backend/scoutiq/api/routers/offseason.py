"""Team offseason planning endpoint.

Combines the existing roster cap sheet, proposed contracts, and option decisions into a
single multi-season payroll ledger. The supported move set is intentionally narrow: new
signings/re-signings and valid option removals. Cap holds, Bird rights, exceptions, waivers,
and trade rules remain explicit non-modeled assumptions.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from scoutiq.api.cap_simulator import build_season_sequence, simulate
from scoutiq.api.deps import DB
from scoutiq.api.offseason import PlannedContract, apply_plan
from scoutiq.api.roster_fit import TeamNeedsResponse, load_fit_context, needs_response
from scoutiq.api.routers.free_agency import _season_caps
from scoutiq.api.routers.players import LATEST_SEASON, TeamSummary, _team_summary
from scoutiq.api.routers.teams import team_cap_hits
from scoutiq.api.season import is_valid_season
from scoutiq.model.predict import build_features_from_season, predict_many_from_features
from scoutiq.model.roster_fit import profile_roster
from scoutiq.models import Contract, ContractYear, Player, PlayerSeason, Team

router = APIRouter(prefix="/offseason", tags=["offseason"])

PLAN_CAVEAT = (
    "Planning baseline uses current-roster contract hits and proposed deals at a constant share "
    "of the cap. It excludes cap holds, incomplete-roster charges, dead money, Bird rights, "
    "exceptions, waivers, trades, luxury tax owed, and repeater-tax history. Player-option "
    "removals are scenarios, not predictions of the player's decision. Roster needs use "
    "latest-season role statistics and recent minutes as a proxy, not a lineup forecast."
)


class ProposedContractRequest(BaseModel):
    player_id: int
    aav_pct: float = Field(..., gt=0, le=35)
    years: int = Field(..., ge=1, le=5)
    guaranteed_years: int | None = Field(None, ge=0, le=5)
    player_option_years: int = Field(0, ge=0, le=2)
    team_option_years: int = Field(0, ge=0, le=2)

    @model_validator(mode="after")
    def validate_structure(self):
        option_years = self.player_option_years + self.team_option_years
        guaranteed = self.guaranteed_years if self.guaranteed_years is not None else self.years - option_years
        if option_years > self.years or guaranteed + option_years > self.years:
            raise ValueError(
                "guaranteed_years + player_option_years + team_option_years cannot exceed years"
            )
        return self


class OffseasonPlanRequest(BaseModel):
    team_id: int
    start_season: str
    horizon: int = Field(4, ge=1, le=5)
    valuation_season: str | None = None
    contracts: list[ProposedContractRequest] = Field(default_factory=list, max_length=10)
    option_declines: list[int] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_plan(self):
        if not is_valid_season(self.start_season):
            raise ValueError("start_season must be a 'YYYY-YY' label, e.g. '2026-27'")
        if self.valuation_season is not None and not is_valid_season(self.valuation_season):
            raise ValueError("valuation_season must be a 'YYYY-YY' label, e.g. '2025-26'")

        contract_ids = [move.player_id for move in self.contracts]
        if len(contract_ids) != len(set(contract_ids)):
            raise ValueError("each player can have only one proposed contract")
        if len(self.option_declines) != len(set(self.option_declines)):
            raise ValueError("option_declines cannot contain duplicate players")
        overlap = set(contract_ids) & set(self.option_declines)
        if overlap:
            raise ValueError("a player cannot have both a proposed contract and an option decline")
        if any(move.years > self.horizon for move in self.contracts):
            raise ValueError("proposed contract years cannot exceed the plan horizon")
        return self


class OffseasonContractYear(BaseModel):
    season: str
    cap_hit_usd: int
    cap_hit_pct: float
    is_guaranteed: bool
    is_player_option: bool
    is_team_option: bool
    is_projected_cap: bool


class OffseasonMoveResponse(BaseModel):
    player_id: int
    player_name: str
    kind: Literal["signing", "re-sign", "team-option-decline", "player-option-opt-out"]
    value_pct: float | None = None
    value_gap_pct: float | None = None
    removed_existing_usd: int = 0
    years: list[OffseasonContractYear] = Field(default_factory=list)


class OffseasonPlanSeason(BaseModel):
    season: str
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int
    is_projected_cap: bool
    baseline_payroll_usd: int
    payroll_after_usd: int
    payroll_delta_usd: int
    baseline_roster_count: int
    roster_count_after: int
    tier_before: str
    tier_after: str
    crosses_a_line: bool
    room_to_cap_after: int
    room_to_tax_after: int
    room_to_first_apron_after: int
    room_to_second_apron_after: int


class OffseasonPlanResponse(BaseModel):
    team: TeamSummary
    start_season: str
    valuation_season: str
    moves: list[OffseasonMoveResponse]
    seasons: list[OffseasonPlanSeason]
    needs_before: TeamNeedsResponse
    needs_after: TeamNeedsResponse
    caveat: str


def _option_rows(db: DB, player_ids: list[int], season: str) -> dict[int, ContractYear]:
    if not player_ids:
        return {}
    rows = db.execute(
        select(ContractYear, Contract.player_id)
        .join(Contract, Contract.id == ContractYear.contract_id)
        .where(Contract.player_id.in_(player_ids))
        .where(ContractYear.season == season)
        .order_by(Contract.season_start)
    ).all()
    return {player_id: year for year, player_id in rows}


def _valuations(
    db: DB, players_by_id: dict[int, Player], season: str
) -> dict[int, dict]:
    player_ids = list(players_by_id)
    if not player_ids:
        return {}
    season_rows = db.scalars(
        select(PlayerSeason)
        .where(PlayerSeason.player_id.in_(player_ids))
        .where(PlayerSeason.season == season)
    ).all()
    if not season_rows:
        return {}
    try:
        predictions = predict_many_from_features(
            [build_features_from_season(row, players_by_id[row.player_id]) for row in season_rows]
        )
    except FileNotFoundError:
        return {}
    return {row.player_id: pred for row, pred in zip(season_rows, predictions)}


@router.post("/plan", response_model=OffseasonPlanResponse)
def build_offseason_plan(req: OffseasonPlanRequest, db: DB = None):
    """Apply proposed contracts and option removals to a team's multi-season payroll."""
    team = db.get(Team, req.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found.")

    caps = _season_caps(db)
    if not caps:
        raise HTTPException(status_code=503, detail="No cap constants found in DB.")
    try:
        plan_caps = build_season_sequence(req.start_season, req.horizon, caps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    roster = db.scalars(select(Player).where(Player.current_team_id == req.team_id)).all()
    roster_ids = [player.player_id for player in roster]
    baseline_hits = {
        cap.season: team_cap_hits(db, roster_ids, cap.season)[0]
        for cap in plan_caps
    }

    requested_ids = {move.player_id for move in req.contracts} | set(req.option_declines)
    requested_players = (
        db.scalars(select(Player).where(Player.player_id.in_(requested_ids))).all()
        if requested_ids
        else []
    )
    players_by_id = {player.player_id: player for player in requested_players}
    missing_ids = sorted(requested_ids - set(players_by_id))
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Players not found: {missing_ids}.")

    valuation_season = req.valuation_season or LATEST_SEASON
    contract_players = {
        move.player_id: players_by_id[move.player_id] for move in req.contracts
    }
    valuations = _valuations(db, contract_players, valuation_season)

    planned_contracts: list[PlannedContract] = []
    move_responses: list[OffseasonMoveResponse] = []
    for move in req.contracts:
        player = players_by_id[move.player_id]
        valuation = valuations.get(move.player_id)
        simulation = simulate(
            player_id=move.player_id,
            player_name=player.full_name,
            aav_pct=move.aav_pct,
            years=move.years,
            guaranteed_years=move.guaranteed_years,
            player_option_years=move.player_option_years,
            team_option_years=move.team_option_years,
            start_season=req.start_season,
            cap_by_season=caps,
            valuation=valuation,
        )
        planned_contracts.append(
            PlannedContract(player_id=move.player_id, years=simulation.years)
        )
        move_responses.append(
            OffseasonMoveResponse(
                player_id=move.player_id,
                player_name=player.full_name,
                kind="re-sign" if player.current_team_id == req.team_id else "signing",
                value_pct=simulation.value_pct,
                value_gap_pct=simulation.value_gap_pct,
                removed_existing_usd=baseline_hits[req.start_season].get(move.player_id, 0),
                years=[
                    OffseasonContractYear(
                        season=year.season,
                        cap_hit_usd=year.cap_hit_usd,
                        cap_hit_pct=year.cap_hit_pct,
                        is_guaranteed=year.is_guaranteed,
                        is_player_option=year.is_player_option,
                        is_team_option=year.is_team_option,
                        is_projected_cap=year.is_projected_cap,
                    )
                    for year in simulation.years
                ],
            )
        )

    option_rows = _option_rows(db, req.option_declines, req.start_season)
    roster_id_set = set(roster_ids)
    for player_id in req.option_declines:
        if player_id not in roster_id_set:
            raise HTTPException(
                status_code=422,
                detail=f"Player {player_id} is not on the selected team's current roster.",
            )
        option = option_rows.get(player_id)
        if option is None or not (option.is_team_option or option.is_player_option):
            raise HTTPException(
                status_code=422,
                detail=f"Player {player_id} has no option year in {req.start_season}.",
            )
        removed = baseline_hits[req.start_season].get(player_id, 0)
        if removed <= 0:
            raise HTTPException(
                status_code=422,
                detail=f"Player {player_id} has no removable cap hit in {req.start_season}.",
            )
        move_responses.append(
            OffseasonMoveResponse(
                player_id=player_id,
                player_name=players_by_id[player_id].full_name,
                kind=(
                    "team-option-decline"
                    if option.is_team_option
                    else "player-option-opt-out"
                ),
                removed_existing_usd=removed,
            )
        )

    seasons = apply_plan(
        plan_caps,
        baseline_hits,
        planned_contracts,
        set(req.option_declines),
    )
    baseline_role_ids = set(baseline_hits[req.start_season])
    planned_role_ids = (
        baseline_role_ids - set(req.option_declines)
    ) | {move.player_id for move in req.contracts}
    fit_context = load_fit_context(db, valuation_season)
    return OffseasonPlanResponse(
        team=_team_summary(team),
        start_season=req.start_season,
        valuation_season=valuation_season,
        moves=move_responses,
        seasons=[OffseasonPlanSeason(**vars(season)) for season in seasons],
        needs_before=needs_response(
            profile_roster(fit_context, baseline_role_ids), valuation_season
        ),
        needs_after=needs_response(
            profile_roster(fit_context, planned_role_ids), valuation_season
        ),
        caveat=PLAN_CAVEAT,
    )
