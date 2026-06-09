"""Player scout-rating aggregation — DB-backed (Sonar→Claude) with a synthetic-fixture fallback."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoutiq.llm.eval_scout_ratings import load_jsonl
from scoutiq.llm.schemas import ScoutRating, Trait
from scoutiq.models import ScoutReport

DEFAULT_PLAYER_REPORTS_PATH = Path(__file__).resolve().parent / "eval_data" / "player_scout_reports_fixture.jsonl"

FIXTURE_CAVEAT = (
    "Synthetic, project-authored scout-report fixture. This is a UI/API contract preview, "
    "not real scouting coverage or live LLM output."
)
DB_CAVEAT = (
    "{n} Perplexity Sonar–sourced report{s}, with ratings extracted by Claude and schema-validated. "
    "Ratings are model-extracted from public narratives, not official scouting — see the cited sources."
)


class PlayerScoutReport(BaseModel):
    """A scout report (synthetic fixture or Sonar-sourced) keyed to a known NBA player_id."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    player_id: int
    player_name: str
    source_label: str
    source_text: str
    ratings: list[ScoutRating]
    citations: list[str] = []
    fetched_at: str | None = None

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
    citations: list[str] = []
    last_fetched: str | None = None


def load_player_reports(path: Path = DEFAULT_PLAYER_REPORTS_PATH) -> list[PlayerScoutReport]:
    return [PlayerScoutReport.model_validate(row) for row in load_jsonl(path)]


def _aggregate_traits(reports: list[PlayerScoutReport]) -> list[AggregatedTraitRating]:
    """Average trait scores across a player's reports (the shared aggregation core)."""
    by_trait: dict[Trait, list[ScoutRating]] = defaultdict(list)
    for report in reports:
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
    return traits


def aggregate_player_scout_ratings(
    player_id: int,
    player_name: str,
    reports: list[PlayerScoutReport],
) -> PlayerScoutRatings:
    """Aggregate synthetic fixture scout-report ratings for a player."""
    player_reports = [report for report in reports if report.player_id == player_id]
    return PlayerScoutRatings(
        player_id=player_id,
        player_name=player_reports[0].player_name if player_reports else player_name,
        source_mode="synthetic_fixture",
        report_count=len(player_reports),
        traits=_aggregate_traits(player_reports),
        reports=player_reports,
        caveat=FIXTURE_CAVEAT,
    )


def aggregate_from_db(db: Session, player_id: int, player_name: str) -> PlayerScoutRatings | None:
    """Aggregate real Sonar→Claude ratings from the DB, or None if the player has no coverage."""
    db_reports = db.scalars(
        select(ScoutReport).where(ScoutReport.player_id == player_id).order_by(ScoutReport.season)
    ).all()
    if not db_reports:
        return None

    reports = [
        PlayerScoutReport(
            report_id=r.report_id,
            player_id=r.player_id,
            player_name=player_name,
            source_label=r.source_label,
            source_text=r.source_text,
            ratings=[
                ScoutRating(
                    trait=rating.trait,
                    score=rating.score,
                    confidence=rating.confidence,
                    evidence_span=rating.evidence_span,
                )
                for rating in r.ratings
            ],
            citations=r.citations or [],
            fetched_at=r.fetched_at.isoformat() if r.fetched_at else None,
        )
        for r in db_reports
    ]

    citations = list(dict.fromkeys(c for report in reports for c in report.citations))
    fetched = [r.fetched_at for r in reports if r.fetched_at]
    n = len(reports)
    return PlayerScoutRatings(
        player_id=player_id,
        player_name=player_name,
        source_mode="sonar_claude_db",
        report_count=n,
        traits=_aggregate_traits(reports),
        reports=reports,
        caveat=DB_CAVEAT.format(n=n, s="" if n == 1 else "s"),
        citations=citations,
        last_fetched=max(fetched) if fetched else None,
    )
