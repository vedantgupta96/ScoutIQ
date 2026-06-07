"""Server-side player headshot proxy with disk cache.

Browsers can be flaky when loading NBA CDN images directly, so the UI asks our
API for player headshots. We cache successful images and short-circuit repeated
misses so historical players do not create a CDN request on every page load.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from scoutiq.config import settings

router = APIRouter(prefix="/players", tags=["players"])

CACHE_DIR = settings.RAW_DIR / "headshots"
CDN_URL = "https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
HEADERS = {"User-Agent": "ScoutIQ/0.1 (personal portfolio research; contact via github)"}
SUCCESS_CACHE_SECONDS = 604_800  # 7 days
MISS_CACHE_SECONDS = 86_400  # 1 day


def _miss_is_fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < MISS_CACHE_SECONDS


def _raise_missing() -> None:
    raise HTTPException(
        status_code=404,
        detail="no headshot available",
        headers={"Cache-Control": f"public, max-age={MISS_CACHE_SECONDS}"},
    )


@router.get("/{player_id}/headshot")
def headshot(player_id: int) -> FileResponse:
    """Return the player's NBA headshot (cached), or 404 if none exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    image_path = CACHE_DIR / f"{player_id}.png"
    miss_path = CACHE_DIR / f"{player_id}.missing"

    if image_path.exists():
        return FileResponse(
            image_path,
            media_type="image/png",
            headers={"Cache-Control": f"public, max-age={SUCCESS_CACHE_SECONDS}"},
        )

    if _miss_is_fresh(miss_path):
        _raise_missing()

    try:
        resp = requests.get(CDN_URL.format(pid=player_id), headers=HEADERS, timeout=8)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail="headshot fetch failed") from e

    content_type = resp.headers.get("content-type", "").lower()
    if resp.status_code != 200 or not resp.content or not content_type.startswith("image/"):
        miss_path.touch()
        _raise_missing()

    image_path.write_bytes(resp.content)
    if miss_path.exists():
        miss_path.unlink()

    return FileResponse(
        image_path,
        media_type="image/png",
        headers={"Cache-Control": f"public, max-age={SUCCESS_CACHE_SECONDS}"},
    )
