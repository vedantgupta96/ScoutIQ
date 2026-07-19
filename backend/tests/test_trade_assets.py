"""Trade-asset layer: pick value curve, Stepien legality, contract surplus, team-state lens."""
from scoutiq.api.cap import SeasonCapData
from scoutiq.api.trade_assets import (
    DEFAULT_EXPECTED_PICK,
    PICK_VALUE_ANCHORS,
    discount_factor,
    pick_surplus_pct,
    remaining_contract_surplus,
    roster_count_legality,
    stepien_check,
    value_pick,
)
from scoutiq.models import Contract, ContractYear, DraftPick


def _cap(season: str, salary_cap: int = 154_647_000) -> SeasonCapData:
    return SeasonCapData(
        season=season, salary_cap=salary_cap, tax_line=int(salary_cap * 1.21),
        first_apron=int(salary_cap * 1.27), second_apron=int(salary_cap * 1.34),
        is_projected=False,
    )


# ---- curve -----------------------------------------------------------------

def test_pick_curve_is_monotonically_decreasing():
    values = [pick_surplus_pct(p) for p in range(1, 61)]
    assert values == sorted(values, reverse=True)
    assert values[0] == 20.0          # pick 1 anchors the scale
    assert values[-1] < 1.0           # late seconds are near-zero


def test_pick_curve_interpolates_between_anchors():
    lo, hi = pick_surplus_pct(10), pick_surplus_pct(14)
    assert hi < pick_surplus_pct(12) < lo


def test_anchors_cover_both_rounds():
    picks = [p for p, _ in PICK_VALUE_ANCHORS]
    assert min(picks) == 1 and max(picks) == 60


# ---- pick valuation --------------------------------------------------------

def _pick(**overrides) -> DraftPick:
    defaults = dict(id=1, draft_year=2026, round=1, original_team_id=1, current_team_id=1,
                    protected_top=None, swap_rights_team_id=None, converts_to=None,
                    source="default-ownership")
    defaults.update(overrides)
    return DraftPick(**defaults)


def test_value_pick_defaults_to_mid_round():
    value = value_pick(_pick(), upcoming_draft_year=2026, team_state="neutral",
                       salary_cap=154_647_000)
    assert value.expected_pick == DEFAULT_EXPECTED_PICK[1]
    assert value.years_out == 0
    assert value.raw_pct == value.discounted_pct  # no discount at zero years out


def test_value_pick_discounts_future_years_by_team_state():
    contender = value_pick(_pick(draft_year=2030), upcoming_draft_year=2026,
                           team_state="contending", salary_cap=154_647_000)
    rebuilder = value_pick(_pick(draft_year=2030), upcoming_draft_year=2026,
                           team_state="rebuilding", salary_cap=154_647_000)
    assert contender.raw_pct == rebuilder.raw_pct
    assert contender.discounted_pct < rebuilder.discounted_pct  # contenders devalue the future


def test_value_pick_protection_shifts_and_defers():
    protected = value_pick(_pick(protected_top=10), upcoming_draft_year=2026,
                           team_state="neutral", salary_cap=154_647_000, expected_pick=8)
    assert protected.conveyed_pick == 11    # never receive a pick inside protection
    assert protected.deferral_years == 1    # roll-risk discount year
    unprotected = value_pick(_pick(), upcoming_draft_year=2026,
                             team_state="neutral", salary_cap=154_647_000, expected_pick=8)
    assert protected.discounted_pct < unprotected.discounted_pct


def test_second_round_pick_values_on_second_round_tail():
    second = value_pick(_pick(round=2), upcoming_draft_year=2026,
                        team_state="neutral", salary_cap=154_647_000)
    assert second.raw_pct <= pick_surplus_pct(31)


# ---- Stepien ---------------------------------------------------------------

WINDOW = list(range(2026, 2033))


def test_stepien_pass_when_alternating_years_remain():
    result = stepien_check(
        owned_first_years_after={2027, 2029, 2031},
        outgoing_first_years={2026, 2028, 2030, 2032},
        outgoing_any_protected=False,
        window_years=WINDOW,
    )
    assert result.status == "pass"


