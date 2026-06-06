"""Spotrac contract ETL — load forward contract structure into `contracts` + `contract_years`.

Spotrac is the riskiest part of the pipeline: they don't provide an API, the HTML changes
without notice, and aggressive scraping triggers bot-detection. Mitigations:
  - Per-player disk caching (same pattern as bbref.py): only hit the network once per player.
  - Rate-limiting: SPOTRAC_DELAY_SECONDS between requests.
  - Graceful per-player failure: one bad page does not abort the run.
  - Cache TTL: re-fetch if cached HTML is older than CACHE_TTL_DAYS days (contracts change).

Spotrac URL pattern: https://www.spotrac.com/nba/player/<slug>/contract/

The scraper parses the contract summary table and the year-by-year breakdown table.
Run after the BBRef ETL so player_xref slugs are populated (Spotrac slugs differ from BBRef;
we derive them from the player name, not the crosswalk).

Usage:
    python -m scoutiq.etl.load_contracts             # all players with verified BBRef crosswalk
    python -m scoutiq.etl.load_contracts --limit 50  # test run on 50 players
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import Contract, ContractYear, Player, PlayerXref

logger = logging.getLogger(__name__)

SPOTRAC_DELAY_SECONDS = 4.0   # be polite; Spotrac rate-limits aggressively
CACHE_TTL_DAYS = 7            # re-fetch contract pages older than this (contracts can be amended)
CACHE_DIR = settings.RAW_DIR / "spotrac"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Slug derivation (Spotrac uses a different slug format than BBRef)
# ---------------------------------------------------------------------------

def spotrac_slug(full_name: str) -> str:
    """'LeBron James' -> 'lebron-james'  (Spotrac URL slug)."""
    name = full_name.lower()
    # drop suffixes that Spotrac doesn't use
    name = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", "", name)
    name = re.sub(r"[^a-z0-9\s]", "", name)   # drop accents / punctuation
    name = re.sub(r"\s+", "-", name.strip())
    return name


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------

def _cache_path(slug: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{slug}.html"


def _cache_stale(path: Path) -> bool:
    if not path.exists():
        return True
    age_days = (time.time() - path.stat().st_mtime) / 86_400
    return age_days > CACHE_TTL_DAYS


def fetch_contract_html(slug: str) -> str | None:
    """Return Spotrac contract-page HTML, using disk cache.  Returns None on 404/failure."""
    path = _cache_path(slug)
    if not _cache_stale(path):
        return path.read_text(encoding="utf-8")

    url = f"https://www.spotrac.com/nba/player/{slug}/contract/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code == 404:
            logger.debug("404: %s", url)
            return None
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("fetch failed for %s: %s", slug, e)
        return None

    html = resp.text
    path.write_text(html, encoding="utf-8")
    time.sleep(SPOTRAC_DELAY_SECONDS)
    return html


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _parse_dollars(text: str) -> int | None:
    """'$142,123,456' -> 142123456.  Returns None if not parseable."""
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _parse_pct(text: str) -> float | None:
    """'18.50%' -> 0.1850.  Returns None if not parseable."""
    m = re.search(r"[\d.]+", text)
    return round(float(m.group()) / 100, 6) if m else None


def _season_from_year_range(text: str) -> str | None:
    """'2024-25' or '2024-2025' -> '2024-25'."""
    m = re.search(r"(20\d{2})[–\-](20)?(\d{2})", text)
    if not m:
        return None
    y1 = m.group(1)
    y2 = m.group(3)
    return f"{y1}-{y2}"


def parse_contract(html: str) -> dict | None:
    """Parse Spotrac contract page → dict with keys: season_start, years, total_value, year_rows.

    year_rows is a list of dicts: {season, aav, cap_pct, is_guaranteed, is_player_option, is_team_option}
    Returns None if the page doesn't contain a parseable contract.
    """
    soup = BeautifulSoup(html, "html5lib")

    # --- locate the year-by-year table ---
    # Spotrac renders a <table> with class "contract" or similar; the structure changes
    # periodically, so we look for the table containing year-range cells.
    tables = soup.find_all("table")
    year_table = None
    for tbl in tables:
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if any(re.search(r"20\d{2}", h) for h in headers) or any("Base Salary" in h for h in headers):
            year_table = tbl
            break

    if year_table is None:
        logger.debug("No contract table found in HTML")
        return None

    rows = year_table.find_all("tr")
    year_rows = []
    total_value = 0

    for row in rows[1:]:  # skip header row
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        # first cell: season year range
        season = _season_from_year_range(cells[0].get_text(strip=True))
        if not season:
            continue

        # look for dollar amount (base salary) in subsequent cells
        aav = None
        cap_pct = None
        for cell in cells[1:]:
            txt = cell.get_text(strip=True)
            if "$" in txt and aav is None:
                aav = _parse_dollars(txt)
            if "%" in txt and cap_pct is None:
                cap_pct = _parse_pct(txt)

        # option detection from row class or cell text
        row_classes = " ".join(row.get("class", []))
        cell_texts = " ".join(c.get_text(strip=True) for c in cells).lower()
        is_player_option = "player option" in cell_texts or "po" in row_classes.lower()
        is_team_option = "team option" in cell_texts or "to" in row_classes.lower()
        is_guaranteed = not is_player_option and not is_team_option

        year_rows.append({
            "season": season,
            "aav": aav,
            "cap_pct": cap_pct,
            "is_guaranteed": is_guaranteed,
            "is_player_option": is_player_option,
            "is_team_option": is_team_option,
        })
        if aav:
            total_value += aav

    if not year_rows:
        return None

    year_rows.sort(key=lambda r: r["season"])
    return {
        "season_start": year_rows[0]["season"],
        "years": len(year_rows),
        "total_value": total_value or None,
        "year_rows": year_rows,
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def upsert_contract(player_id: int, parsed: dict, session) -> None:
    """Upsert a parsed contract into contracts + contract_years."""
    now = datetime.now(tz=timezone.utc)

    stmt = (
        pg_insert(Contract)
        .values(
            player_id=player_id,
            season_start=parsed["season_start"],
            years=parsed["years"],
            total_value=parsed["total_value"],
            source="spotrac",
            scraped_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_contract_player_start",
            set_={"years": parsed["years"], "total_value": parsed["total_value"], "scraped_at": now},
        )
        .returning(Contract.id)
    )
    contract_id = session.execute(stmt).scalar_one()

    for yr in parsed["year_rows"]:
        yr_stmt = (
            pg_insert(ContractYear)
            .values(
                contract_id=contract_id,
                season=yr["season"],
                aav=yr["aav"],
                cap_pct=yr["cap_pct"],
                is_guaranteed=yr["is_guaranteed"],
                is_player_option=yr["is_player_option"],
                is_team_option=yr["is_team_option"],
            )
            .on_conflict_do_update(
                constraint="uq_contract_year",
                set_={
                    "aav": yr["aav"],
                    "cap_pct": yr["cap_pct"],
                    "is_guaranteed": yr["is_guaranteed"],
                    "is_player_option": yr["is_player_option"],
                    "is_team_option": yr["is_team_option"],
                },
            )
        )
        session.execute(yr_stmt)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def load_all(limit: int | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with get_session() as session:
        query = select(Player.player_id, Player.full_name)
        rows = session.execute(query).all()

    players = [(r.player_id, r.full_name) for r in rows]
    if limit:
        players = players[:limit]

    ok = skipped = errors = 0
    for player_id, full_name in players:
        slug = spotrac_slug(full_name)
        try:
            html = fetch_contract_html(slug)
            if html is None:
                logger.debug("No page for %s (%s)", full_name, slug)
                skipped += 1
                continue

            parsed = parse_contract(html)
            if parsed is None:
                logger.debug("No contract table for %s", full_name)
                skipped += 1
                continue

            with get_session() as session:
                upsert_contract(player_id, parsed, session)

            logger.info("✓ %s — %d yr / $%s", full_name, parsed["years"],
                        f"{parsed['total_value']:,}" if parsed["total_value"] else "?")
            ok += 1
        except Exception as e:
            logger.warning("✗ %s: %s", full_name, e)
            errors += 1

    logger.info("Done. ok=%d  skipped=%d  errors=%d", ok, skipped, errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max players to process")
    args = parser.parse_args()
    load_all(limit=args.limit)
