"""Unit tests for the strategy-backtest engine (docs/10 Phase 2).

Synthetic panels with hand-computable surplus: the production→value bridge, realized-surplus
math over a horizon, survivorship handling, eligibility filters, deterministic ranking, and
alpha vs the random benchmark."""
from scoutiq.backtest.engine import (
    PCT_OF_CAP_PER_WIN,
    SeasonStat,
    StrategySpec,
    make_panel,
    production_value_pct,
    run_backtest,
)

SEASONS = ["S1", "S2", "S3"]


def stat(pid, season, *, mpg=30.0, gp=70, age=25, ws=None, vorp=None, bpm=None,
         value_pct=None, actual_pct=None, gap_pct=None, position="G", name=None):
    return SeasonStat(
        player_id=pid, full_name=name or f"P{pid}", season=season, position=position,
        age=age, gp=gp, mpg=mpg, ws=ws, vorp=vorp, bpm=bpm,
        value_pct=value_pct, actual_pct=actual_pct, gap_pct=gap_pct,
    )


def test_production_value_bridge():
    assert production_value_pct(stat(1, "S1", ws=10)) == 10 * PCT_OF_CAP_PER_WIN   # 25.0
    assert production_value_pct(stat(1, "S1", ws=None, vorp=3)) == 3 * 2.7 * PCT_OF_CAP_PER_WIN
    assert production_value_pct(stat(1, "S1", ws=None, vorp=None)) is None
    assert production_value_pct(stat(1, "S1", ws=-1)) == -PCT_OF_CAP_PER_WIN       # negative WS honestly negative


def test_realized_surplus_over_horizon():
    # P1 is picked at S1 (gap signal), then produces across S2 + S3.
    panel = make_panel([
        stat(1, "S1", value_pct=20, actual_pct=5, gap_pct=15, ws=8),
        stat(1, "S2", ws=10, actual_pct=6),   # prod 25 − 6 = 19
        stat(1, "S3", ws=8, actual_pct=7),    # prod 20 − 7 = 13
    ])
    spec = StrategySpec(signal="gap", portfolio_size=1, horizon=2, start_season="S1", end_season="S1")
    res = run_backtest(panel, spec)
    assert res.decision_seasons == ["S1"]
    assert res.n_picks == 1
    assert res.picks[0]["realized_surplus_pct"] == 32.0   # 19 + 13
    assert res.picks[0]["seasons_realized"] == 2
    assert res.picks[0]["hit"] is True
    assert res.total_surplus_pct == 32.0


def test_survivorship_missing_seasons_contribute_zero():
    # Picked player has no S2/S3 rows (left the league): surplus 0, not dropped.
    panel = make_panel([
        stat(1, "S1", value_pct=30, actual_pct=2, gap_pct=28, ws=5),
        stat(2, "S2", ws=5, actual_pct=5),  # filler so S1 has a future season
    ])
    spec = StrategySpec(signal="gap", portfolio_size=1, horizon=2, start_season="S1", end_season="S1")
    res = run_backtest(panel, spec)
    assert res.picks[0]["player_id"] == 1
    assert res.picks[0]["realized_surplus_pct"] == 0.0
    assert res.picks[0]["seasons_realized"] == 0
    assert res.picks[0]["hit"] is False


def test_eligibility_filters():
    panel = make_panel([
        stat(1, "S1", mpg=10, value_pct=20, actual_pct=5, gap_pct=15),   # fails min_mpg
        stat(2, "S1", age=34, value_pct=20, actual_pct=5, gap_pct=15),   # fails max_age
        stat(3, "S1", value_pct=20, actual_pct=25, gap_pct=-5),          # fails require_undervalued
        stat(4, "S1", value_pct=20, actual_pct=5, gap_pct=15, ws=6),     # passes
        stat(4, "S2", ws=6, actual_pct=5),
    ])
    spec = StrategySpec(signal="gap", portfolio_size=5, horizon=1, min_mpg=20, min_gp=40,
                        max_age=30, require_undervalued=True, start_season="S1", end_season="S1")
    res = run_backtest(panel, spec)
    assert res.n_picks == 1 and res.picks[0]["player_id"] == 4


