"""Pure scoring functions for scout-rating extraction evals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from scoutiq.llm.schemas import ScoutRating, ScoutRatingExtraction


@dataclass(frozen=True)
class EvalReport:
    total_notes: int
    expected_trait_count: int
    predicted_trait_count: int
    trait_coverage: float
    exact_score_agreement: float
    within_one_score_agreement: float
    evidence_hit_rate: float
    invalid_output_count: int
    validation_errors: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_notes": self.total_notes,
            "expected_trait_count": self.expected_trait_count,
            "predicted_trait_count": self.predicted_trait_count,
            "trait_coverage": round(self.trait_coverage, 4),
            "exact_score_agreement": round(self.exact_score_agreement, 4),
            "within_one_score_agreement": round(self.within_one_score_agreement, 4),
            "evidence_hit_rate": round(self.evidence_hit_rate, 4),
            "invalid_output_count": self.invalid_output_count,
            "validation_errors": self.validation_errors,
        }


def _rating_by_trait(ratings: list[ScoutRating]) -> dict[str, ScoutRating]:
    return {rating.trait.value: rating for rating in ratings}


def _safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def score_extractions(
    gold: list[ScoutRatingExtraction],
    prediction_rows: list[dict[str, Any]],
) -> EvalReport:
    """Score raw prediction rows against validated gold extractions.

    Invalid prediction rows are counted and skipped. Missing predictions for a
    note simply contribute zero matched traits.
    """

    predictions: dict[str, ScoutRatingExtraction] = {}
    validation_errors: list[dict[str, Any]] = []

    for row in prediction_rows:
        note_id = str(row.get("note_id", "<missing>"))
        try:
            extraction = ScoutRatingExtraction.model_validate(row)
        except ValidationError as exc:
            validation_errors.append({"note_id": note_id, "errors": exc.errors(include_context=False)})
            continue
        predictions[extraction.note_id] = extraction

    expected_trait_count = 0
    predicted_trait_count = 0
    exact_matches = 0
    within_one_matches = 0
    evidence_hits = 0

    for gold_row in gold:
        pred_row = predictions.get(gold_row.note_id)
        gold_by_trait = _rating_by_trait(gold_row.ratings)
        pred_by_trait = _rating_by_trait(pred_row.ratings) if pred_row else {}

        expected_trait_count += len(gold_by_trait)
        for trait, gold_rating in gold_by_trait.items():
            pred_rating = pred_by_trait.get(trait)
            if pred_rating is None:
                continue

            predicted_trait_count += 1
            if pred_rating.score == gold_rating.score:
                exact_matches += 1
            if abs(pred_rating.score - gold_rating.score) <= 1:
                within_one_matches += 1
            if pred_rating.evidence_span.lower() in gold_row.source_text.lower():
                evidence_hits += 1

    return EvalReport(
        total_notes=len(gold),
        expected_trait_count=expected_trait_count,
        predicted_trait_count=predicted_trait_count,
        trait_coverage=_safe_divide(predicted_trait_count, expected_trait_count),
        exact_score_agreement=_safe_divide(exact_matches, expected_trait_count),
        within_one_score_agreement=_safe_divide(within_one_matches, expected_trait_count),
        evidence_hit_rate=_safe_divide(evidence_hits, predicted_trait_count),
        invalid_output_count=len(validation_errors),
        validation_errors=validation_errors,
    )
