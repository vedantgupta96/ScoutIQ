from fastapi import APIRouter

from scoutiq.api.season import LATEST_SEASON

router = APIRouter()


@router.get("/health")
def health() -> dict:
    # current_season is the single source of truth for the UI's season label,
    # so the frontend never hardcodes (and drifts from) the loaded season.
    return {"status": "ok", "service": "scoutiq-api", "current_season": LATEST_SEASON}
