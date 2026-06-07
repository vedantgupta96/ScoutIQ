"""Enrich with Basketball-Reference: advanced metrics (BPM/VORP/WS/...) + position + realized salary.

For each player already in player_seasons:
  1. resolve a verified BBRef slug -> player_xref
  2. merge BBRef advanced metrics into player_seasons.advanced (+ set players.position)
  3. upsert realized salary -> player_salaries

Caching makes re-runs instant. First full run is slow (rate-limited); validate on --limit first.

Usage:
  python -m scoutiq.etl.load_bbref --limit 10        # validate on a subset
  python -m scoutiq.etl.load_bbref                    # full run
"""
from __future__ import annotations

import argparse
import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl._util import clean
from scoutiq.models import Player, PlayerSalary, PlayerSeason, PlayerXref
from scoutiq.sources import bbref
from scoutiq.sources.crosswalk import resolve_slug
from scoutiq.sources.nba import team_id_for_abbreviation

# BBRef advanced columns -> keys stored in player_seasons.advanced (no collision with nba.com keys)
BBREF_ADV = {"BPM": "BPM", "OBPM": "OBPM", "DBPM": "DBPM", "VORP": "VORP", "WS": "WS", "WS/48": "WS48", "PER": "PER"}
MULTI_TEAM_CODES = {"TOT", "2TM", "3TM", "4TM", "5TM"}

# Real position codes (PG/SG/SF/PF/C and combos). BBRef sometimes puts notes like
# "Did not play - other pro league" in the Pos cell — reject those.
_POS_RE = re.compile(r"^[PGSFC]{1,2}(-[PGSFC]{1,2})?$")


def _valid_pos(v) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v if _POS_RE.match(v) else None


def _players_to_enrich(session, limit: int | None, only_ids: list[int] | None):
    q = (
        select(Player.player_id, Player.full_name)
        .join(PlayerSeason, PlayerSeason.player_id == Player.player_id)
        .distinct()
        .order_by(Player.full_name)
    )
    if only_ids:
        q = q.where(Player.player_id.in_(only_ids))
    if limit:
        q = q.limit(limit)
    return session.execute(q).all()


def _enrich_one(session, player_id: int, full_name: str, season_set: set[str]) -> tuple[int, int]:
    slug, status = resolve_slug(full_name)

    session.execute(
        insert(PlayerXref)
        .values(player_id=player_id, bbref_slug=slug, verified_name=full_name, status=status)
        .on_conflict_do_update(
            index_elements=["player_id"],
            set_={"bbref_slug": slug, "verified_name": full_name, "status": status},
        )
    )
    if not slug:
        return 0, 0

    html = bbref.fetch_player_html(slug)  # cached from the verify step
    if html is None:
        return 0, 0

    adv = bbref.parse_advanced(html)
    n_adv = 0
    if adv is not None and not adv.empty:
        # position from the most recent season row that has a *valid* position code
        for _, r in adv.sort_values("Season", ascending=False).iterrows():
            pos = _valid_pos(clean(r.get("Pos")))
            if pos:
                session.get(Player, player_id).position = pos
                break

        for _, r in adv.iterrows():
            season = str(r["Season"])
            if season not in season_set:
                continue
            ps = session.execute(
                select(PlayerSeason).where(
                    PlayerSeason.player_id == player_id, PlayerSeason.season == season
                )
            ).scalar_one_or_none()
            if ps is None:
                continue
            team_abbr = clean(r.get("Team") or r.get("Tm"))
            if team_abbr:
                # BBRef combined rows for traded players use 2TM/3TM/etc.; a total-season row has
                # no single team, so clear team_id rather than storing a misleading current team.
                team_code = str(team_abbr).upper()
                if team_code in MULTI_TEAM_CODES:
                    ps.team_id = None
                else:
                    team_id = team_id_for_abbreviation(team_code)
                    if team_id is not None:
                        ps.team_id = team_id
            metrics = {key: clean(r[col]) for col, key in BBREF_ADV.items() if col in r and clean(r[col]) is not None}
            ps.advanced = {**(ps.advanced or {}), **metrics}
            n_adv += 1

    sal = bbref.parse_salaries(html)
    n_sal = 0
    if sal is not None and not sal.empty:
        rows = [
            {"player_id": player_id, "season": str(r["Season"]), "salary": clean(r["Salary"]), "source": "bbref"}
            for _, r in sal.iterrows()
            if str(r["Season"]) in season_set and clean(r["Salary"]) is not None
        ]
        if rows:
            stmt = insert(PlayerSalary).values(rows)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["player_id", "season"],
                    set_={"salary": stmt.excluded["salary"], "source": stmt.excluded["source"]},
                )
            )
            n_sal = len(rows)
    return n_adv, n_sal


def run(limit: int | None, only_ids: list[int] | None) -> None:
    season_set = set(settings.seasons)
    with get_session() as s:
        players = _players_to_enrich(s, limit, only_ids)

    print(f"load_bbref: enriching {len(players)} players (cache: {settings.RAW_DIR})")
    stats = {"verified": 0, "mismatch": 0, "not_found": 0, "adv_rows": 0, "sal_rows": 0}
    for i, (pid, name) in enumerate(players, 1):
        # one transaction per player keeps progress durable; one bad player must not abort the run
        try:
            with get_session() as s:
                n_adv, n_sal = _enrich_one(s, pid, name, season_set)
                status = s.get(PlayerXref, pid).status  # read inside the session (avoid detached instance)
                stats[status] = stats.get(status, 0) + 1
                stats["adv_rows"] += n_adv
                stats["sal_rows"] += n_sal
        except Exception as e:  # noqa: BLE001 — keep the long scrape going; surface the failure
            stats["error"] = stats.get("error", 0) + 1
            print(f"  [{i}/{len(players)}] {name}: ERROR {type(e).__name__}: {e}")
            continue
        if i % 25 == 0 or i == len(players):
            print(f"  [{i}/{len(players)}] {name}: adv+{n_adv} sal+{n_sal}  ({status})")
    print(f"done. xref: {stats}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N players (validate before full run)")
    ap.add_argument("--player-ids", help="comma-separated nba player_ids")
    args = ap.parse_args()
    ids = [int(x) for x in args.player_ids.split(",")] if args.player_ids else None
    run(args.limit, ids)
