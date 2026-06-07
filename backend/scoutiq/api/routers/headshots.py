"""Server-side player headshot proxy + disk cache.

Browsers can't reliably load cdn.nba.com images directly (cross-origin HTTP/2
quirks vary by network), so we fetch each headshot once server-side, cache it to
disk, and serve it from our own origin. A missing/404 headshot returns 404 and the
UI falls back to initials.
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from scoutiq.config import settings

router = APIRouter(prefix="/players", tags=["players"])

CACHE_DIR = settings.RAW_DIR / "headshots"
CDN_URL = "https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
HEADERS = {"User-Agent": "ScoutIQ/0.1 (personal portfolio research; contact via github)"}


@router.get("/{player_id}/headshot")
def headshot(player_id: int) -> FileResponse:
    """Return the player's NBA headshot (cached), or 404 if none exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{player_id}.png"

    if not path.exists():
        try:
            resp = requests.get(CDN_URL.format(pid=player_id), headers=HEADERS, timeout=8)
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail="headshot fetch failed") from e
        if resp.status_code != 200 or not resp.content:
            raise HTTPException(status_code=404, detail="no headshot available")
        path.write_bytes(resp.content)

    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},  # 7 days
    )
