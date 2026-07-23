"""Tests for the extension-decision logic module.

Pure logic tested against the module directly, with its DB collaborators
(value_player_detail, load_season_caps) monkeypatched — mirrors test_free_agency.py.
"""
from decimal import Decimal

from fakes import FakeDB

from scoutiq.api import extension as ext
from scoutiq.api.cap import SeasonCapData
from scoutiq.api.valuation import Valuation
from scoutiq.models import Contract, ContractYear, Player

CAPS = {
    "2026-27": SeasonCapData("2026-27", 161_606_000, 196_350_000, 204_762_000, 217_176_000),
}


def _valuation(value_pct, lo_pct, hi_pct):
    return Valuation(
        season="2025-26", value_pct=value_pct, lo_pct=lo_pct, hi_pct=hi_pct,
        actual_usd=None, actual_pct=None, gap_pct=None, salary_cap=None, value_usd=None,
        model_version="test", verdict_label="", verdict_tone="neutral",
        caution_flags=[], caveat=None, stats=None,
    )


def _contract_db(*, year_rows, player_id=1):
    contract = Contract(id=1, player_id=player_id, season_start="2023-24", years=len(year_rows))
    return FakeDB(
        players=[Player(player_id=player_id, full_name="Test Player")],
        contracts=[contract],
        contract_years=list(year_rows),
    )


def _patch_value(monkeypatch, value_pct=None, lo=None, hi=None, attribution=None, raise_lookup=False):
    def fake(db, player_id, season):
        if raise_lookup:
            raise LookupError("no stats")
        return _valuation(value_pct, lo, hi), {}, attribution
    monkeypatch.setattr(ext, "value_player_detail", fake)


def _patch_caps(monkeypatch, caps=CAPS):
    monkeypatch.setattr(ext, "load_season_caps", lambda db: dict(caps))


