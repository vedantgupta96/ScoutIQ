"""What-If Contract & Cap Simulator routes."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from scoutiq.api.cap import SeasonCapData, load_season_caps
from scoutiq.api.cap_simulator import apron_outlook, simulate
from scoutiq.api.deps import DB
from scoutiq.api.season import is_valid_season
from scoutiq.api.routers.teams import team_cap_hits
from scoutiq.api.valuation import value_players
from scoutiq.models import Player, Team

router = APIRouter(tags=["simulator"])

# Most recent season with full model features — used as the valuation base.
# Mirrors players.LATEST_SEASON; advance both each offseason after the ETL runs.
# 2025-26 cap constants are loaded, so the simulator now uses actual (not
# projected) caps for current-season contracts.
VALUATION_SEASON = "2025-26"


class SimulatorRequest(BaseModel):
    player_id: int
    aav_pct: float = Field(..., gt=0, le=100, description="Proposed AAV as % of salary cap (e.g. 20.0)")
    years: int = Field(..., ge=1, le=5, description="Contract length in years")
    guaranteed_years: int | None = Field(
        None,
        ge=0,
        description="Fully guaranteed years. If omitted, all non-option years are treated as guaranteed.",
    )
    player_option_years: int = Field(0, ge=0, description="Player option years (after guaranteed)")
    team_option_years: int = Field(0, ge=0, description="Team option years (at end of contract)")
    start_season: str = Field("2025-26", description="First season of the contract (YYYY-YY)")
    valuation_season: str | None = Field(None, description="Season to use for model valuation (defaults to latest)")
    team_id: int | None = Field(
        None,
        description="If set, overlay the first-year cap hit on this team's payroll to show apron consequences.",
    )

    @field_validator("start_season", "valuation_season")
    @classmethod
    def _check_season(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_season(v):
            raise ValueError("must be a 'YYYY-YY' season label, e.g. '2025-26'")
        return v


class ContractYearResponse(BaseModel):
    season: str
    cap_hit_usd: int
    cap_hit_pct: float
    is_guaranteed: bool
    is_player_option: bool
    is_team_option: bool
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int
    is_projected_cap: bool


class SimulatorAssumptions(BaseModel):
    standalone_contract_only: bool
    simplified_cba: bool
    cap_projection_rate: float
    not_modeled: list[str]


class ApronOutlookResponse(BaseModel):
    team_id: int
    team_name: str | None
    season: str
    existing_payroll_usd: int
    replaces_existing_usd: int
    proposed_cap_hit_usd: int
    payroll_after_usd: int
    tier_before: str
    tier_after: str
    crosses_a_line: bool
    room_to_tax_after: int | None
    room_to_first_apron_after: int | None
    room_to_second_apron_after: int | None
    consequences: list[str]


class SimulatorResponse(BaseModel):
    player_id: int
    player_name: str
    proposed_aav_pct: float
    proposed_aav_usd: int
    value_pct: float | None
    value_usd: int | None
    lo_pct: float | None
    hi_pct: float | None
    value_gap_pct: float | None
    model_version: str | None
    assumptions: SimulatorAssumptions
    years: list[ContractYearResponse]
    valuation_season: str
    disclaimer: str
    apron_outlook: ApronOutlookResponse | None = None


def _simulate_cap(req: SimulatorRequest, db: DB = None) -> dict:
    """Simulate a proposed contract against the cap and the valuation model.

    Returns year-by-year cap hits, apron thresholds, and the model's production-implied
    value gap (positive = player being underpaid relative to production).

    Cap constants for future seasons beyond the DB are projected at 4.5%/yr growth.
    """
    player = db.get(Player, req.player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {req.player_id} not found.")

    option_years = req.player_option_years + req.team_option_years
    total_known_years = option_years + (req.guaranteed_years or 0)
    if option_years > req.years or (req.guaranteed_years is not None and total_known_years > req.years):
        raise HTTPException(
            status_code=422,
            detail="guaranteed_years + player_option_years + team_option_years cannot exceed years.",
        )

    cap_by_season = load_season_caps(db)

    if not cap_by_season:
        raise HTTPException(status_code=503, detail="No cap constants found in DB.")

    # run valuation model on player's most recent stats
    val_season = req.valuation_season or VALUATION_SEASON
    v = value_players(db, [(req.player_id, val_season)]).get((req.player_id, val_season))
    valuation = (
        {
            "value_pct": v.value_pct,
            "lo_pct": v.lo_pct,
            "hi_pct": v.hi_pct,
            "model_version": v.model_version,
        }
        if v is not None
        else None
    )

    try:
        result = simulate(
            player_id=req.player_id,
            player_name=player.full_name,
            aav_pct=req.aav_pct,
            years=req.years,
            guaranteed_years=req.guaranteed_years,
            player_option_years=req.player_option_years,
            team_option_years=req.team_option_years,
            start_season=req.start_season,
            cap_by_season=cap_by_season,
            valuation=valuation,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # convert dataclass to dict (JSON-serialisable)
    d = asdict(result)
    d["valuation_season"] = val_season

    outlook = _apron_overlay(req, player, result, db) if req.team_id is not None else None
    d["apron_outlook"] = asdict(outlook) if outlook is not None else None

    if outlook is not None:
        d["disclaimer"] = (
            "First-year cap hit overlaid on the team's current payroll to show apron consequences. "
            "Simplified CBA subset: excludes dead money, cap holds, incomplete-roster charges, "
            "Bird rights, MLE/BAE, luxury tax owed, the repeater tax, and traded-player exceptions."
        )
    else:
        d["disclaimer"] = (
            "Standalone contract simulation only. It uses a simplified CBA subset and does not model "
            "team payroll, luxury tax owed, Bird rights, MLE/BAE, repeater tax, or traded-player exceptions."
        )
    return d


def _apron_overlay(req: SimulatorRequest, player: Player, result, db: DB):
    """Overlay the proposed first-year cap hit on `team_id`'s payroll for the start season.

    Sums the team's current roster cost, nets out the player's existing figure on a
    re-sign, and reports the resulting apron tier and its CBA consequences. Returns None
    if the contract has no years (can't happen) — otherwise an ApronOutlook.
    """
    if not result.years:
        return None
    team = db.get(Team, req.team_id)
    roster = db.scalars(select(Player).where(Player.current_team_id == req.team_id)).all()
    cap_hits, _ = team_cap_hits(db, [p.player_id for p in roster], req.start_season)
    existing_payroll = sum(cap_hits.values())
    # Net out the player's current cap figure only if they're already on this team.
    replaces = cap_hits.get(req.player_id, 0) if player.current_team_id == req.team_id else 0

    first_year = result.years[0]
    cap_data = SeasonCapData(
        season=first_year.season,
        salary_cap=first_year.salary_cap,
        tax_line=first_year.tax_line,
        first_apron=first_year.first_apron,
        second_apron=first_year.second_apron,
        is_projected=first_year.is_projected_cap,
    )
    return apron_outlook(
        team_id=req.team_id,
        team_name=team.name if team else None,
        season=first_year.season,
        existing_payroll_usd=existing_payroll,
        replaces_existing_usd=replaces,
        proposed_cap_hit_usd=first_year.cap_hit_usd,
        cap_data=cap_data,
    )


@router.post("/simulate/contract", response_model=SimulatorResponse)
def simulate_contract(req: SimulatorRequest, db: DB = None):
    """Canonical what-if contract simulator endpoint."""
    return _simulate_cap(req, db)


@router.post("/simulator/cap", response_model=SimulatorResponse, deprecated=True)
def simulate_cap(req: SimulatorRequest, db: DB = None):
    """Deprecated compatibility alias for POST /simulate/contract."""
    return _simulate_cap(req, db)


# --- Scenario comparison -----------------------------------------------------

class CompareRequest(BaseModel):
    scenarios: list[SimulatorRequest] = Field(
        ..., min_length=2, max_length=5, description="Two to five proposed contracts to compare."
    )


class ScenarioDelta(BaseModel):
    label: str                       # e.g. "5yr @ 30.0% of cap"
    total_cap_hit_usd: int           # sum of guaranteed + option years (face value)
    guaranteed_cap_hit_usd: int      # sum of guaranteed years only
    value_gap_pct: float | None      # positive = bargain
    apron_tier_after: str | None     # if a team overlay was requested


class CompareResponse(BaseModel):
    scenarios: list[SimulatorResponse]
    deltas: list[ScenarioDelta]
    best_value_index: int | None     # largest value_gap_pct (most bargain / least overpay)
    cheapest_index: int              # smallest total face value
    note: str


def _scenario_label(s: SimulatorResponse) -> str:
    return f"{len(s.years)}yr @ {s.proposed_aav_pct:.1f}% of cap"


@router.post("/simulate/compare", response_model=CompareResponse)
def compare_contracts(req: CompareRequest, db: DB = None):
    """Run several proposed contracts for side-by-side what-if comparison.

    Each scenario is simulated independently (same rules as /simulate/contract, including
    an optional per-scenario team apron overlay). Returns per-scenario face-value totals,
    the model's value gap, and convenience picks (best value, cheapest).
    """
    sims = [SimulatorResponse(**_simulate_cap(s, db)) for s in req.scenarios]

    deltas: list[ScenarioDelta] = []
    for s in sims:
        total = sum(y.cap_hit_usd for y in s.years)
        guaranteed = sum(y.cap_hit_usd for y in s.years if y.is_guaranteed)
        deltas.append(
            ScenarioDelta(
                label=_scenario_label(s),
                total_cap_hit_usd=total,
                guaranteed_cap_hit_usd=guaranteed,
                value_gap_pct=s.value_gap_pct,
                apron_tier_after=s.apron_outlook.tier_after if s.apron_outlook else None,
            )
        )

    valued = [(i, d.value_gap_pct) for i, d in enumerate(deltas) if d.value_gap_pct is not None]
    best_value_index = max(valued, key=lambda t: t[1])[0] if valued else None
    cheapest_index = min(range(len(deltas)), key=lambda i: deltas[i].total_cap_hit_usd)

    return CompareResponse(
        scenarios=sims,
        deltas=deltas,
        best_value_index=best_value_index,
        cheapest_index=cheapest_index,
        note=(
            "Face-value totals sum every year including options (options are not exercised "
            "automatically). 'Best value' is the largest model value gap; it may not be the cheapest."
        ),
    )