def test_stepien_fails_on_consecutive_missing_years():
    result = stepien_check(
        owned_first_years_after={2028, 2029, 2030, 2031, 2032},
        outgoing_first_years={2026, 2027},
        outgoing_any_protected=False,
        window_years=WINDOW,
    )
    assert result.status == "fail"
    assert "2026 and 2027" in result.reasons[0]


def test_stepien_protected_outgoing_needs_review():
    result = stepien_check(
        owned_first_years_after={2027, 2028, 2029, 2030, 2031, 2032},
        outgoing_first_years={2026},
        outgoing_any_protected=True,
        window_years=WINDOW,
    )
    assert result.status == "needs-review"


def test_stepien_not_applicable_without_outgoing_firsts():
    result = stepien_check(
        owned_first_years_after=set(WINDOW),
        outgoing_first_years=set(),
        outgoing_any_protected=False,
        window_years=WINDOW,
    )
    assert result.status == "not-applicable"


# ---- contract surplus ------------------------------------------------------

class FakeRow:
    def __init__(self, values):
        self._values = values

    def __iter__(self):
        return iter(self._values)


class SurplusFakeDB:
    """Returns (ContractYear, player_id) rows like the joined select."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, stmt):
        class Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return Result(self.rows)


def _year(season: str, aav: int, guaranteed: bool = True) -> ContractYear:
    return ContractYear(contract_id=1, season=season, aav=aav, cap_pct=None,
                        is_guaranteed=guaranteed, is_player_option=False, is_team_option=False)


def test_contract_surplus_sums_value_minus_pay():
    caps = {"2025-26": _cap("2025-26"), "2026-27": _cap("2026-27")}
    db = SurplusFakeDB([(_year("2025-26", 15_464_700), 1), (_year("2026-27", 15_464_700), 1)])

    result = remaining_contract_surplus(
        db, [1], {1: 20.0}, caps, from_season="2025-26", team_state="neutral"
    )

    entry = result[1]
    assert len(entry.years) == 2
    # value 20% - pay 10% = 10% of cap ≈ $15.46M year one; year two discounted 8%.
    assert entry.years[0].surplus_pct == 10.0
    assert entry.years[0].discounted_surplus_usd == 15_464_700
    assert entry.years[1].discounted_surplus_usd == int(round(15_464_700 * 0.92))
    assert entry.expiring is False


def test_contract_surplus_flags_expiring_and_handles_missing_value():
    caps = {"2025-26": _cap("2025-26")}
    db = SurplusFakeDB([(_year("2025-26", 30_000_000), 7)])

    result = remaining_contract_surplus(
        db, [7], {}, caps, from_season="2025-26", team_state="neutral"
    )

    entry = result[7]
    assert entry.expiring is True
    assert entry.total_surplus_usd == 0
    assert entry.years[0].surplus_pct is None  # no model value -> honest absence


def test_discount_factor_orders_team_states():
    assert discount_factor("contending", 3) < discount_factor("neutral", 3) < discount_factor("rebuilding", 3)
    assert discount_factor("neutral", 0) == 1.0


# ---- roster-count legality (Phase D2) --------------------------------------

def test_roster_count_pass_within_bounds():
    r = roster_count_legality(standard_before=14, standard_outgoing=1, standard_incoming=1, two_way_count=2)
    assert r.status == "pass"
    assert r.standard_after == 14 and r.net_change == 0


def test_roster_count_over_max_needs_review():
    r = roster_count_legality(standard_before=15, standard_outgoing=1, standard_incoming=3, two_way_count=1)
    assert r.status == "needs-review"
    assert r.standard_after == 17 and r.net_change == 2
    assert "above the 15-man limit" in r.reasons[0]


def test_roster_count_under_min_needs_review():
    r = roster_count_legality(standard_before=14, standard_outgoing=2, standard_incoming=0, two_way_count=1)
    assert r.status == "needs-review"
    assert r.standard_after == 12 and r.net_change == -2
    assert "below the 14-man minimum" in r.reasons[0]


def test_roster_count_net_change_is_exact_regardless_of_absolute():
    # A 2-for-2 swap never changes the count, so it always passes even near the limit.
    r = roster_count_legality(standard_before=15, standard_outgoing=2, standard_incoming=2, two_way_count=3)
    assert r.status == "pass" and r.net_change == 0 and r.standard_after == 15
