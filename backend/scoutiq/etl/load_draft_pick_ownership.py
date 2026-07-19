"""Load real draft-pick ownership from Spotrac's future-picks page into draft_picks.

Replaces the seeder's default self-ownership assumption with sourced data
(https://www.spotrac.com/nba/draft/future). Page structure: two tables per team
(Round 1, Round 2) in one page; each table groups rows by draft year over a 30-column
pick-number axis, and the FIRST row of each year group describes the fate of that
team's OWN pick — later rows mirror incoming picks and are redundant for ownership.
Cell colspans encode conditional pick ranges (e.g. "DAL If 1-2" spanning 2 columns,
"CHA If 3-30" spanning 28: Dallas keeps top-2, else conveys to Charlotte).

Honesty rules:
- Clean cases become structured fields (owner, protected_top, swap rights).
- Multi-team conditionals ("least favorable of CLE, MIN and UTA...") are NOT force-fit:
  ownership stays with the origin team, the full text is preserved in `notes`, and the
  row is counted as unresolved in the run summary.
- Rows for drafts already held (before the page's earliest year) are deleted.

Usage:
    python -m scoutiq.etl.load_draft_pick_ownership            # cached fetch + load
    python -m scoutiq.etl.load_draft_pick_ownership --no-fetch # cache only
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import DraftPick, Team

logger = logging.getLogger(__name__)

URL = "https://www.spotrac.com/nba/draft/future"
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

# Spotrac abbreviation quirks -> nba_api teams.abbreviation.
ABBR_ALIASES = {"PHO": "PHX", "NO": "NOP", "SA": "SAS", "GS": "GSW", "NY": "NYK", "UTAH": "UTA"}
# Spotrac section headings that differ from nba_api teams.name
# (DB stores "Los Angeles Clippers"; Spotrac's section heading says "LA Clippers").
NAME_ALIASES = {"LA Clippers": "LAC"}

_YEAR = re.compile(r"^20\d\d$")
_LEAD_ABBR = re.compile(r"^([A-Z]{2,4})\b")
_PROTECTED = re.compile(r"^If 1-(\d+)$")
_SWAP = re.compile(r"\bswap with ([A-Z]{2,4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class OwnPickLine:
    """One team's own pick for one (year, round): the first row of a year group."""
    origin_abbr: str
    draft_year: int
    round: int
    segments: list[tuple[str, int]]  # (cell text, colspan width), in pick-axis order

    @property
    def raw_text(self) -> str:
        return " | ".join(text for text, _ in self.segments)


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.html"


def fetch_page(*, allow_network: bool = True) -> str | None:
    path = _cache_path("future_draft_picks")
    fresh = path.exists() and (time.time() - path.stat().st_mtime) / 86_400 <= CACHE_TTL_DAYS
    if fresh or (path.exists() and not allow_network):
        return path.read_text(encoding="utf-8")
    if not allow_network:
        return None
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("fetch failed %s: %s", URL, e)
        return path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(resp.text, encoding="utf-8")
    time.sleep(SPOTRAC_DELAY_SECONDS)
    return resp.text


def parse_own_pick_lines(html: str, team_names_to_abbr: dict[str, str]) -> list[OwnPickLine]:
    """Extract each team's own-pick rows from the two per-team tables."""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    name_pattern = re.compile("|".join(re.escape(name) for name in team_names_to_abbr))

    lines: list[OwnPickLine] = []
    for index, table in enumerate(tables):
        heading = table.find_previous(string=name_pattern)
        if heading is None:
            continue
        match = name_pattern.search(heading)
        origin_abbr = team_names_to_abbr[match.group(0)]
        rnd = 1 if index % 2 == 0 else 2

        current_year: int | None = None
        year_has_own_row: set[int] = set()
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            first_text = cells[0].get_text(strip=True)
            if len(cells) == 1 and _YEAR.match(first_text):
                current_year = int(first_text)
                continue
            if cells[0].name != "td" or current_year is None or len(cells) < 2:
                continue
            if current_year in year_has_own_row:
                continue  # later rows mirror incoming picks; ownership comes from each origin's own section
            year_has_own_row.add(current_year)
            segments = [
                (c.get_text(" ", strip=True), int(c.get("colspan") or 1))
                for c in cells[1:]
            ]
            lines.append(OwnPickLine(origin_abbr, current_year, rnd, segments))
    return lines


def _norm_abbr(abbr: str) -> str:
    return ABBR_ALIASES.get(abbr, abbr)