def test_ranking_is_deterministic_and_by_signal():
    panel = make_panel([
        stat(1, "S1", value_pct=20, actual_pct=5, gap_pct=15, ws=5),
        stat(2, "S1", value_pct=30, actual_pct=5, gap_pct=25, ws=5),   # highest gap
        stat(3, "S1", value_pct=25, actual_pct=5, gap_pct=20, ws=5),
        stat(1, "S2", ws=5, actual_pct=5), stat(2, "S2", ws=5, actual_pct=5), stat(3, "S2", ws=5, actual_pct=5),
    ])
    spec = StrategySpec(signal="gap", portfolio_size=2, horizon=1, start_season="S1", end_season="S1")
    order = [p["player_id"] for p in run_backtest(panel, spec).picks]
    assert order == [2, 3]                     # gap desc
    assert order == [p["player_id"] for p in run_backtest(panel, spec).picks]  # stable


def test_alpha_vs_random_is_positive_when_signal_works():
    # The high-gap player produces; the rest bust. Strategy should beat a random pick.
    panel = make_panel([
        stat(1, "S1", value_pct=20, actual_pct=5, gap_pct=15),
        stat(2, "S1", value_pct=12, actual_pct=12, gap_pct=0),
        stat(3, "S1", value_pct=8, actual_pct=13, gap_pct=-5),
        stat(1, "S2", ws=10, actual_pct=5),   # prod 25 − 5 = +20
        stat(2, "S2", ws=1, actual_pct=12),   # prod 2.5 − 12 = −9.5
        stat(3, "S2", ws=1, actual_pct=12),   # −9.5
    ])
    spec = StrategySpec(signal="gap", portfolio_size=1, horizon=1, start_season="S1", end_season="S1")
    res = run_backtest(panel, spec)
    assert res.surplus_per_slot_pct == 20.0
    assert res.benchmarks["random"]["surplus_per_slot_pct"] < 20.0
    assert res.alpha_per_slot_pct > 0
    assert set(res.benchmarks) == {"random", "chase_production", "chase_salary"}


def test_empty_universe_is_graceful():
    panel = make_panel([stat(1, "S1", mpg=5), stat(2, "S2", mpg=5)])
    res = run_backtest(panel, StrategySpec(portfolio_size=3, horizon=1))
    assert res.n_picks == 0
    assert res.total_surplus_pct == 0.0
    assert res.sharpe == 0.0


def test_current_targets_from_latest_season():
    # The rule's "would sign now" list comes from the latest panel season, ranked by signal.
    panel = make_panel([
        stat(1, "S1", value_pct=20, actual_pct=5, gap_pct=15),
        stat(2, "S2", value_pct=30, actual_pct=5, gap_pct=25),   # latest season, top gap
        stat(3, "S2", value_pct=25, actual_pct=5, gap_pct=20),
        stat(4, "S2", mpg=10, value_pct=40, actual_pct=1, gap_pct=39),  # fails floor
    ])
    res = run_backtest(panel, StrategySpec(signal="gap", portfolio_size=2, horizon=1))
    assert res.current_season == "S2"
    assert [t["player_id"] for t in res.current_targets] == [2, 3]   # eligible, gap desc


def test_edge_confidence_interval_present_and_ordered():
    panel = make_panel([
        stat(1, "S1", value_pct=20, actual_pct=5, gap_pct=15),
        stat(2, "S1", value_pct=12, actual_pct=12, gap_pct=0),
        stat(1, "S2", ws=10, actual_pct=5), stat(2, "S2", ws=1, actual_pct=12),
    ])
    res = run_backtest(panel, StrategySpec(signal="gap", portfolio_size=2, horizon=1))
    assert res.alpha_lo_pct <= res.alpha_hi_pct
    assert isinstance(res.edge_conclusive, bool)
