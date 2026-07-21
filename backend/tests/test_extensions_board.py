"""Tests for the league-wide extensions board ranking logic.

Mirrors test_extension.py: pure-ish logic tested against the module directly, with
value_players monkeypatched — no live DB, no model artifact.
"""
from fakes import FakeDB

from scoutiq.api import extension as ext
from scoutiq.api.valuation import Valuation
from scoutiq.models import Contract, ContractYear, Player


def _valuation(value_pct):
    return Valuation(
        season="2025-26", value_pct=value_pct, lo_pct=value_pct, hi_pct=value_pct,
        actual_usd=None, actual_pct=None, gap_pct=None, salary_cap=None, value_usd=None,
        model_version="test", verdict_label="", verdict_tone="neutral",
        caution_flags=[], caveat=None, stats=None,
    )


def _patch_value_players(monkeypatch, values: dict[int, float]):
    def fake(db, targets):
        return {
            (player_id, season): _valuation(values[player_id])
            for player_id, season in targets
            if player_id in values
        }
    monkeypatch.setattr(ext, "value_players", fake)


def _rostered_db(*, players, contracts, contract_years, rostered_ids):
    def on_scalars(sql: str):
        if "current_team_id IS NOT NULL" in sql:
            return list(rostered_ids)
        return None

    return FakeDB(
        players=players,
        contracts=contracts,
        contract_years=contract_years,
        on_scalars=on_scalars,
    )


def test_ranks_two_eligible_players_by_gap_desc(monkeypatch):
    _patch_value_players(monkeypatch, {1: 25.0, 2: 10.0})
    db = _rostered_db(
        players=[
            Player(player_id=1, full_name="A"),
            Player(player_id=2, full_name="B"),
        ],
        contracts=[
            Contract(id=1, player_id=1, season_start="2023-24", years=1),
            Contract(id=2, player_id=2, season_start="2023-24", years=1),
        ],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
            ContractYear(contract_id=2, season="2026-27", cap_pct=0.09,
                         is_player_option=False, is_team_option=False),
        ],
        rostered_ids=[1, 2],
    )

    candidates = ext.rank_extension_candidates(db)

    assert [c.player_id for c in candidates] == [1, 2]
    assert candidates[0].gap_pct == 10.0
    assert candidates[1].gap_pct == 1.0


def test_excludes_impending_fa_and_option_only_tail(monkeypatch):
    _patch_value_players(monkeypatch, {1: 25.0, 2: 25.0, 3: 25.0})
    db = _rostered_db(
        players=[
            Player(player_id=1, full_name="Eligible"),
            Player(player_id=2, full_name="ImpendingFA"),
            Player(player_id=3, full_name="OptionOnly"),
        ],
        contracts=[
            Contract(id=1, player_id=1, season_start="2023-24", years=1),
            Contract(id=2, player_id=2, season_start="2023-24", years=1),
            Contract(id=3, player_id=3, season_start="2023-24", years=1),
        ],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
            ContractYear(contract_id=2, season="2025-26", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
            ContractYear(contract_id=3, season="2026-27", cap_pct=0.15,
                         is_player_option=True, is_team_option=False),
        ],
        rostered_ids=[1, 2, 3],
    )

    candidates = ext.rank_extension_candidates(db)

    assert [c.player_id for c in candidates] == [1]


def test_skips_player_with_no_valuation(monkeypatch):
    _patch_value_players(monkeypatch, {1: 25.0})
    db = _rostered_db(
        players=[
            Player(player_id=1, full_name="Valued"),
            Player(player_id=2, full_name="Unvalued"),
        ],
        contracts=[
            Contract(id=1, player_id=1, season_start="2023-24", years=1),
            Contract(id=2, player_id=2, season_start="2023-24", years=1),
        ],
        contract_years=[
            ContractYear(contract_id=1, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
            ContractYear(contract_id=2, season="2026-27", cap_pct=0.15,
                         is_player_option=False, is_team_option=False),
        ],
        rostered_ids=[1, 2],
    )

    candidates = ext.rank_extension_candidates(db)

    assert [c.player_id for c in candidates] == [1]


def test_extension_verdict_matches_decide_extension_behavior():
    verdict, tone, rationale, gap_pct = ext.extension_verdict(25.0, 15.0)
    assert (verdict, tone, gap_pct) == ("Extend now", "positive", 10.0)
    assert "extending now locks in below-market cost" in rationale

    verdict, tone, rationale, gap_pct = ext.extension_verdict(10.0, 20.0)
    assert (verdict, tone, gap_pct) == ("Don't extend", "negative", -10.0)

    verdict, tone, rationale, gap_pct = ext.extension_verdict(20.4, 20.0)
    assert (verdict, tone, gap_pct) == ("Fair — extend at market or wait", "neutral", 0.4)

    verdict, tone, rationale, gap_pct = ext.extension_verdict(25.0, None)
    assert (verdict, tone, gap_pct) == ("Extend at market", "neutral", None)
