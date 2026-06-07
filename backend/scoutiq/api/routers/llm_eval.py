"""Read-only API surface for the offline scout-rating eval harness."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scoutiq.llm.eval_scout_ratings import DEFAULT_OUTPUT, load_gold, load_jsonl
from scoutiq.llm.schemas import ScoutRating, Trait
from scoutiq.llm.scoring import score_extractions

LLM_DIR = Path(__file__).resolve().parents[2] / "llm"
GOLD_PATH = LLM_DIR / "eval_data" / "scout_ratings_gold.jsonl"
PREDICTIONS_PATH = LLM_DIR / "eval_data" / "scout_ratings_predictions_fixture.jsonl"

router = APIRouter(prefix="/llm", tags=["llm"])


class ScoutRatingEvalExample(BaseModel):
    note_id: str
    player_name: str
    source_text: str
    ratings: list[ScoutRating]


class ScoutRatingEvalResponse(BaseModel):
    mode: str
    report: dict[str, Any]
    traits: list[str]
    gold_count: int
    fixture_prediction_count: int
    artifact_path: str
    caveat: str
    examples: list[ScoutRatingEvalExample]


@router.get("/scout-ratings/eval", response_model=ScoutRatingEvalResponse)
def get_scout_ratings_eval():
    """Score the committed offline fixture and return model-page metadata.

    This endpoint is intentionally read-only: it does not call live LLMs and
    does not write the generated JSON artifact. Live Claude evaluation remains
    CLI-only behind explicit environment variables.
    """
    if not GOLD_PATH.exists() or not PREDICTIONS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Scout-rating eval fixtures are missing. Restore scoutiq/llm/eval_data.",
        )

    try:
        gold = load_gold(GOLD_PATH)
        prediction_rows = load_jsonl(PREDICTIONS_PATH)
        report = score_extractions(gold, prediction_rows).to_dict()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Scout-rating eval unavailable: {exc}") from exc

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
        mode="offline_fixture",
        report=report,
        traits=[trait.value for trait in Trait],
        gold_count=len(gold),
        fixture_prediction_count=len(prediction_rows),
        artifact_path=str(DEFAULT_OUTPUT.relative_to(LLM_DIR.parents[1])),
        caveat=(
            "Synthetic offline fixture only. The UI never calls Claude or Sonar; live eval is manual CLI mode "
            "behind ANTHROPIC_API_KEY and SCOUTIQ_LLM_MODEL."
        ),
        examples=examples,
    )
