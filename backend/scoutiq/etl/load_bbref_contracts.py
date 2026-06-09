"""Load current Basketball-Reference contract rows as a fallback.

Spotrac team pages are the primary forward-contract source because they expose
options and richer contract structure. BBRef's current contracts table is useful
for edge cases that are omitted from active Spotrac team pages, such as inactive
or recently waived/traded players. This loader only inserts rows for players
with no existing contract, so it cannot replace richer Spotrac data.

Usage:
    python -m scoutiq.etl.load_bbref_contracts
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl.load_contracts import _build_name_index, _match_player
from scoutiq.models import Contract, ContractYear

logger = logging.getLogger(__name__)

BBREF_CONTRACTS_URL = "https://www.basketball-reference.com/contracts/players.html"
CACHE_TTL_DAYS = 2
CACHE_PATH = settings.RAW_DIR / "bbref_contracts_players.html"
HEADERS = {"User-Agent": "ScoutIQ data audit (contact: local-dev)"}
SEASON_RE = re.compile(r"^\d{4}-\d{2}$")


def _cache_stale(path: Path) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) / 86_400 > CACHE_TTL_DAYS


def _get_contracts_html(force: bool = False) -> str:
    settings.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not force and not _cache_stale(CACHE_PATH):
        return CACHE_PATH.read_text(encoding="utf-8")

    resp = requests.get(BBREF_CONTRACTS_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    html = resp.text
    CACHE_PATH.write_text(html, encoding="utf-8")
    return html


def _parse_dollars(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def parse_contract_rows(html: str, season: str) -> list[dict]:
    """Return [{full_name, team, years:[{season, aav}]}] from BBRef contracts."""
    tables = pd.read_html(StringIO(html))
    if not tables:
        return []
    df = tables[0]

    def _column(label: str):
        for col in df.columns:
            if isinstance(col, tuple) and col[-1] == label:
                return col
            if col == label:
                return col
        return None

    player_col = _column("Player")
    team_col = _column("Tm")
    if player_col is None:
        return []

    season_cols = [
        col for col in df.columns
        if (isinstance(col, tuple) and SEASON_RE.match(str(col[-1]))) or SEASON_RE.match(str(col))
    ]
    rows: list[dict] = []
    for _, row in df.iterrows():
        full_name = str(row[player_col]).strip()
        if not full_name or full_name == "Player":
            continue

        years = []
        for col in season_cols:
            season_label = str(col[-1] if isinstance(col, tuple) else col)
            amount = _parse_dollars(row[col])
            if amount is not None:
                years.append({"season": season_label, "aav": amount})
        if not any(year["season"] == season for year in years):
            continue

        rows.append({
            "full_name": full_name,
            "team": str(row[team_col]).strip() if team_col is not None and not pd.isna(row[team_col]) else None,
            "years": years,
        })
    return rows


def _upsert_missing_contract(player_id: int, years: list[dict], session) -> bool:
    existing_id = session.scalar(select(Contract.id).where(Contract.player_id == player_id))
    if existing_id is not None:
        return False

    now = datetime.now(tz=timezone.utc)
    first_season = years[0]["season"]
    contract_id = session.execute(
        pg_insert(Contract)
        .values(
            player_id=player_id,
            season_start=first_season,
            years=len(years),
            total_value=sum(year["aav"] for year in years if year["aav"] is not None),
            source="bbref_contracts",
            scraped_at=now,
        )
        .returning(Contract.id)
    ).scalar_one()

    session.execute(delete(ContractYear).where(ContractYear.contract_id == contract_id))
    for year in years:
        session.execute(
            pg_insert(ContractYear)
            .values(
                contract_id=contract_id,
                season=year["season"],
                aav=year["aav"],
                cap_pct=None,
                is_guaranteed=True,
                is_player_option=False,
                is_team_option=False,
            )
            .on_conflict_do_update(
                constraint="uq_contract_year",
                set_={"aav": year["aav"]},
            )
        )
    return True


def load(season: str = settings.CURRENT_SEASON, force: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rows = parse_contract_rows(_get_contracts_html(force=force), season)
    with get_session() as session:
        name_index = _build_name_index(session)

    inserted = no_match = existing = 0
    for row in rows:
        player_id = _match_player(row["full_name"], name_index)
        if player_id is None:
            no_match += 1
            continue
        with get_session() as session:
            if _upsert_missing_contract(player_id, row["years"], session):
                inserted += 1
                logger.info("inserted BBRef fallback contract: %s", row["full_name"])
            else:
                existing += 1
    logger.info("Done. inserted=%d existing=%d no_match=%d", inserted, existing, no_match)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=settings.CURRENT_SEASON)
    parser.add_argument("--force", action="store_true", help="refresh the BBRef contracts cache")
    args = parser.parse_args()
    load(season=args.season, force=args.force)
