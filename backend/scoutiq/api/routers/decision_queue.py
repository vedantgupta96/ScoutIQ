"""GET /decision-queue — a team-specific, read-only prioritization view.

Thin HTTP wrapper: all ranking, banding, and verdict logic lives in the deep module
scoutiq.api.decision_queue. Per-item degradation (missing contract, missing valuation, missing
model artifact) is handled inside that module, so this endpoint only needs to turn an unknown
team into a 404 and an invalid or non-current season into a 422.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from scoutiq.api.decision_queue import build_decision_queue
from scoutiq.api.deps import DB
from scoutiq.api.season import is_valid_season

router = APIRouter(prefix="/decision-queue", tags=["decision-queue"])


class QueueItemModel(BaseModel):
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
    caution: str | None


class DecisionQueueResponse(BaseModel):
    team_id: int
    team_name: str | None
    season: str
    generated_from: str
    items: list[QueueItemModel]
    caveat: str
    model_unavailable: bool


@router.get("", response_model=DecisionQueueResponse)
def get_decision_queue(
    team_id: int = Query(...),
    season: str | None = Query(None, description="Season label, e.g. '2025-26'. Defaults to the latest loaded season."),
    db: DB = None,
):
    """A team's prioritized queue: pending options, extension calls, expiring contracts,
    the team's cap tier, and its single largest roster-need deficit."""
    if season is not None and not is_valid_season(season):
        raise HTTPException(status_code=422, detail="season must be a 'YYYY-YY' label, e.g. '2025-26'.")

    try:
        queue = build_decision_queue(db, team_id, season)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return DecisionQueueResponse(
        team_id=queue.team_id,
        team_name=queue.team_name,
        season=queue.season,
        generated_from=queue.generated_from,
        items=[QueueItemModel(**vars(item)) for item in queue.items],
        caveat=queue.caveat,
        model_unavailable=queue.model_unavailable,
    )
