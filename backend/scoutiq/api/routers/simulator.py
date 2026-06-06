"""POST /simulator/cap — What-If Contract & Cap Simulator (signature feature)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from scoutiq.api.cap_simulator import SeasonCapData, simulate
from scoutiq.api.deps import DB
from scoutiq.model.predict import predict_for_player
from scoutiq.models import CapConstants, Player, PlayerSeason

router = APIRouter(prefix="/simulator", tags=["simulator"])

# Most recent season with full model features — used as the valuation base
VALUATION_SEASON = "2024-25"


class SimulatorRequest(BaseModel):
    player_id: int
    aav_pct: float = Field(..., gt=0, le=100, description="Proposed AAV as % of salary cap (e.g. 20.0)")
    years: int = Field(..., ge=1, le=5, description="Contract length in years")
    guaranteed_years: int = Field(0, ge=0, description="Number of fully guaranteed years")
    player_option_years: int = Field(0, ge=0, description="Player option years (after guaranteed)")
    team_option_years: int = Field(0, ge=0, description="Team option years (at end of contract)")
    start_season: str = Field("2025-26", description="First season of the contract (YYYY-YY)")
    valuation_season: str | None = Field(None, description="Season to use for model valuation (defaults to latest)")


@router.post("/cap")
def simulate_cap(req: SimulatorRequest, db: DB = None):
    """Simulate a proposed contract against the cap and the valuation model.

    Returns year-by-year cap hits, apron thresholds, and the model's production-implied
    value gap (positive = player being underpaid relative to production).

    Cap constants for future seasons beyond the DB are projected at 4.5%/yr growth.
    """
    player = db.get(Player, req.player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {req.player_id} not found.")

    # validate option/guaranteed totals
    if req.guaranteed_years + req.player_option_years + req.team_option_years > req.years:
        raise HTTPException(
            status_code=422,
            detail="guaranteed_years + player_option_years + team_option_years cannot exceed years.",
        )

    # fetch all cap constants for season projection
    cap_rows = db.scalars(select(CapConstants)).all()
    cap_by_season: dict[str, SeasonCapData] = {}
    for row in cap_rows:
        # first_apron / second_apron may be null before 2023-24 CBA; use proxies
        first_apron = row.first_apron or (int(row.tax_line * 1.032) if row.tax_line else 0)
        second_apron = row.second_apron or (int(row.tax_line * 1.097) if row.tax_line else 0)
        cap_by_season[row.season] = SeasonCapData(
            season=row.season,
            salary_cap=row.salary_cap or 0,
            tax_line=row.tax_line or 0,
            first_apron=first_apron,
            second_apron=second_apron,
        )

    if not cap_by_season:
        raise HTTPException(status_code=503, detail="No cap constants found in DB.")

    # run valuation model on player's most recent stats
    val_season = req.valuation_season or VALUATION_SEASON
    valuation: dict | None = None

    ps_check = db.scalars(
        select(PlayerSeason).where(
            PlayerSeason.player_id == req.player_id,
            PlayerSeason.season == val_season,
        )
    ).first()

    if ps_check is not None:
        try:
            valuation = predict_for_player(req.player_id, val_season, db)
        except (LookupError, FileNotFoundError):
            valuation = None

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

    # convert dataclass to dict (JSON-serialisable)
    d = asdict(result)
    d["valuation_season"] = val_season
    d["disclaimer"] = (
        "Cap simulation uses a simplified CBA subset. "
        "Bird rights, MLE/BAE, repeater tax, and traded-player exceptions are not modeled."
    )
    return d
