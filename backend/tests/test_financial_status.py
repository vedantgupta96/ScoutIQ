from scoutiq.api.financial_status import CURRENT_SEASON, contract_coverage


def test_current_season_is_in_progress_season():
    assert CURRENT_SEASON == "2026-27"


def test_covers_current_season():
    assert contract_coverage(["2025-26", "2026-27", "2027-28"]) == "current"
    assert contract_coverage(["2026-27"]) == "current"


def test_expired_when_all_seasons_before_current():
    assert contract_coverage(["2024-25", "2025-26"]) == "expired"


def test_future_only_when_all_seasons_after_current():
    assert contract_coverage(["2027-28", "2028-29"]) == "future_only"


def test_no_years():
    assert contract_coverage([]) == "no_years"


def test_mixed_missing_current_season_decided_by_max():
    assert contract_coverage(["2024-25", "2025-26", "2027-28"]) == "future_only"
    assert contract_coverage(["2024-25", "2025-26"], current_season="2026-27") == "expired"


def test_explicit_current_season_override():
    assert contract_coverage(["2025-26"], current_season="2025-26") == "current"
