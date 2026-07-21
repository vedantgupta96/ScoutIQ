"""Spotrac contract ETL — load forward contract structure into `contracts` + `contract_years`.

Two-step scrape:
  1. 30 team contract pages  → player list with Spotrac IDs and summary (AAV, years, total value)
  2. Individual player pages  → year-by-year cap hits + option/guarantee status

URL patterns:
  Team:   https://www.spotrac.com/nba/{team-slug}/contracts/
  Player: https://www.spotrac.com/nba/player/_/id/{spotrac_id}/{name-slug}

Mitigations against Spotrac bot-detection:
  - Disk cache with TTL (re-fetch after CACHE_TTL_DAYS; contracts can be amended)
  - Rate-limiting: SPOTRAC_DELAY_SECONDS between requests
  - Per-player fault tolerance: one bad page never aborts the run

Name-matching to our DB: normalize → exact match; fallback → word-overlap score.

Usage:
    python -m scoutiq.etl.load_contracts            # all active-roster players
    python -m scoutiq.etl.load_contracts --limit 20 # test run
    python -m scoutiq.etl.load_contracts --teams denver-nuggets boston-celtics
"""
from __future__ import annotations

import argparse
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import Contract, ContractYear, Player

logger = logging.getLogger(__name__)

SPOTRAC_DELAY_SECONDS = 3.5
CACHE_TTL_DAYS = 7
CACHE_DIR = settings.RAW_DIR / "spotrac"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FIRST_NAME_ALIASES = {
    "bones": "nahshon",
    "cam": "cameron",
    "herb": "herbert",
    "nic": "nicolas",
    "ron": "ronald",
    "svi": "sviatoslav",
}

NBA_TEAM_SLUGS = [
    "atlanta-hawks", "boston-celtics", "brooklyn-nets", "charlotte-hornets",
    "chicago-bulls", "cleveland-cavaliers", "dallas-mavericks", "denver-nuggets",
    "detroit-pistons", "golden-state-warriors", "houston-rockets", "indiana-pacers",
    "la-clippers", "los-angeles-lakers", "memphis-grizzlies", "miami-heat",
    "milwaukee-bucks", "minnesota-timberwolves", "new-orleans-pelicans", "new-york-knicks",
    "oklahoma-city-thunder", "orlando-magic", "philadelphia-76ers", "phoenix-suns",
    "portland-trail-blazers", "sacramento-kings", "san-antonio-spurs", "toronto-raptors",
    "utah-jazz", "washington-wizards",
]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9_-]", "_", key)
    return CACHE_DIR / f"{safe}.html"


def _cache_stale(path: Path) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) / 86_400 > CACHE_TTL_DAYS


