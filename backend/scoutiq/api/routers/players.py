"""GET /players/{player_id}/valuation — production-implied value for a player's most recent season."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from scoutiq.api.deps import DB
from scoutiq.model.predict import predict_for_player
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason

router = APIRouter(prefix="/players", tags=["players"])

# The most recent completed season for which we have full stats.
# Update each offseason after the ETL runs for the new season.
LATEST_SEASON = "2024-25"


@router.get("/{player_id}/valuation")
def get_valuation(player_id: int, season: str | None = None, db: DB = None):
    """Return production-implied value and salary gap for a player.

    - `season` defaults to the most recent season with stats.
    - `value_pct` is what production says the player is worth (% of cap).
    - `actual_pct` is what they were actually paid (% of cap).
    - `gap_pct` = value_pct - actual_pct  (positive → underpaid, negative → overpaid).
    - `lo_pct` / `hi_pct` are the 80% conformal prediction interval bounds.
    """
    target_season = season or LATEST_SEASON

    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    try:
        prediction = predict_for_player(player_id, target_season, db)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail=f"No stats for player_id={player_id} in season {target_season}.",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # realized salary for this season (if known)
    salary_row = db.scalars(
        select(PlayerSalary).where(
            PlayerSalary.player_id == player_id,
            PlayerSalary.season == target_season,
        )
    ).first()

    cap_row = db.get(CapConstants, target_season)
    salary_cap = cap_row.salary_cap if cap_row else None

    actual_usd = salary_row.salary if salary_row else None
    actual_pct = round(actual_usd / salary_cap * 100, 2) if (actual_usd and salary_cap) else None
    value_pct = prediction["value_pct"]
    gap_pct = round(value_pct - actual_pct, 2) if actual_pct is not None else None

    return {
        "player_id": player_id,
        "player_name": player.full_name,
        "position": player.position,
        "season": target_season,
        "value_pct": value_pct,
        "lo_pct": prediction["lo_pct"],
        "hi_pct": prediction["hi_pct"],
        "actual_pct": actual_pct,
        "actual_usd": actual_usd,
        "gap_pct": gap_pct,
        "salary_cap": salary_cap,
        "value_usd": int(value_pct / 100 * salary_cap) if salary_cap else None,
        "model_version": prediction["model_version"],
        "features": prediction.get("features"),
    }
