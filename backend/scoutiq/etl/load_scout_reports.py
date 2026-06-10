"""Backfill scout_reports from Perplexity Sonar for the top-tier current-season players.

Stage 1 of the qualitative layer (WORDS). Selects the highest-minute-per-game players for the current
season, adds a small marquee coverage list for load-managed stars, fetches a cited Sonar narrative, upserts it
into `scout_reports`, and writes a committed corpus snapshot for reproducibility. Stage 2
(etl/extract_scout_ratings.py) turns these into structured ratings.

Usage:
    python -m scoutiq.etl.load_scout_reports --limit 5     # smoke test
    python -m scoutiq.etl.load_scout_reports               # default ~40 players + marquee coverage
    python -m scoutiq.etl.load_scout_reports --players 203999 1629029
    python -m scoutiq.etl.load_scout_reports --no-marquee
"""
from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import Player, PlayerSeason, ScoutReport
from scoutiq.sources import sonar

logger = logging.getLogger(__name__)

SOURCE_LABEL = "Perplexity Sonar"
DEFAULT_LIMIT = 40
# High-impact players who can miss a total-minutes cutoff because of injury/load management.
DEFAULT_MARQUEE_PLAYER_IDS = (201939,)  # Stephen Curry
CORPUS_SNAPSHOT = Path(__file__).resolve().parents[1] / "llm" / "eval_data" / "player_scout_corpus.jsonl"


def report_id_for(player_id: int, season: str) -> str:
    return f"sonar-{player_id}-{season}"


def _merge_unique_players(*groups: Sequence[tuple[int, str]]) -> list[tuple[int, str]]:
    """Preserve group order while de-duping players by nba_api player_id."""
    seen: set[int] = set()
    merged: list[tuple[int, str]] = []
    for group in groups:
        for player_id, full_name in group:
            if player_id in seen:
                continue
            merged.append((player_id, full_name))
            seen.add(player_id)
    return merged


def _select_top_tier(
    limit: int,
    season: str,
    marquee_player_ids: Sequence[int] = DEFAULT_MARQUEE_PLAYER_IDS,
) -> list[tuple[int, str]]:
    """Highest-minute-per-game players plus explicit marquee coverage."""
    min_per_game = PlayerSeason.minutes / PlayerSeason.gp
    stmt = (
        select(Player.player_id, Player.full_name)
        .join(PlayerSeason, PlayerSeason.player_id == Player.player_id)
        .where(PlayerSeason.season == season)
        .where(PlayerSeason.gp >= 20)
        .where(PlayerSeason.minutes >= 600)
        .order_by(min_per_game.desc().nulls_last(), PlayerSeason.minutes.desc().nulls_last())
        .limit(limit)
    )
    with get_session() as session:
        ranked = [(row.player_id, row.full_name) for row in session.execute(stmt).all()]
    marquee = _select_named(list(marquee_player_ids)) if marquee_player_ids else []
    return _merge_unique_players(ranked, marquee)


def _select_named(player_ids: list[int]) -> list[tuple[int, str]]:
    with get_session() as session:
        rows = session.execute(
            select(Player.player_id, Player.full_name).where(Player.player_id.in_(player_ids))
        ).all()
    return [(row.player_id, row.full_name) for row in rows]


def _upsert_report(report_id: str, player_id: int, season: str, report: sonar.SonarReport) -> None:
    now = datetime.now(tz=timezone.utc)
    stmt = (
        pg_insert(ScoutReport)
        .values(
            report_id=report_id,
            player_id=player_id,
            season=season,
            source_label=SOURCE_LABEL,
            source_text=report.source_text,
            citations=report.citations,
            fetched_at=now,
        )
        .on_conflict_do_update(
            index_elements=["report_id"],
            set_={
                "source_text": report.source_text,
                "citations": report.citations,
                "fetched_at": now,
            },
        )
    )
    with get_session() as session:
        session.execute(stmt)


def _write_corpus_snapshot() -> int:
    """Dump every scout_report to a committed JSONL snapshot (reproducibility)."""
    with get_session() as session:
        reports = session.scalars(select(ScoutReport).order_by(ScoutReport.player_id)).all()
        rows = [
            {
                "report_id": r.report_id,
                "player_id": r.player_id,
                "season": r.season,
                "source_label": r.source_label,
                "source_text": r.source_text,
                "citations": r.citations or [],
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in reports
        ]
    CORPUS_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_SNAPSHOT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def load_all(
    limit: int = DEFAULT_LIMIT,
    player_ids: list[int] | None = None,
    season: str | None = None,
    marquee_player_ids: Sequence[int] = DEFAULT_MARQUEE_PLAYER_IDS,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    season = season or settings.CURRENT_SEASON

    players = _select_named(player_ids) if player_ids else _select_top_tier(limit, season, marquee_player_ids)
    logger.info("Sourcing Sonar reports for %d players (season %s)", len(players), season)

    ok = skipped = errors = 0
    for player_id, full_name in players:
        try:
            report = sonar.fetch_scout_report(player_id, full_name, season)
            if report is None:
                logger.warning("✗ %s — no Sonar response", full_name)
                skipped += 1
                continue
            _upsert_report(report_id_for(player_id, season), player_id, season, report)
            logger.info("✓ %s — %d chars, %d citations", full_name, len(report.source_text), len(report.citations))
            ok += 1
        except Exception as e:
            logger.warning("✗ %s: %s", full_name, e)
            errors += 1

    snapshot_count = _write_corpus_snapshot()
    logger.info("Done. ok=%d skipped=%d errors=%d | corpus snapshot: %d reports", ok, skipped, errors, snapshot_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--players", nargs="+", type=int, default=None, metavar="PLAYER_ID")
    parser.add_argument(
        "--marquee-players",
        nargs="+",
        type=int,
        default=list(DEFAULT_MARQUEE_PLAYER_IDS),
        metavar="PLAYER_ID",
        help="extra player IDs to include after the MPG-ranked pool",
    )
    parser.add_argument("--no-marquee", action="store_true", help="disable the default marquee coverage list")
    parser.add_argument("--season", type=str, default=None)
    args = parser.parse_args()
    marquee_player_ids = [] if args.no_marquee else args.marquee_players
    load_all(limit=args.limit, player_ids=args.players, season=args.season, marquee_player_ids=marquee_player_ids)
