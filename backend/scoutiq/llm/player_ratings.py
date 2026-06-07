"""Fixture-backed player scout-rating aggregation."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scoutiq.llm.eval_scout_ratings import load_jsonl
from scoutiq.llm.schemas import ScoutRating, Trait

DEFAULT_PLAYER_REPORTS_PATH = Path(__file__).resolve().parent / "eval_data" / "player_scout_reports_fixture.jsonl"


class PlayerScoutReport(BaseModel):
    """Synthetic scout report fixture keyed to a known NBA player_id."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    player_id: int
    player_name: str
    source_label: str
    source_text: str
    ratings: list[ScoutRating]

    @field_validator("report_id", "player_name", "source_label", "source_text")
    @classmethod
    def text_fields_must_be_present(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must be non-empty")
        return value

    @field_validator("ratings")
    @classmethod
    def traits_must_be_unique(cls, ratings: list[ScoutRating]) -> list[ScoutRating]:
        traits = [rating.trait for rating in ratings]
        if len(traits) != len(set(traits)):
            raise ValueError("ratings must not contain duplicate traits")
        return ratings


class ConfidenceMix(BaseModel):
    low: int = 0
    medium: int = 0
    high: int = 0


class AggregatedTraitRating(BaseModel):
    trait: Trait
    average_score: float = Field(ge=1, le=5)
    report_count: int
    confidence_mix: ConfidenceMix
    evidence: list[str]


class PlayerScoutRatings(BaseModel):
    player_id: int
    player_name: str
    source_mode: str
    report_count: int
    traits: list[AggregatedTraitRating]
    reports: list[PlayerScoutReport]
    caveat: str


def load_player_reports(path: Path = DEFAULT_PLAYER_REPORTS_PATH) -> list[PlayerScoutReport]:
    return [PlayerScoutReport.model_validate(row) for row in load_jsonl(path)]


def aggregate_player_scout_ratings(
    player_id: int,
    player_name: str,
    reports: list[PlayerScoutReport],
) -> PlayerScoutRatings:
    """Aggregate synthetic scout-report ratings for a player."""
    player_reports = [report for report in reports if report.player_id == player_id]
    by_trait: dict[Trait, list[ScoutRating]] = defaultdict(list)

    for report in player_reports:
        for rating in report.ratings:
            by_trait[rating.trait].append(rating)

    traits: list[AggregatedTraitRating] = []
    for trait in Trait:
        ratings = by_trait.get(trait, [])
        if not ratings:
            continue
        confidence_counts: dict[str, Any] = {"low": 0, "medium": 0, "high": 0}
        for rating in ratings:
            confidence_counts[rating.confidence] += 1
        traits.append(AggregatedTraitRating(
            trait=trait,
            average_score=round(sum(rating.score for rating in ratings) / len(ratings), 2),
            report_count=len(ratings),
            confidence_mix=ConfidenceMix(**confidence_counts),
            evidence=[rating.evidence_span for rating in ratings[:3]],
        ))

    return PlayerScoutRatings(
        player_id=player_id,
        player_name=player_reports[0].player_name if player_reports else player_name,
        source_mode="synthetic_fixture",
        report_count=len(player_reports),
        traits=traits,
        reports=player_reports,
        caveat=(
            "Synthetic, project-authored scout-report fixture. This is a UI/API contract preview, "
            "not real scouting coverage or live LLM output."
        ),
    )
