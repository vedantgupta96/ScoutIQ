"""Tests for the cap threshold module — tier ladders, apron proxies, and room-to-line math."""
from scoutiq.api.cap import (
    CAP_GROWTH_RATE,
    SeasonCapData,
    apron_values,
    cap_for,
    load_season_caps,
    room_to_lines,
)
from scoutiq.models import CapConstants
from fakes import FakeDB


# --------------------------------------------------------------------------- apron_values
def test_apron_values_prefers_stored_columns():
    row = CapConstants(
        season="2025-26", salary_cap=154_647_000, tax_line=187_895_000,
        first_apron=195_945_000, second_apron=207_824_000,
    )
    assert apron_values(row) == (195_945_000, 207_824_000)


def test_apron_values_falls_back_to_tax_line_proxy():
    row = CapConstants(
        season="2022-23", salary_cap=123_655_000, tax_line=150_000_000,
        first_apron=None, second_apron=None,
    )
    assert apron_values(row) == (154_800_000, 164_550_000)


def test_apron_values_handles_missing_row_or_tax_line():
    assert apron_values(None) == (None, None)
    row = CapConstants(season="2022-23", salary_cap=123_655_000, tax_line=None)
    assert apron_values(row) == (None, None)


# --------------------------------------------------------------------------- load_season_caps
def test_load_season_caps_skips_incomplete_rows_and_proxy_fills_aprons():
    complete = CapConstants(
        season="2025-26", salary_cap=154_647_000, tax_line=187_895_000,
        first_apron=195_945_000, second_apron=207_824_000,
    )
    no_tax_line = CapConstants(season="2020-21", salary_cap=109_140_000, tax_line=None)
    no_salary_cap = CapConstants(season="2021-22", salary_cap=None, tax_line=136_606_000)
    pre_cba = CapConstants(
        season="2022-23", salary_cap=123_655_000, tax_line=150_000_000,
        first_apron=None, second_apron=None,
    )
    db = FakeDB(caps=[complete, no_tax_line, no_salary_cap, pre_cba])

    caps = load_season_caps(db)

    assert set(caps) == {"2025-26", "2022-23"}
    assert caps["2025-26"].first_apron == 195_945_000
    assert caps["2025-26"].second_apron == 207_824_000
    assert caps["2022-23"].first_apron == 154_800_000
    assert caps["2022-23"].second_apron == 164_550_000


# --------------------------------------------------------------------------- cap_for
def test_cap_for_returns_stored_season():
    caps = {"2025-26": SeasonCapData("2025-26", 154_647_000, 187_895_000, 195_945_000, 207_824_000)}
    result = cap_for("2025-26", caps)
    assert result.is_projected is False
    assert result.salary_cap == 154_647_000


def test_cap_for_projects_unstored_future_season():
    base = SeasonCapData("2025-26", 154_647_000, 187_895_000, 195_945_000, 207_824_000)
    caps = {"2025-26": base}
    result = cap_for("2026-27", caps)
    factor = 1 + CAP_GROWTH_RATE
    assert result.season == "2026-27"
    assert result.is_projected is True
    assert result.salary_cap == int(base.salary_cap * factor)
    assert result.tax_line == int(base.tax_line * factor)
    assert result.first_apron == int(base.first_apron * factor)
    assert result.second_apron == int(base.second_apron * factor)


def test_cap_for_returns_none_for_empty_caps():
    assert cap_for("2025-26", {}) is None


# --------------------------------------------------------------------------- room_to_lines
def test_room_to_lines_signed_including_negative():
    rooms = room_to_lines(
        180_000_000, salary_cap=150_000_000, tax_line=170_000_000,
        first_apron=190_000_000, second_apron=210_000_000,
    )
    assert rooms.room_to_cap == -30_000_000
    assert rooms.room_to_tax == -10_000_000
    assert rooms.room_to_first_apron == 10_000_000
    assert rooms.room_to_second_apron == 30_000_000


def test_room_to_lines_none_thresholds_yield_none_fields():
    rooms = room_to_lines(100, salary_cap=None, tax_line=None, first_apron=None, second_apron=None)
    assert rooms.room_to_cap is None
    assert rooms.room_to_tax is None
    assert rooms.room_to_first_apron is None
    assert rooms.room_to_second_apron is None
