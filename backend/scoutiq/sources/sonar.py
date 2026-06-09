"""Perplexity Sonar adapter — fetch a cited, qualitative scouting narrative for one player.

This is the WORDS half of ScoutIQ's thesis: Sonar sources public scouting prose (strengths,
weaknesses, intangibles, fit) WITH citations. It is never used for stats, salary, or cap numbers —
those come from the deterministic nba_api / BBRef / Spotrac ETL.

Be a polite, cheap citizen: disk-cache each response by player+season so re-runs never re-bill the API.
The cache is the "cached Sonar corpus" — the offline backfill reads it; the live API never calls here.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from scoutiq.config import settings

CACHE_DIR = settings.RAW_DIR / "sonar"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
DELAY_SECONDS = 1.0  # politeness between live calls
_last_fetch_ts = 0.0

SYSTEM_PROMPT = (
    "You are an NBA scouting research assistant. Given a player, write a concise qualitative "
    "scouting report (4-8 sentences) covering on-court strengths, weaknesses, intangibles "
    "(leadership, work ethic, coachability, basketball IQ, discipline), athleticism, and team fit. "
    "Write prose only. Do NOT include statistics, salary, contract, or salary-cap figures — those are "
    "handled elsewhere. Base claims on reputable public reporting and cite your sources."
)


@dataclass(frozen=True)
class SonarReport:
    source_text: str
    citations: list[str]


def _cache_path(player_id: int, season: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_season = re.sub(r"[^0-9-]", "", season)
    return CACHE_DIR / f"{player_id}_{safe_season}.json"


def _user_prompt(player_name: str, season: str) -> str:
    return (
        f"Write a qualitative scouting report for {player_name} as of the {season} NBA season. "
        "Focus on playing style and intangibles. No numbers."
    )


def fetch_scout_report(
    player_id: int,
    player_name: str,
    season: str,
    *,
    use_cache: bool = True,
) -> SonarReport | None:
    """Return a cited scouting narrative for the player, or None on failure.

    Caches the parsed {source_text, citations} JSON to data/raw/sonar/{player_id}_{season}.json so
    re-runs are free and the corpus is reproducible.
    """
    global _last_fetch_ts
    cache = _cache_path(player_id, season)
    if use_cache and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return SonarReport(source_text=data["source_text"], citations=data.get("citations", []))

    api_key = settings.PERPLEXITY_API_KEY
    if not api_key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY is empty. Set it in backend/.env to run the Sonar corpus pull."
        )

    wait = DELAY_SECONDS - (time.time() - _last_fetch_ts)
    if wait > 0:
        time.sleep(wait)

    payload = {
        "model": settings.SONAR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(player_name, season)},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(
            PERPLEXITY_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=45,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None
    finally:
        _last_fetch_ts = time.time()

    body = resp.json()
    choices = body.get("choices") or []
    if not choices:
        return None
    source_text = (choices[0].get("message", {}).get("content") or "").strip()
    if not source_text:
        return None
    # Perplexity returns citations as a top-level list of URLs (newer responses may also embed
    # `search_results` with urls); prefer the flat `citations` list and fall back gracefully.
    citations = body.get("citations") or [
        r.get("url") for r in body.get("search_results", []) if r.get("url")
    ]
    citations = [c for c in citations if c]

    cache.write_text(
        json.dumps({"source_text": source_text, "citations": citations}, indent=2),
        encoding="utf-8",
    )
    return SonarReport(source_text=source_text, citations=citations)
