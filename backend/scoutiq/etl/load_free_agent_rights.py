"""Load Spotrac free-agent status and team cap holds for an entering season.

Usage: python -m scoutiq.etl.load_free_agent_rights --year 2026 [--teams boston-celtics]
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.db import get_session
from scoutiq.etl.load_contracts import NBA_TEAM_SLUGS, _build_name_index, _get, _match_player, _parse_dollars
from scoutiq.models import FreeAgentRight, Team

logger = logging.getLogger(__name__)

TEAM_ABBREVIATIONS = dict(zip(NBA_TEAM_SLUGS, (
    "ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK "
    "OKC ORL PHI PHX POR SAC SAS TOR UTA WAS"
).split(), strict=True))


def entering_season(year: int) -> str:
    return f"{year}-{str(year + 1)[2:]}"


def _headers(table) -> list[str]:
    row = table.find("tr")
    if row is None:
        return []
    return [
        re.sub(r"\s+", " ", cell.get_text(" ", strip=True).lower()).strip()
        for cell in row.find_all(["th", "td"])
    ]


def _header_index(headers: list[str], *prefixes: str) -> int | None:
    return next(
        (i for i, header in enumerate(headers) if any(header.startswith(prefix) for prefix in prefixes)),
        None,
    )


def _player(cell) -> tuple[str, str] | None:
    link = cell.find("a", href=True)
    if not link:
        return None
    match = re.search(r"/id/(\d+)", link["href"])
    name = link.get_text(" ", strip=True)
    return (name, match.group(1)) if name and match else None


def _bird(value: str) -> str | None:
    value = value.lower().replace("_", "-")
    if "early" in value:
        return "early-bird"
    if "non-bird" in value or "non bird" in value:
        return "non-bird"
    if "two-way" in value or "two way" in value:
        return "two-way"
    if "bird" in value:
        return "bird"
    return None


def parse_free_agents(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html5lib")
    candidate_tables = []
    for table in soup.find_all("table"):
        headers = _headers(table)
        player_i = _header_index(headers, "player")
        type_i = _header_index(headers, "type")
        if player_i is None or type_i is None:
            continue
        heading = table.find_previous(["h1", "h2", "h3"])
        is_available = bool(heading and "available" in heading.get_text(" ", strip=True).lower())
        candidate_tables.append((is_available, table, headers, player_i, type_i))

    if not candidate_tables:
        return []
    _, table, headers, player_i, type_i = next(
        (candidate for candidate in candidate_tables if candidate[0]),
        candidate_tables[0],
    )
    rows: list[dict] = []
    prev_i = _header_index(headers, "prev aav")
    qo_i = _header_index(headers, "qo", "qualifying offer")
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(player_i, type_i):
            continue
        player = _player(cells[player_i])
        type_text = cells[type_i].get_text(" ", strip=True)
        status_match = re.search(r"\b(UFA|RFA)\b", type_text, re.I)
        if not player or not status_match:
            continue
        rows.append(
            {
                "full_name": player[0],
                "source_player_id": player[1],
                "fa_status": status_match.group(1).lower(),
                "bird_rights": _bird(type_text),
                "previous_aav_usd": (
                    _parse_dollars(cells[prev_i].get_text(" ", strip=True))
                    if prev_i is not None and len(cells) > prev_i
                    else None
                ),
                "qualifying_offer_usd": (
                    _parse_dollars(cells[qo_i].get_text(" ", strip=True))
                    if qo_i is not None and len(cells) > qo_i
                    else None
                ),
            }
        )
    return rows


def parse_cap_holds(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html5lib")
    heading = next(
        (
            heading
            for heading in soup.find_all("h2")
            if "cap hold" in heading.get_text(" ", strip=True).lower()
        ),
        None,
    )
    table = heading.find_next("table") if heading else None
    if not table:
        return []
    headers = _headers(table)
    player_i = _header_index(headers, "player")
    cap_i = _header_index(headers, "cap hit")
    if player_i is None or cap_i is None:
        return []
    rights_i = next(
        (i for i, header in enumerate(headers) if "rights" in header or header == "type"),
        len(headers) - 1,
    )
    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(player_i, cap_i):
            continue
        player = _player(cells[player_i])
        if not player:
            continue
        rows.append(
            {
                "full_name": player[0],
                "source_player_id": player[1],
                "cap_hold_usd": _parse_dollars(cells[cap_i].get_text(" ", strip=True)),
                "bird_rights": (
                    _bird(cells[rights_i].get_text(" ", strip=True))
                    if len(cells) > rights_i
                    else None
                ),
            }
        )
    return rows


def upsert_right(session, player_id: int, season: str, values: dict) -> None:
    update = {k: v for k, v in values.items() if v is not None}
    session.execute(pg_insert(FreeAgentRight).values(player_id=player_id, entering_season=season, **update)
                    .on_conflict_do_update(constraint="uq_free_agent_right_player_season", set_=update))


def load(year: int, team_slugs: list[str] | None = None) -> None:
    season, now = entering_season(year), datetime.now(timezone.utc)
    with get_session() as session:
        names = _build_name_index(session)
        team_ids = {
            abbreviation: team_id
            for team_id, abbreviation in session.execute(
                select(Team.team_id, Team.abbreviation)
            ).all()
        }
        source_ids = {
            source_id: player_id
            for source_id, player_id in session.execute(
                select(FreeAgentRight.source_player_id, FreeAgentRight.player_id)
            ).all()
            if source_id
        }
    global_url = f"https://www.spotrac.com/nba/free-agents/_/year/{year}"
    global_html = _get(global_url, f"free_agents_{year}")
    if global_html:
        with get_session() as session:
            for row in parse_free_agents(global_html):
                full_name = row.pop("full_name")
                pid = source_ids.get(row["source_player_id"]) or _match_player(full_name, names)
                if pid:
                    upsert_right(
                        session,
                        pid,
                        season,
                        {
                            **row,
                            "source_url": global_url,
                            "scraped_at": now,
                            "source": "spotrac",
                        },
                    )
    for slug in team_slugs or NBA_TEAM_SLUGS:
        url = f"https://www.spotrac.com/nba/{slug}/overview/_/year/{year}"
        html = _get(url, f"overview_{slug}_{year}")
        if not html:
            logger.warning("cap-hold fetch failed for %s; existing rows preserved", slug)
            continue
        with get_session() as session:
            for row in parse_cap_holds(html):
                full_name = row.pop("full_name")
                pid = source_ids.get(row["source_player_id"]) or _match_player(full_name, names)
                if pid:
                    upsert_right(
                        session,
                        pid,
                        season,
                        {
                            **row,
                            "rights_team_id": team_ids.get(TEAM_ABBREVIATIONS[slug]),
                            "source_url": url,
                            "scraped_at": now,
                            "source": "spotrac",
                        },
                    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--teams", nargs="+", choices=NBA_TEAM_SLUGS)
    args = parser.parse_args()
    load(args.year, args.teams)