def _get(url: str, cache_key: str) -> str | None:
    path = _cache_path(cache_key)
    if not _cache_stale(path):
        return path.read_text(encoding="utf-8")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("fetch failed %s: %s", url, e)
        return None
    path.write_text(resp.text, encoding="utf-8")
    time.sleep(SPOTRAC_DELAY_SECONDS)
    return resp.text


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_dollars(text: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _parse_pct(text: str) -> float | None:
    m = re.search(r"[\d.]+", text)
    return round(float(m.group()) / 100, 6) if m else None


def _normalize(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace, drop Jr/Sr/II/III."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    n = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", "", n)
    n = re.sub(r"[^a-z\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    parts = n.split()
    if parts and parts[0] in FIRST_NAME_ALIASES:
        parts[0] = FIRST_NAME_ALIASES[parts[0]]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Step 1 — scrape team page → player list
# ---------------------------------------------------------------------------

def scrape_team(team_slug: str) -> list[dict]:
    """Return list of {full_name, spotrac_id, name_slug, years, total_value, aav, start, end}."""
    url = f"https://www.spotrac.com/nba/{team_slug}/contracts/"
    html = _get(url, f"team_{team_slug}")
    if not html:
        logger.warning("no page for team %s", team_slug)
        return []

    soup = BeautifulSoup(html, "html5lib")
    table = soup.find("table")
    if not table:
        logger.warning("no table on %s", team_slug)
        return []

    players = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 8:
            continue

        # player link → spotrac_id + name slug
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        href = link_tag["href"]
        m = re.search(r"/id/(\d+)/([^/]+)", href)
        if not m:
            continue
        spotrac_id = m.group(1)
        name_slug = m.group(2)

        # Spotrac table cells include a duplicated sort key, e.g.
        # "Anunoby OG Anunoby"; the player link text is the canonical name.
        full_name = link_tag.get_text(" ", strip=True)
        if not full_name:
            raw = cells[0].get_text(strip=True)
            full_name_m = re.search(
                r"([A-Z][a-zéàâêîôùûäëïöüñ]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-zéàâêîôùûäëïöüñ]+.*)",
                raw,
            )
            full_name = full_name_m.group(1).strip() if full_name_m else raw

        years_txt = cells[7].get_text(strip=True) if len(cells) > 7 else ""
        years = int(years_txt) if years_txt.isdigit() else None

        total_value = _parse_dollars(cells[8].get_text(strip=True)) if len(cells) > 8 else None
        aav = _parse_dollars(cells[9].get_text(strip=True)) if len(cells) > 9 else None

        start_txt = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        end_txt = cells[6].get_text(strip=True) if len(cells) > 6 else ""

        if not spotrac_id or not years:
            continue

        # Spotrac tags contract type in a designation cell (e.g. "Free Agent Two-Way");
        # two-way players do not count against the 15-man standard roster limit.
        is_two_way = "two-way" in row.get_text(" ", strip=True).lower()

        players.append({
            "full_name": full_name,
            "spotrac_id": spotrac_id,
            "name_slug": name_slug,
            "years": years,
            "total_value": total_value,
            "aav": aav,
            "start": start_txt,   # calendar year, e.g. '2023'
            "end": end_txt,
            "is_two_way": is_two_way,
        })

    return players


# ---------------------------------------------------------------------------
# Step 2 — scrape individual player page → year-by-year
# ---------------------------------------------------------------------------

def _parse_contract_table(table) -> list[dict]:
    """Parse one Spotrac cap-hit table into year rows, or [] if it isn't one.

    Columns vary by page: some include a "Status" column, some do not, which
    shifts Cap Hit / Cap % by one. Locate columns by header text instead of
    fixed indices, or the dollar/percent cells silently misalign.
    """
    header_row = table.find("tr")
    if header_row is None:
        return []
    headers = [c.get_text(" ", strip=True).lower() for c in header_row.find_all(["td", "th"])]

    def _col(prefix: str) -> int | None:
        return next((i for i, h in enumerate(headers) if h.startswith(prefix)), None)

    cap_hit_idx = _col("cap hit")
    cap_pct_idx = _col("cap %")
    cash_annual_idx = _col("cash annual")
    cash_guaranteed_idx = _col("cash guaranteed")
    status_idx = _col("status")
    if cap_hit_idx is None or cap_pct_idx is None:
        return []  # not a cap-hit table (base-salary / cash tables share the page)

    rows = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= cap_pct_idx:
            continue  # short rows (e.g. future UFA years) have no cap figures

        season = cells[0].get_text(strip=True)   # '2024-25'
        # skip non-season rows (UFA, RFA, etc.) — must match YYYY-YY
        if not re.match(r"^\d{4}-\d{2}$", season):
            continue

        status = cells[status_idx].get_text(strip=True).lower() if status_idx is not None else ""
        # skip free-agent / post-contract rows
        if status in ("ufa", "rfa", "two-way"):
            continue

        is_player_option = "player" in status
        is_team_option = "team" in status
        cap_hit = _parse_dollars(cells[cap_hit_idx].get_text(strip=True))
        if cap_hit is None:
            # Two-way / exhibit-style rows often have no cap hit but do expose
            # cash columns. Keep that amount so coverage audits classify them
            # as below-floor contracts instead of unexplained parser misses.
            for fallback_idx in (cash_annual_idx, cash_guaranteed_idx):
                if fallback_idx is not None and len(cells) > fallback_idx:
                    cap_hit = _parse_dollars(cells[fallback_idx].get_text(strip=True))
                    if cap_hit is not None:
                        break
        rows.append({
            "season": season,
            "aav": cap_hit,
            "cap_pct": _parse_pct(cells[cap_pct_idx].get_text(strip=True)),
            "is_guaranteed": not is_player_option and not is_team_option,
            "is_player_option": is_player_option,
            "is_team_option": is_team_option,
        })
    return rows


def scrape_player_contract(spotrac_id: str, name_slug: str) -> list[dict] | None:
    """Return list of {season, aav, cap_pct, is_guaranteed, is_player_option, is_team_option}.

    A recently-extended player's page leads with the extension table while the
    current contract (the years we actually need, e.g. 2025-26) sits in a later
    cap-hit table. Merge across every cap-hit table, keeping the first non-null
    cap hit per season, so those current years aren't dropped.
    """
    url = f"https://www.spotrac.com/nba/player/_/id/{spotrac_id}/{name_slug}"
    html = _get(url, f"player_{spotrac_id}")
    if not html:
        return None

    soup = BeautifulSoup(html, "html5lib")
    by_season: dict[str, dict] = {}
    for table in soup.find_all("table"):
        for row in _parse_contract_table(table):
            existing = by_season.get(row["season"])
            if existing is None or (existing["aav"] is None and row["aav"] is not None):
                by_season[row["season"]] = row

    rows = [by_season[s] for s in sorted(by_season)]
    return rows if rows else None


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def _build_name_index(session) -> dict[str, int]:
    """normalized_name -> player_id from our DB."""
    rows = session.execute(select(Player.player_id, Player.full_name)).all()
    return {_normalize(r.full_name): r.player_id for r in rows}


def _match_player(full_name: str, index: dict[str, int]) -> int | None:
    norm = _normalize(full_name)
    if norm in index:
        return index[norm]
    # word-overlap fallback: e.g. 'nicolas claxton' vs 'nic claxton'
    words = set(norm.split())
    best_id, best_score = None, 0
    for db_name, pid in index.items():
        db_words = set(db_name.split())
        if not db_words:
            continue
        score = len(words & db_words) / max(len(words), len(db_words))
        if score > best_score and score >= 0.8:
            best_score, best_id = score, pid
    return best_id


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _start_season(start_year: str, years_data: list[dict]) -> str:
    """Derive season_start from first year row or start_year string."""
    if years_data:
        return years_data[0]["season"]
    y = re.sub(r"[^0-9]", "", start_year)[:4]
    if len(y) == 4:
        y2 = str(int(y) + 1)[2:]
        return f"{y}-{y2}"
    return "2024-25"


def upsert_contract(player_id: int, summary: dict, year_rows: list[dict], session) -> None:
    now = datetime.now(tz=timezone.utc)
    season_start = _start_season(summary.get("start", ""), year_rows)
    years = len(year_rows) or summary.get("years", 1)

    # Clean-replace this player's contract. The dedup key is (player_id, season_start),
    # but a re-scrape can change season_start when the parser improves (e.g. the first
    # cap-hit table shifts), which would upsert into a *new* row and leave the old one
    # as a stale duplicate. Delete any existing contract(s) for the player first so a
    # re-scrape always yields exactly one current contract.
    existing_ids = session.execute(
        select(Contract.id).where(Contract.player_id == player_id)
    ).scalars().all()
    if existing_ids:
        session.execute(delete(ContractYear).where(ContractYear.contract_id.in_(existing_ids)))
        session.execute(delete(Contract).where(Contract.id.in_(existing_ids)))

    contract_id = session.execute(
        pg_insert(Contract)
        .values(
            player_id=player_id,
            season_start=season_start,
            years=years,
            total_value=summary.get("total_value"),
            source="spotrac",
            scraped_at=now,
        )
        .returning(Contract.id)
    ).scalar_one()

    for yr in year_rows:
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

def load_all(team_slugs: list[str] | None = None, limit: int | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    teams = team_slugs or NBA_TEAM_SLUGS

    # build name index once
    with get_session() as session:
        name_index = _build_name_index(session)
    logger.info("DB index: %d players", len(name_index))

    # collect all players from team pages (deduplicated by spotrac_id)
    seen_ids: set[str] = set()
    all_players: list[dict] = []
    for team_slug in teams:
        logger.info("scraping team: %s", team_slug)
        players = scrape_team(team_slug)
        for p in players:
            if p["spotrac_id"] not in seen_ids:
                seen_ids.add(p["spotrac_id"])
                all_players.append(p)
        logger.info("  → %d unique players so far", len(all_players))

    if limit:
        all_players = all_players[:limit]

    ok = skipped = errors = no_match = 0
    for p in all_players:
        player_id = _match_player(p["full_name"], name_index)
        if player_id is None:
            logger.debug("no DB match for '%s'", p["full_name"])
            no_match += 1
            continue
        try:
            year_rows = scrape_player_contract(p["spotrac_id"], p["name_slug"])
            if not year_rows:
                logger.debug("no year data for %s", p["full_name"])
                skipped += 1
                continue
            with get_session() as session:
                upsert_contract(player_id, p, year_rows, session)
            logger.info(
                "✓ %s — %d yr  $%s AAV  [%s]",
                p["full_name"],
                len(year_rows),
                f"{p['aav']:,}" if p["aav"] else "?",
                ", ".join(f"{yr['season']}={'G' if yr['is_guaranteed'] else 'PO' if yr['is_player_option'] else 'TO'}"
                          for yr in year_rows),
            )
            ok += 1
        except Exception as e:
            logger.warning("✗ %s: %s", p["full_name"], e)
            errors += 1

    logger.info("Done. ok=%d  skipped=%d  no_match=%d  errors=%d", ok, skipped, no_match, errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--teams", nargs="+", default=None, metavar="TEAM_SLUG")
    args = parser.parse_args()
    load_all(team_slugs=args.teams, limit=args.limit)
