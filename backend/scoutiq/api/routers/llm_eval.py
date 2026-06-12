"""Read-only API surface for the offline scout-rating eval harness."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scoutiq.api.deps import get_db
from scoutiq.llm.eval_scout_ratings import DEFAULT_OUTPUT, load_gold, load_jsonl
from scoutiq.llm.schemas import ScoutRating, Trait
from scoutiq.llm.scoring import score_extractions
from scoutiq.models import PlayerRating, ScoutReport

logger = logging.getLogger(__name__)

LLM_DIR = Path(__file__).resolve().parents[2] / "llm"
GOLD_PATH = LLM_DIR / "eval_data" / "scout_ratings_gold.jsonl"
PREDICTIONS_PATH = LLM_DIR / "eval_data" / "scout_ratings_predictions_fixture.jsonl"
ARTIFACT_PATH = DEFAULT_OUTPUT

router = APIRouter(prefix="/llm", tags=["llm"])


class ScoutRatingEvalExample(BaseModel):
    note_id: str
    player_name: str
    source_text: str
    ratings: list[ScoutRating]


class ScoutCorpusStats(BaseModel):
    """Footprint of the real Sonar->Claude corpus served from Postgres."""

    report_count: int
    cited_report_count: int
    rated_player_count: int
    rating_count: int
    latest_fetched_at: str | None


class ScoutRatingEvalResponse(BaseModel):
    mode: str  # "live_artifact" | "offline_fixture"
    report: dict[str, Any]
    meta: dict[str, Any] | None = None
    corpus: ScoutCorpusStats | None = None
    traits: list[str]
    gold_count: int
    fixture_prediction_count: int
    artifact_path: str
    caveat: str
    examples: list[ScoutRatingEvalExample]


def _load_live_artifact() -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (report, meta) from the committed eval artifact, but only when it
    self-identifies as a live-model run — a fixture replay is not evidence."""
    if not ARTIFACT_PATH.exists():
        return None
    try:
        data = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("scout eval artifact unreadable: %s", exc)
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("mode") != "live":
        return None
    report = {k: v for k, v in data.items() if k != "meta"}
    return report, meta


def _corpus_stats(db: Session) -> ScoutCorpusStats | None:
    """Count the production corpus. Defensive: a missing/odd DB (tests, fresh
    clones) yields None rather than failing the whole eval payload."""
    try:
        report_row = db.execute(
            select(
                func.count(ScoutReport.report_id),
                func.count(ScoutReport.citations),
                func.count(func.distinct(ScoutReport.player_id)),
                func.max(ScoutReport.fetched_at),
            )
        ).first()
        rating_row = db.execute(
            select(func.count(PlayerRating.id))
        ).first()
        if not report_row or not rating_row:
            return None
        report_count, cited_count, player_count, latest = report_row
        if not report_count:
            return None
        return ScoutCorpusStats(
            report_count=int(report_count),
            cited_report_count=int(cited_count or 0),
            rated_player_count=int(player_count or 0),
            rating_count=int(rating_row[0] or 0),
            latest_fetched_at=latest.isoformat() if latest is not None else None,
        )
    except Exception as exc:  # pragma: no cover - shape varies by test stub
        logger.warning("scout corpus stats unavailable: %s", exc)
        return None


@router.get("/scout-ratings/eval", response_model=ScoutRatingEvalResponse)
def get_scout_ratings_eval(db: Session = Depends(get_db)):
    """Eval + corpus metadata for the model page.

    This endpoint is intentionally read-only: it never calls live LLMs. The
    eval metrics come from the committed CLI artifact when that artifact was
    produced by a live-model run (`meta.mode == "live"`); otherwise it falls
    back to scoring the synthetic fixture predictions in-process. Corpus
    counts describe the real Sonar-sourced, Claude-extracted rows in Postgres.
    """
    if not GOLD_PATH.exists() or not PREDICTIONS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Scout-rating eval fixtures are missing. Restore scoutiq/llm/eval_data.",
        )

    try:
        gold = load_gold(GOLD_PATH)
        prediction_rows = load_jsonl(PREDICTIONS_PATH)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Scout-rating eval unavailable: {exc}") from exc

    live = _load_live_artifact()
    if live is not None:
        report, meta = live
        mode = "live_artifact"
        caveat = (
            "Gold-set eval ran offline via the CLI against the live extraction model; the UI never "
            "calls Claude or Sonar. Gold notes are synthetic by design (no scraped scouting IP). "
            "Corpus counts below are the real cited reports and extracted ratings served from Postgres."
        )
    else:
        try:
            report = score_extractions(gold, prediction_rows).to_dict()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Scout-rating eval unavailable: {exc}") from exc
        meta = None
        mode = "offline_fixture"
        caveat = (
            "Synthetic offline fixture only. The UI never calls Claude or Sonar; live eval is manual "
            "CLI mode behind ANTHROPIC_API_KEY and SCOUTIQ_LLM_MODEL."
        )

    examples = [
        ScoutRatingEvalExample(
            note_id=row.note_id,
            player_name=row.player_name,
            source_text=row.source_text,
            ratings=row.ratings,
        )
        for row in gold[:2]
    ]

    return ScoutRatingEvalResponse(
        mode=mode,
        report=report,
        meta=meta,
        corpus=_corpus_stats(db),
        traits=[trait.value for trait in Trait],
        gold_count=len(gold),
        fixture_prediction_count=len(prediction_rows),
        artifact_path=str(DEFAULT_OUTPUT.relative_to(LLM_DIR.parents[1])),
        caveat=caveat,
        examples=examples,
    )
