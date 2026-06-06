#!/usr/bin/env python3
"""
ScoutIQ Part-A probe — confirm the advanced-stat feature set before building ETL.

Checks two things:
  1. nba.com Advanced (leaguedashplayerstats, MeasureType=Advanced) -> USG_PCT, TS_PCT, PIE, NET_RATING...
  2. Basketball-Reference per-player "Advanced" table -> BPM, VORP, WS, WS/48

Run:  spikes/.venv/bin/python spikes/probe_advanced.py
"""
from __future__ import annotations

import re
import time
import unicodedata

BBREF_HEADERS = {"User-Agent": "ScoutIQ-spike/0.1 (personal portfolio research)"}
WANT_NBA = ["USG_PCT", "TS_PCT", "PIE", "NET_RATING", "OFF_RATING", "DEF_RATING", "AST_PCT", "REB_PCT"]
WANT_BBREF = ["BPM", "VORP", "WS", "WS/48", "OBPM", "DBPM"]


def section(t: str) -> None:
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def probe_nba_advanced(season: str = "2023-24") -> None:
    section(f"1. nba.com Advanced — leaguedashplayerstats (season {season})")
    from nba_api.stats.endpoints import leaguedashplayerstats

    t0 = time.time()
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        measure_type_detailed_defense="Advanced", season=season, timeout=30
    ).get_data_frames()[0]
    dt = time.time() - t0
    print(f"  rows={len(df)} players  fetched in {dt:.1f}s")
    print(f"  columns ({len(df.columns)}): {list(df.columns)}")
    present = [c for c in WANT_NBA if c in df.columns]
    missing = [c for c in WANT_NBA if c not in df.columns]
    print(f"  wanted present: {present}")
    print(f"  wanted MISSING: {missing or 'none'}")


def bbref_slug(full_name: str) -> str:
    norm = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode()
    parts = re.sub(r"[^a-zA-Z ]", "", norm).lower().split()
    return f"{parts[-1][:5]}{parts[0][:2]}01" if len(parts) >= 2 else ""


def probe_bbref_advanced(name: str = "Jayson Tatum") -> None:
    section(f"2. Basketball-Reference Advanced table — {name}")
    import pandas as pd
    import requests
    from io import StringIO

    slug = bbref_slug(name)
    url = f"https://www.basketball-reference.com/players/{slug[0]}/{slug}.html"
    print(f"  GET {url}")
    html = requests.get(url, headers=BBREF_HEADERS, timeout=30).text.replace("<!--", "").replace("-->", "")
    tables = pd.read_html(StringIO(html))
    print(f"  tables parsed: {len(tables)}")

    # The Advanced table is the one carrying BPM/VORP/WS columns.
    hit = None
    for i, tbl in enumerate(tables):
        cols = {str(c) for c in tbl.columns}
        if {"BPM", "VORP", "WS"} & cols:
            hit = i
            break
    if hit is None:
        print("  !! no table with BPM/VORP/WS found — advanced metrics may be named differently. (FINDING)")
        return
    tbl = tables[hit]
    cols = [str(c) for c in tbl.columns]
    print(f"  advanced table = #{hit}; columns: {cols}")
    present = [c for c in WANT_BBREF if c in cols]
    missing = [c for c in WANT_BBREF if c not in cols]
    print(f"  wanted present: {present}")
    print(f"  wanted MISSING: {missing or 'none'}")
    print(f"  sample row: {tbl.iloc[0].to_dict()}")


if __name__ == "__main__":
    probe_nba_advanced()
    time.sleep(1.0)
    probe_bbref_advanced()
    section("Decision")
    print("  Lock feature list in docs/02 §3 from the columns confirmed above.")
