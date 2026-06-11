"""Unit tests for the shared season-label parsing/validation helpers."""
import pytest

from scoutiq.api.season import is_valid_season, next_season, validate_season


@pytest.mark.parametrize("season", ["2025-26", "1999-00", "2023-24", "2099-00"])
def test_is_valid_season_accepts_well_formed_labels(season):
    assert is_valid_season(season) is True


@pytest.mark.parametrize(
    "season",
    ["banana", "2025", "2025-2026", "25-26", "2025-27", "2025-25", "", "2025_26"],
)
def test_is_valid_season_rejects_malformed_or_inconsistent_labels(season):
    assert is_valid_season(season) is False


def test_validate_season_returns_input_when_valid():
    assert validate_season("2025-26") == "2025-26"


def test_validate_season_raises_with_clear_message():
    with pytest.raises(ValueError, match="expected 'YYYY-YY'"):
        validate_season("banana")


def test_next_season_rolls_year_and_century():
    assert next_season("2025-26") == "2026-27"
    assert next_season("1999-00") == "2000-01"


def test_next_season_returns_none_for_malformed_input():
    assert next_season("banana") is None