def resolve_line(line: OwnPickLine, known_abbrs: set[str]) -> dict:
    """Map one own-pick line to draft_picks fields. Conservative by design:
    anything not cleanly expressible keeps origin ownership + verbatim notes."""
    origin = line.origin_abbr
    result = {
        "origin_abbr": origin,
        "draft_year": line.draft_year,
        "round": line.round,
        "owner_abbr": origin,
        "protected_top": None,
        "swap_abbr": None,
        "notes": None,
        "resolved": True,
    }

    def lead_abbr(text: str) -> str | None:
        match = _LEAD_ABBR.match(text)
        abbr = _norm_abbr(match.group(1)) if match else None
        return abbr if abbr in known_abbrs else None

    segments = [(text, width) for text, width in line.segments if text]
    if len(segments) == 1:
        text, _ = segments[0]
        holder = lead_abbr(text)
        remainder = text[len(text.split()[0]):].strip() if holder else text
        swap = _SWAP.search(text)
        if holder and not remainder:
            result["owner_abbr"] = holder                      # e.g. "SAS"
        elif holder and swap:
            result["owner_abbr"] = holder                      # e.g. "BKN HOU Or swap with HOU"
            result["swap_abbr"] = _norm_abbr(swap.group(1))
            result["notes"] = text
        elif holder and re.fullmatch(r"\(via [^)]+\)", remainder):
            result["owner_abbr"] = holder                      # e.g. "HOU (via BKN)"
            result["notes"] = text
        else:
            result["notes"] = text                             # conditional prose -> unresolved
            result["resolved"] = False
    elif len(segments) == 2:
        (text_a, width_a), (text_b, _) = segments
        abbr_a, abbr_b = lead_abbr(text_a), lead_abbr(text_b)
        protected = _PROTECTED.match(text_a[len(text_a.split()[0]):].strip()) if abbr_a else None
        if abbr_a == origin and abbr_b and protected and int(protected.group(1)) == width_a:
            # "ORIGIN If 1-k | OTHER If k+1-30": top-k protected, conveys to OTHER.
            result["owner_abbr"] = abbr_b
            result["protected_top"] = width_a
            result["notes"] = line.raw_text
        else:
            result["notes"] = line.raw_text
            result["resolved"] = False
    else:
        result["notes"] = line.raw_text
        result["resolved"] = False
    return result


def run(*, allow_network: bool = True) -> tuple[int, int]:
    html = fetch_page(allow_network=allow_network)
    if html is None:
        raise SystemExit("No Spotrac page available (network failed and no cache).")

    now = datetime.now(timezone.utc)
    with get_session() as db:
        teams = db.scalars(select(Team)).all()
        names_to_abbr = {t.name: t.abbreviation for t in teams if t.name and t.abbreviation}
        names_to_abbr.update(NAME_ALIASES)
        abbr_to_id = {t.abbreviation: t.team_id for t in teams if t.abbreviation}
        known = set(abbr_to_id)

        lines = parse_own_pick_lines(html, names_to_abbr)
        if len(lines) < 30 * 2 * 5:  # 30 teams x 2 rounds x >=5 years, else the page changed shape
            raise SystemExit(f"Parse looks broken: only {len(lines)} own-pick lines found.")

        resolved = [resolve_line(line, known) for line in lines]
        unresolved = [r for r in resolved if not r["resolved"]]

        values = []
        for r in resolved:
            values.append({
                "draft_year": r["draft_year"],
                "round": r["round"],
                "original_team_id": abbr_to_id[r["origin_abbr"]],
                "current_team_id": abbr_to_id[r["owner_abbr"]],
                "protected_top": r["protected_top"],
                "swap_rights_team_id": abbr_to_id.get(r["swap_abbr"]) if r["swap_abbr"] else None,
                "converts_to": None,
                "source": "spotrac" if r["resolved"] else "spotrac-conditional",
                "source_url": URL,
                "notes": r["notes"],
                "updated_at": now,
            })

        stmt = pg_insert(DraftPick).values(values)
        update_cols = {
            col: stmt.excluded[col]
            for col in values[0]
            if col not in ("draft_year", "round", "original_team_id")
        }
        db.execute(stmt.on_conflict_do_update(constraint="uq_draft_pick_identity", set_=update_cols))

        # Drafts already held are no longer tradable assets.
        min_year = min(v["draft_year"] for v in values)
        stale = db.execute(delete(DraftPick).where(DraftPick.draft_year < min_year)).rowcount

        years = sorted({v["draft_year"] for v in values})
        print(f"draft_picks ownership: upserted {len(values)} picks ({years[0]}-{years[-1]}), "
              f"{len(unresolved)} conditional lines kept origin ownership with verbatim notes, "
              f"deleted {stale} pre-{min_year} rows")
        for r in unresolved[:8]:
            print(f"  conditional: {r['draft_year']} R{r['round']} {r['origin_abbr']}: {r['notes'][:90]}")
        return len(values), len(unresolved)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Spotrac future draft-pick ownership.")
    parser.add_argument("--no-fetch", action="store_true", help="Use disk cache only; never hit the network.")
    args = parser.parse_args()
    run(allow_network=not args.no_fetch)


if __name__ == "__main__":
    main()
