"""Null is_guaranteed means the guarantee is unknown: consumers flag it and keep the scheduled salary."""
from types import SimpleNamespace

from fakes import FakeDB
from test_extension import _contract_db, _patch_caps, _patch_value
from test_trade_assets import SurplusFakeDB, _cap, _year

from scoutiq.api import extension as ext
from scoutiq.api import guarantees
from scoutiq.api.routers.offseason import OffseasonContractYear
from scoutiq.api.routers.simulator import _scenario_delta
from scoutiq.api.trade_assets import contract_year_status, remaining_contract_surplus
from scoutiq.models import ContractYear


def test_guarantee_status_labels():
    assert guarantees.guarantee_status([True, False]) == "known"
    assert guarantees.guarantee_status([None, None]) == "unknown"
    assert guarantees.guarantee_status([True, None]) == "partial_unknown"
    assert guarantees.guarantee_status([]) == "known"


def test_trade_status_unknown_vs_false_and_option_precedence():
    assert contract_year_status(_year("2026-27", 1, guaranteed=None)) == "guarantee_unknown"
    assert contract_year_status(_year("2026-27", 1, guaranteed=False)) == "non_guaranteed"
    assert contract_year_status(_year("2026-27", 1, guaranteed=None, player_option=True)) == "player_option"


def test_surplus_committed_excludes_unknown_all_includes_and_flags():
    caps = {"2026-27": _cap("2026-27"), "2027-28": _cap("2027-28")}
    db = SurplusFakeDB([
        (_year("2026-27", 15_464_700), 1),
        (_year("2027-28", 15_464_700, guaranteed=None), 1),
    ])
    entry = remaining_contract_surplus(db, [1], {1: 20.0}, caps, from_season="2026-27")[1]
    assert entry.has_unknown_guarantees is True and entry.has_uncertain_years is True
    assert [y.status for y in entry.years] == ["guaranteed", "guarantee_unknown"]
    assert [y.committed for y in entry.years] == [True, False]
    assert [y.cap_hit_usd for y in entry.years] == [15_464_700, 15_464_700]
    assert entry.total_surplus_all_usd > entry.total_surplus_committed_usd


def test_surplus_without_unknowns_does_not_flag():
    caps = {"2026-27": _cap("2026-27")}
    entry = remaining_contract_surplus(SurplusFakeDB([(_year("2026-27", 1_000_000), 1)]), [1], {1: 20.0}, caps,
                                       from_season="2026-27")[1]
    assert entry.has_unknown_guarantees is False


def test_extension_flags_unknown_guarantee_but_keeps_eligibility(monkeypatch):
    _patch_value(monkeypatch, value_pct=25.0, lo=20.0, hi=30.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.15, is_guaranteed=None,
                     is_player_option=False, is_team_option=False),
    ])
    result = ext.decide_extension(db, 1)
    assert result.eligible is True and result.verdict == "Extend now"
    assert result.guarantee_unknown is True
    assert "Guarantee split unknown" in result.rationale
    assert result.current_pay_pct == 15.0


def test_extension_known_guarantee_has_no_flag(monkeypatch):
    _patch_value(monkeypatch, value_pct=25.0, lo=20.0, hi=30.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.15, is_guaranteed=True,
                     is_player_option=False, is_team_option=False),
    ])
    result = ext.decide_extension(db, 1)
    assert result.guarantee_unknown is False and "Guarantee split unknown" not in result.rationale


def test_simulator_delta_sums_only_confirmed_guarantees_and_flags_unknown():
    years = [
        SimpleNamespace(cap_hit_usd=10, is_guaranteed=True),
        SimpleNamespace(cap_hit_usd=20, is_guaranteed=None),
        SimpleNamespace(cap_hit_usd=30, is_guaranteed=False),
    ]
    s = SimpleNamespace(years=years, proposed_aav_pct=10.0, value_gap_pct=1.0, apron_outlook=None)
    delta = _scenario_delta(s)
    assert (delta.total_cap_hit_usd, delta.guaranteed_cap_hit_usd, delta.guarantee_unknown_usd) == (60, 10, 20)
    assert delta.requires_known_guarantee is True
    s.years = years[:1] + years[2:]
    assert _scenario_delta(s).requires_known_guarantee is False


def test_offseason_year_schema_accepts_null_guarantee():
    year = OffseasonContractYear(season="2026-27", cap_hit_usd=5, cap_hit_pct=1.0, is_guaranteed=None,
                                 is_player_option=False, is_team_option=False, is_projected_cap=False)
    assert year.is_guaranteed is None and year.cap_hit_usd == 5
