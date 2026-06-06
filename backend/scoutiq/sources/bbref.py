"""Basketball-Reference adapter: fetch (with disk cache), strip comment-buried tables, parse.

One player page yields BOTH the Advanced table (BPM/VORP/WS/... + Pos) and the Salaries table.
Sports-Reference hides many tables inside HTML comments, so we strip <!-- --> before parsing.
Be a polite citizen: identify ourselves, rate-limit, and cache so re-runs never re-hit the site.
"""
from __future__ import annotations

import re
import time
import unicodedata
from io import StringIO

import pandas as pd
import requests

from scoutiq.config import settings

RAW_DIR = settings.RAW_DIR
_SEASON_RE = re.compile(r"^\d{4}-\d{2}$")
_last_fetch_ts = 0.0


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation — for slug building and match verification."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", norm.lower()).strip()


def bbref_slug(full_name: str, suffix: int = 1) -> str:
    """BBRef id heuristic: first5(last)+first2(first)+NN. Collisions resolve via suffix 02/03..."""
    parts = normalize_name(full_name).split()
    if len(parts) < 2:
        return ""
    first, last = parts[0], parts[-1]
    return f"{last[:5]}{first[:2]}{suffix:02d}"


def player_url(slug: str) -> str:
    return f"https://www.basketball-reference.com/players/{slug[0]}/{slug}.html"


def strip_html_comments(html: str) -> str:
    return html.replace("<!--", "").replace("-->", "")


def fetch_player_html(slug: str, use_cache: bool = True) -> str | None:
    """Return raw HTML for a player slug; cache to data/raw/{slug}.html. None on 404/error."""
    global _last_fetch_ts
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{slug}.html"
    if use_cache and cache.exists():
        return cache.read_text(encoding="utf-8")

    # rate-limit live fetches
    wait = settings.BBREF_DELAY_SECONDS - (time.time() - _last_fetch_ts)
    if wait > 0:
        time.sleep(wait)
    try:
        resp = requests.get(player_url(slug), headers={"User-Agent": settings.BBREF_USER_AGENT}, timeout=30)
    except requests.RequestException:
        return None
    finally:
        _last_fetch_ts = time.time()

    if resp.status_code != 200:
        return None
    resp.encoding = "utf-8"  # BBRef is UTF-8; requests otherwise guesses Latin-1 and mangles accents
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


def page_player_name(html: str) -> str | None:
    """Pull the player's name from <title> for match verification."""
    m = re.search(r"<title>([^<|]+)", html)
    return m.group(1).strip() if m else None


def _read_tables(html: str) -> list[pd.DataFrame]:
    try:
        return pd.read_html(StringIO(strip_html_comments(html)))
    except ValueError:
        return []


def _season_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only real per-season rows (drop Career/averages footers); de-dupe by season (keep first =
    BBRef's combined row for multi-team seasons)."""
    cols = [str(c) for c in df.columns]
    df.columns = cols
    if "Season" not in cols:
        return df.iloc[0:0]
    out = df[df["Season"].astype(str).str.match(_SEASON_RE)].copy()
    return out.drop_duplicates(subset="Season", keep="first")


def parse_advanced(html: str) -> pd.DataFrame | None:
    """Advanced table: BPM, VORP, WS, WS/48, OBPM, DBPM, PER, USG%, TS%, Pos, Age per season."""
    for tbl in _read_tables(html):
        cols = {str(c) for c in tbl.columns}
        if {"BPM", "VORP", "WS"} & cols:
            return _season_rows(tbl)
    return None


def _parse_salary(val) -> int | None:
    if not isinstance(val, str):
        return None
    digits = re.sub(r"[^\d]", "", val)
    return int(digits) if digits else None


def parse_salaries(html: str) -> pd.DataFrame | None:
    """Salaries table -> columns [Season, Salary(int)]. Realized per-season salary."""
    for tbl in _read_tables(html):
        cols = {str(c) for c in tbl.columns}
        if "Salary" in cols and "Season" in cols:
            rows = _season_rows(tbl)
            if rows.empty:
                continue
            rows["Salary"] = rows["Salary"].map(_parse_salary)
            return rows[["Season", "Salary"]]
    return None
