"""Tests for the valuation module, through its public interface."""
import pytest

import scoutiq.api.valuation as valuation_module
from scoutiq.api.valuation import classify_gap, value_players, valuation_verdict
from scoutiq.models import Player, PlayerSeason
from fakes import FakeDB


def _season(player_id: int, season: str) -> PlayerSeason:
    return PlayerSeason(
        player_id=player_id, season=season, team_id=None, age=25, gp=70, minutes=2000,
        box={"PTS": 1400}, advanced={"BPM": 1.0},
    )


def _const_predict(value_pct: float, lo_pct: float, hi_pct: float):
    def _predict(rows):
        return [
            {"value_pct": value_pct, "lo_pct": lo_pct, "hi_pct": hi_pct, "model_version": "test"}
            for _ in rows
        ]
    return _predict


def test_value_players_keys_by_player_and_season(monkeypatch):
    monkeypatch.setattr(valuation_module, "predict_many_from_features", _const_predict(20.0, 15.0, 25.0))
    db = FakeDB(
        players=[Player(player_id=1, full_name="A"), Player(player_id=2, full_name="B")],
        seasons=[_season(1, "2025-26"), _season(2, "2025-26")],
    )

    result = value_players(db, [(1, "2025-26"), (2, "2025-26")])

    assert set(result) == {(1, "2025-26"), (2, "2025-26")}
    assert result[(1, "2025-26")].value_pct == 20.0
    assert result[(2, "2025-26")].value_pct == 20.0


def test_value_players_timeline_one_player_two_seasons(monkeypatch):
    monkeypatch.setattr(valuation_module, "predict_many_from_features", _const_predict(18.0, 12.0, 24.0))
    db = FakeDB(
        players=[Player(player_id=1, full_name="A")],
        seasons=[_season(1, "2024-25"), _season(1, "2025-26")],
    )

    result = value_players(db, [(1, "2024-25"), (1, "2025-26")])

    assert set(result) == {(1, "2024-25"), (1, "2025-26")}


def test_value_players_degrades_to_empty_on_missing_artifact(monkeypatch):
    def _raise(rows):
        raise FileNotFoundError("model.joblib missing")

    monkeypatch.setattr(valuation_module, "predict_many_from_features", _raise)
    db = FakeDB(
        players=[Player(player_id=1, full_name="A")],
        seasons=[_season(1, "2025-26")],
    )

    assert value_players(db, [(1, "2025-26")]) == {}


def test_value_players_omits_targets_without_a_stats_season(monkeypatch):
    monkeypatch.setattr(valuation_module, "predict_many_from_features", _const_predict(20.0, 15.0, 25.0))
    db = FakeDB(
        players=[Player(player_id=1, full_name="A"), Player(player_id=2, full_name="B")],
        seasons=[_season(1, "2025-26")],  # player 2 has no loaded season
    )

    result = value_players(db, [(1, "2025-26"), (2, "2025-26")])

    assert set(result) == {(1, "2025-26")}


@pytest.mark.parametrize(
    "gap_pct,expected",
    [
        (3.0, ("Significant bargain", "positive")),
        (1.0, ("Bargain", "positive")),
        (0.0, ("Fair value", "neutral")),
        (-1.0, ("Slight overpay", "negative")),
        (-3.0, ("Overpaid", "negative")),
        (None, ("No data", "neutral")),
    ],
)
def test_classify_gap_ladder(gap_pct, expected):
    assert classify_gap(gap_pct) == expected


def test_valuation_verdict_cautions_minimum_veteran_impact_gap():
    label, tone, flags, caveat = valuation_verdict(
        gap_pct=15.76,
        actual_pct=1.48,
        features={
            "age": 37,
            "BPM": "-0.4",
            "WS48": ".009",
            "NET_RATING": -12.1,
            "TS_PCT": 0.528,
            "USG_PCT": 0.252,
        },
    )

    assert label == "Salary bargain"
    assert tone == "warning"
    assert "Age 35+" in flags
    assert "Minimum-salary gap" in flags
    assert "Negative BPM" in flags
    assert caveat
