"""Backfill player_ratings: extract structured trait ratings from scout_reports with Claude.

Stage 2 of the qualitative layer. For each report without ratings, calls the shared Claude extractor
(llm.extract.extract_ratings), validates against the pydantic schema, and clean-replaces the report's
`player_ratings` rows. Reads ANTHROPIC_API_KEY + SCOUTIQ_LLM_MODEL from settings (backend/.env).

An optional --eval-gate runs the SAME extraction path over the labeled gold set and prints the eval
harness metrics (trait coverage / within-1 agreement) so extraction reliability is visible before the
production ratings are trusted.

Usage:
    python -m scoutiq.etl.extract_scout_ratings --limit 3      # smoke test
    python -m scoutiq.etl.extract_scout_ratings               # all reports lacking ratings
    python -m scoutiq.etl.extract_scout_ratings --force       # re-extract everything
    python -m scoutiq.etl.extract_scout_ratings --eval-gate   # quality check on the gold set
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, exists, select

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.llm import extract
from scoutiq.llm.eval_scout_ratings import load_gold
from scoutiq.llm.scoring import score_extractions
from scoutiq.models import Player, PlayerRating, ScoutReport

logger = logging.getLogger(__name__)

GOLD_PATH = Path(__file__).resolve().parents[1] / "llm" / "eval_data" / "scout_ratings_gold.jsonl"


def _require_keys() -> tuple[str, str]:
    api_key = settings.ANTHROPIC_API_KEY
    model = settings.SCOUTIQ_LLM_MODEL
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is empty. Set it in backend/.env to run extraction.")
    return api_key, model


def _reports_to_process(limit: int | None, force: bool) -> list[tuple[str, int, str]]:
    """Return [(report_id, player_id, source_text)] for reports needing extraction."""
    stmt = select(ScoutReport)
    if not force:
        has_ratings = exists().where(PlayerRating.report_id == ScoutReport.report_id)
        stmt = stmt.where(~has_ratings)
    stmt = stmt.order_by(ScoutReport.player_id)
    if limit:
        stmt = stmt.limit(limit)
    with get_session() as session:
        return [(r.report_id, r.player_id, r.source_text) for r in session.scalars(stmt).all()]


def _player_names(player_ids: list[int]) -> dict[int, str]:
    if not player_ids:
        return {}
    with get_session() as session:
        rows = session.execute(
            select(Player.player_id, Player.full_name).where(Player.player_id.in_(player_ids))
        ).all()
    return {row.player_id: row.full_name for row in rows}


def _replace_ratings(report_id: str, player_id: int, extraction) -> int:
    with get_session() as session:
        session.execute(delete(PlayerRating).where(PlayerRating.report_id == report_id))
        for rating in extraction.ratings:
            session.add(PlayerRating(
                report_id=report_id,
                player_id=player_id,
                trait=rating.trait.value,
                score=rating.score,
                confidence=rating.confidence,
                evidence_span=rating.evidence_span,
            ))
    return len(extraction.ratings)


def run_eval_gate(api_key: str, model: str) -> None:
    """Run live extraction over the gold set and print harness metrics."""
    gold = load_gold(GOLD_PATH)
    predictions = []
    for row in gold:
        try:
            predictions.append(
                extract.call_anthropic_raw(row.note_id, row.player_name, row.source_text, api_key=api_key, model=model)
            )
        except Exception as e:
            logger.warning("eval-gate extraction failed for %s: %s", row.note_id, e)
    report = score_extractions(gold, predictions).to_dict()
    logger.info(
        "EVAL GATE — trait_coverage=%.3f within_one=%.3f exact=%.3f invalid=%d",
        report["trait_coverage"], report["within_one_score_agreement"],
        report["exact_score_agreement"], report["invalid_output_count"],
    )


def run(limit: int | None = None, force: bool = False, eval_gate: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    api_key, model = _require_keys()

    if eval_gate:
        run_eval_gate(api_key, model)

    reports = _reports_to_process(limit, force)
    names = _player_names([pid for _, pid, _ in reports])
    logger.info("Extracting ratings for %d reports with %s", len(reports), model)

    ok = invalid = errors = total_ratings = 0
    for report_id, player_id, source_text in reports:
        player_name = names.get(player_id, str(player_id))
        try:
            extraction = extract.extract_ratings(
                report_id, player_name, source_text, api_key=api_key, model=model
            )
        except ValidationError as e:
            logger.warning("✗ %s — invalid extraction: %s", player_name, e.error_count())
            invalid += 1
            continue
        except Exception as e:
            logger.warning("✗ %s: %s", player_name, e)
            errors += 1
            continue
        n = _replace_ratings(report_id, player_id, extraction)
        total_ratings += n
        logger.info("✓ %s — %d traits", player_name, n)
        ok += 1

    logger.info(
        "Done. ok=%d invalid=%d errors=%d | %d ratings written", ok, invalid, errors, total_ratings
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="re-extract reports that already have ratings")
    parser.add_argument("--eval-gate", action="store_true", help="run live eval over the gold set first")
    args = parser.parse_args()
    run(limit=args.limit, force=args.force, eval_gate=args.eval_gate)
