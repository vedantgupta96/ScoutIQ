"""Schemas for scout-report rating extraction."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Trait(str, Enum):
    LEADERSHIP = "leadership"
    COACHABILITY = "coachability"
    WORK_ETHIC = "work_ethic"
    ATHLETICISM = "athleticism"
    DISCIPLINE = "discipline"
    BASKETBALL_IQ = "basketball_iq"


Confidence = Literal["low", "medium", "high"]


class ScoutRating(BaseModel):
    """One structured trait rating extracted from a scouting note."""

    model_config = ConfigDict(extra="forbid")

    trait: Trait
    score: int = Field(ge=1, le=5)
    confidence: Confidence
    evidence_span: str

    @field_validator("evidence_span")
    @classmethod
    def evidence_span_must_be_present(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence_span must be non-empty")
        return value


class ScoutRatingExtraction(BaseModel):
    """Structured ratings extracted for a single scouting note."""

    model_config = ConfigDict(extra="forbid")

    note_id: str
    player_name: str
    source_text: str
    ratings: list[ScoutRating]

    @field_validator("note_id", "player_name", "source_text")
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
