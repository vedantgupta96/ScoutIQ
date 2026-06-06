#!/usr/bin/env python3
"""
ScoutIQ data-source spike — THROWAWAY probe.

Goal: generate real evidence to fill in docs/01-data-source-spike.md.
It probes two things and prints honest findings:

  1. nba_api          -> can we get per-season stats (incl. advanced)? how fast before it throttles?
  2. Basketball Ref   -> can we get CONTRACT/salary data, and how painful is parsing + name->id matching?

This is intentionally crude. Do NOT build on it. Run it, read the output, copy findings into the doc.

Usage:
    pip install -r spikes/requirements.txt
    python spikes/probe_data_sources.py
    python spikes/probe_data_sources.py --players "LeBron James" "Stephen Curry" "Jayson Tatum"

Notes:
  - Basketball-Reference rate-limits hard (~20 req/min) and will 429/ban if hammered. We sleep between calls.
  - Sports-Reference hides many tables inside HTML comments; we strip comments before parsing. That gotcha
    is half the point of this probe — see how the salary table is buried.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata

DEFAULT_PLAYERS = ["LeBron James", "Stephen Curry", "Jayson Tatum"]

BBREF_HEADERS = {
    # Identify yourself; don't pretend to be a browser farm. Be a polite citizen.
    "User-Agent": "ScoutIQ-spike/0.1 (personal portfolio research)",
}


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def require(modname: str, pip_name: str | None = None):
    try:
        return __import__(modname)
    except ImportError:
        print(f"[MISSING] `{modname}` not installed. Run: pip install {pip_name or modname}")
        return None


# ---------------------------------------------------------------------------
# 1. nba_api probe
# ---------------------------------------------------------------------------
def probe_nba_api(names: list[str]) -> None:
    section("1. nba_api — stats backbone")

    if require("nba_api") is None:
        print("Skipping nba_api probe.")
        return

    from nba_api.stats.static import players as static_players
    from nba_api.stats.endpoints import playercareerstats

    for name in names:
        matches = static_players.find_players_by_full_name(name)
        if not matches:
            print(f"  [{name}] NO MATCH in nba_api static list — name-matching will need a crosswalk.")
            continue
        p = matches[0]
        pid = p["id"]
        print(f"\n  [{name}] -> nba_api id={pid}  (matches found: {len(matches)})")

        t0 = time.time()
        try:
            career = playercareerstats.PlayerCareerStats(player_id=pid, timeout=30)
            df = career.get_data_frames()[0]  # SeasonTotalsRegularSeason
        except Exception as e:  # noqa: BLE001 — spike: we want the raw failure mode
            print(f"    !! request failed: {type(e).__name__}: {e}")
            print("    (this IS a finding — note throttling/timeout behavior in the doc)")
            time.sleep(2.0)
            continue
        dt = time.time() - t0

        print(f"    fetched {len(df)} seasons in {dt:.1f}s")
        print(f"    columns available ({len(df.columns)}): {list(df.columns)}")
        # Which advanced metrics are present vs. missing (these matter for valuation features):
        wanted = ["PER", "BPM", "VORP", "WS", "USG_PCT", "TS_PCT"]
        present = [c for c in wanted if c in df.columns]
        missing = [c for c in wanted if c not in df.columns]
        print(f"    advanced present: {present or 'NONE'}")
        print(f"    advanced MISSING: {missing or 'none'}  <- if missing, need Basketball-Reference/derive")

        time.sleep(1.0)  # be gentle


# ---------------------------------------------------------------------------
# 2. Basketball-Reference contract probe
# ---------------------------------------------------------------------------
def bbref_slug(full_name: str) -> str:
    """
    Reproduce BBRef's player-id slug heuristic: first 5 of last name + first 2 of first name + '01'.
    e.g. 'LeBron James' -> jamesle01.  WARNING: collisions get 02/03; this only tries 01.
    That fragility IS the finding — note how often the slug is wrong.
    """
    norm = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode()
    parts = re.sub(r"[^a-zA-Z ]", "", norm).lower().split()
    if len(parts) < 2:
        return ""
    first, last = parts[0], parts[-1]
    return f"{last[:5]}{first[:2]}01"


def strip_html_comments(html: str) -> str:
    """Sports-Reference buries many tables inside <!-- ... --> comments. Unwrap them."""
    return html.replace("<!--", "").replace("-->", "")


def probe_bbref_contracts(names: list[str]) -> None:
    section("2. Basketball-Reference — CONTRACT / salary data (the make-or-break row)")

    requests = require("requests")
    pd = require("pandas", "pandas lxml")
    if requests is None or pd is None:
        print("Skipping contract probe.")
        return

    for name in names:
        slug = bbref_slug(name)
        if not slug:
            print(f"\n  [{name}] could not build slug.")
            continue
        url = f"https://www.basketball-reference.com/players/{slug[0]}/{slug}.html"
        print(f"\n  [{name}] -> slug={slug}")
        print(f"    GET {url}")

        try:
            resp = requests.get(url, headers=BBREF_HEADERS, timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"    !! request error: {type(e).__name__}: {e}")
            time.sleep(4.0)
            continue

        print(f"    status={resp.status_code}  bytes={len(resp.content)}")
        if resp.status_code == 429:
            print("    !! 429 rate-limited — BBRef is throttling. Slow down / cache. (FINDING)")
            time.sleep(10.0)
            continue
        if resp.status_code != 200:
            print("    !! non-200 — slug likely wrong (collision -> 02/03) or page moved. (FINDING)")
            time.sleep(4.0)
            continue

        html = strip_html_comments(resp.text)

        # Does a contract/salary table even exist on the page?
        has_contract_kw = any(k in html.lower() for k in ("contract", "salary"))
        print(f"    page mentions contract/salary: {has_contract_kw}")

        try:
            tables = pd.read_html(html)
        except ValueError:
            print("    !! pandas found NO tables after comment-stripping. (FINDING)")
            time.sleep(4.0)
            continue

        print(f"    tables parsed: {len(tables)}")
        # Heuristic: a salary table usually has a column that looks like a dollar amount or 'Salary'.
        salary_like = []
        for i, t in enumerate(tables):
            cols = [str(c) for c in t.columns]
            joined = " ".join(cols).lower()
            if "salary" in joined or any("$" in str(v) for v in t.head(1).values.flatten()):
                salary_like.append(i)
        if salary_like:
            idx = salary_like[0]
            print(f"    candidate salary table = #{idx}; columns: {list(tables[idx].columns)[:8]}")
            print(f"    sample row: {tables[idx].iloc[0].to_dict() if len(tables[idx]) else 'empty'}")
            print("    -> structure usable? Note guaranteed vs option years are often NOT here. (FINDING)")
        else:
            print("    no obvious salary table found — contract structure may need Spotrac instead. (FINDING)")

        time.sleep(3.5)  # respect ~20 req/min


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="ScoutIQ data-source spike probe")
    ap.add_argument("--players", nargs="*", default=DEFAULT_PLAYERS,
                    help="player full names to probe")
    ap.add_argument("--skip-nba", action="store_true")
    ap.add_argument("--skip-contracts", action="store_true")
    args = ap.parse_args()

    print("ScoutIQ data-source spike — copy findings into docs/01-data-source-spike.md")
    print(f"players: {args.players}")

    if not args.skip_nba:
        probe_nba_api(args.players)
    if not args.skip_contracts:
        probe_bbref_contracts(args.players)

    section("Done — questions to answer in the doc")
    print("  - nba_api: which advanced stats are MISSING? throttle/timeout behavior?")
    print("  - BBRef: did slugs resolve? was a usable salary table present?")
    print("  - Is contract STRUCTURE (guaranteed / options / year-by-year) available, or AAV-only?")
    print("  - If structure is missing here -> evaluate Spotrac, and consider Plan B (AAV-only Phase 1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