def test_eligible_underpaid_extend_now(monkeypatch):
    _patch_value(monkeypatch, value_pct=25.0, lo=20.0, hi=30.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.eligible is True
    assert result.verdict == "Extend now" and result.tone == "positive"
    assert result.current_pay_pct == 15.0
    assert result.gap_pct == 10.0
    assert result.entering_season == "2027-28"
    assert result.projected_cap_usd == 168_878_270  # projected forward from 2026-27 at the escalator
    assert result.projected_aav_usd == round(0.25 * 168_878_270)


def test_decimal_cap_pct_does_not_crash(monkeypatch):
    """Live rows return cap_pct as Decimal (Numeric column); it must be coerced to float
    before arithmetic with the float value_pct. Regression for the float-minus-Decimal 500."""
    _patch_value(monkeypatch, value_pct=25.0, lo=20.0, hi=30.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=Decimal("0.15"),
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.eligible is True
    assert result.current_pay_pct == 15.0
    assert result.gap_pct == 10.0
    assert isinstance(result.current_pay_pct, float)


def test_eligible_underpaid_projected_aav_from_stored_cap(monkeypatch):
    _patch_value(monkeypatch, value_pct=25.0, lo=20.0, hi=30.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2027-28", cap_pct=0.15,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.entering_season == "2028-29"
    assert result.projected_aav_usd == round(result.value_pct / 100 * result.projected_cap_usd)
    assert result.projected_aav_lo_usd == round(result.value_lo_pct / 100 * result.projected_cap_usd)
    assert result.projected_aav_hi_usd == round(result.value_hi_pct / 100 * result.projected_cap_usd)
    assert result.verdict == "Extend now" and result.tone == "positive"


def test_eligible_overpaid_dont_extend(monkeypatch):
    _patch_value(monkeypatch, value_pct=10.0, lo=8.0, hi=12.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.verdict == "Don't extend" and result.tone == "negative"
    assert result.gap_pct == -10.0


def test_eligible_within_threshold_fair(monkeypatch):
    _patch_value(monkeypatch, value_pct=20.4, lo=18.0, hi=22.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.verdict == "Fair — extend at market or wait" and result.tone == "neutral"


def test_impending_free_agent_ineligible(monkeypatch):
    _patch_value(monkeypatch, value_pct=20.0, lo=18.0, hi=22.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2025-26", cap_pct=0.20,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.eligible is False
    assert "impending free agent" in result.ineligible_reason
    assert result.verdict == "Not extension-eligible"
    assert result.projected_aav_usd is None


def test_option_only_remaining_ineligible(monkeypatch):
    _patch_value(monkeypatch, value_pct=20.0, lo=18.0, hi=22.0)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                     is_player_option=True, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.eligible is False
    assert "option decision" in result.ineligible_reason


def test_no_model_value_no_crash(monkeypatch):
    _patch_value(monkeypatch, raise_lookup=True)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.eligible is True
    assert result.value_pct is None
    assert result.verdict == "No model value" and result.tone == "neutral"


def test_trajectory_note_rising(monkeypatch):
    _patch_value(
        monkeypatch, value_pct=20.0, lo=18.0, hi=22.0,
        attribution=[{"group": "trajectory", "label": "Trajectory", "delta_pct": 2.5}],
    )
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.trajectory_note == "Trajectory is rising — waiting likely raises the market price."


def test_trajectory_note_none_without_attribution(monkeypatch):
    _patch_value(monkeypatch, value_pct=20.0, lo=18.0, hi=22.0, attribution=None)
    _patch_caps(monkeypatch)
    db = _contract_db(year_rows=[
        ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                     is_player_option=False, is_team_option=False),
    ])

    result = ext.decide_extension(db, 1)

    assert result.trajectory_note is None


# --------------------------------------------------------------------------- batch_extension_summaries
def _patch_value_players(monkeypatch, values: dict[int, float]):
    def fake(db, targets):
        return {
            (player_id, season): _valuation(values[player_id], values[player_id], values[player_id])
            for player_id, season in targets
            if player_id in values
        }
    monkeypatch.setattr(ext, "value_players", fake)


def _multi_contract_db(*, players, contracts, contract_years):
    return FakeDB(players=players, contracts=contracts, contract_years=contract_years)


def test_batch_extension_summaries_eligible_with_value(monkeypatch):
    _patch_value_players(monkeypatch, {1: 25.0})
    db = _multi_contract_db(
        players=[Player(player_id=1, full_name="A")],
        contracts=[Contract(id=1, player_id=1, season_start="2023-24", years=1)],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
        ],
    )

    summaries = ext.batch_extension_summaries(db, [1])

    assert summaries[1].eligible is True
    assert summaries[1].has_model_value is True
    assert summaries[1].value_pct == 25.0
    assert summaries[1].current_pay_pct == 15.0
    assert summaries[1].gap_pct == 10.0
    assert summaries[1].verdict == "Extend now"
    assert summaries[1].tone == "positive"
    assert summaries[1].final_contract_season == "2026-27"


def test_batch_extension_summaries_verdict_parity_with_extension_verdict(monkeypatch):
    _patch_value_players(monkeypatch, {1: 20.4})
    db = _multi_contract_db(
        players=[Player(player_id=1, full_name="A")],
        contracts=[Contract(id=1, player_id=1, season_start="2023-24", years=1)],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.20,
                         is_player_option=False, is_team_option=False),
        ],
    )

    summaries = ext.batch_extension_summaries(db, [1])
    expected_verdict, expected_tone, _rationale, expected_gap = ext.extension_verdict(20.4, 20.0)

    assert summaries[1].verdict == expected_verdict
    assert summaries[1].tone == expected_tone
    assert summaries[1].gap_pct == expected_gap


def test_batch_extension_summaries_ineligible_impending_fa(monkeypatch):
    _patch_value_players(monkeypatch, {1: 25.0})
    db = _multi_contract_db(
        players=[Player(player_id=1, full_name="A")],
        contracts=[Contract(id=1, player_id=1, season_start="2023-24", years=1)],
        contract_years=[
            ContractYear(contract_id=1, season="2025-26", cap_pct=0.20,
                         is_player_option=False, is_team_option=False),
        ],
    )

    summaries = ext.batch_extension_summaries(db, [1])

    assert summaries[1].eligible is False
    assert summaries[1].has_model_value is False
    assert summaries[1].current_pay_pct is None
    assert summaries[1].verdict is None


def test_batch_extension_summaries_has_model_value_false_when_unvalued(monkeypatch):
    _patch_value_players(monkeypatch, {})
    db = _multi_contract_db(
        players=[Player(player_id=1, full_name="A")],
        contracts=[Contract(id=1, player_id=1, season_start="2023-24", years=1)],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
        ],
    )

    summaries = ext.batch_extension_summaries(db, [1])

    assert summaries[1].eligible is True
    assert summaries[1].has_model_value is False
    assert summaries[1].value_pct is None
    assert summaries[1].verdict is None
    assert summaries[1].current_pay_pct == 15.0


def test_batch_extension_summaries_file_not_found_returns_eligibility_without_raising(monkeypatch):
    def raise_fnf(db, targets):
        raise FileNotFoundError("model artifact missing")
    monkeypatch.setattr(ext, "value_players", raise_fnf)

    db = _multi_contract_db(
        players=[Player(player_id=1, full_name="A"), Player(player_id=2, full_name="B")],
        contracts=[
            Contract(id=1, player_id=1, season_start="2023-24", years=1),
            Contract(id=2, player_id=2, season_start="2023-24", years=1),
        ],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
            ContractYear(contract_id=2, season="2025-26", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
        ],
    )

    summaries = ext.batch_extension_summaries(db, [1, 2])

    assert summaries[1].eligible is True
    assert summaries[1].current_pay_pct == 15.0
    assert summaries[1].has_model_value is False
    assert summaries[1].verdict is None
    assert summaries[2].eligible is False
    assert summaries[2].has_model_value is False


def test_batch_extension_summaries_empty_player_ids():
    assert ext.batch_extension_summaries(None, []) == {}
