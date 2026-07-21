"""Pure, deterministic strategy-backtest engine (docs/10).

Operates on an in-memory panel of player-seasons — no DB — so it is trivially testable.
The honesty contract (docs/10 §7):

- **Selection** ranks players by the valuation model's signal (value gap / value) as-of the
  decision season t — information available then.
- **Grading** scores realized outcomes from REAL production (Win Shares) via a documented,
  model-free `$/win` bridge minus the salary actually paid. The model never grades itself.

Everything is % of one season's cap (era-neutral), traceable, no hidden weights.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

# ---- Production → value bridge (model-free, documented, tunable; docs/10 §6) ----
# A win is worth a fixed share of the cap in any era. The anchor is the empirical
# MARKET-CLEARING rate: mean qualified salary (~11% of cap) ÷ mean qualified Win Shares
# (~4.4) ≈ 2.5% of cap per win, so the average rotation player nets ~0 surplus and any
# positive figure means the player genuinely beat the market. Win Shares is already in win
# units; VORP fills gaps at ~2.7 wins per VORP. Retune this one constant if the league
# economics drift.
PCT_OF_CAP_PER_WIN = 2.5
WINS_PER_VORP = 2.7

# Benchmark sampling (seeded → deterministic).
RANDOM_BENCHMARK_SAMPLES = 200
RANDOM_SEED = 20260721

SIGNALS = ("gap", "value", "bpm", "ws", "vorp")

CAVEAT = (
    "Selection uses the model's value signal as-of the decision season; outcomes are graded "
    "on real Win Shares (a model-free ~2% of cap per win) minus salary actually paid, so the "
    "model never grades itself. Players who leave the league contribute 0 for missing seasons "
    "(dead money is not tracked), which under-penalises busts. Few decision cohorts means wide "
    "error bars — read the benchmark gap, not the absolute number."
)


@dataclass(frozen=True)
class SeasonStat:
    """One player-season. `value_pct`/`gap_pct` are the model's as-of signal; `ws`/`vorp`/`bpm`
    and `actual_pct` (real salary as % of cap) are the model-free grading inputs."""
    player_id: int
    full_name: str
    season: str
    position: str | None
    age: int | None
    gp: int
    mpg: float
    ws: float | None
    vorp: float | None
    bpm: float | None
    value_pct: float | None
    actual_pct: float | None
    gap_pct: float | None


@dataclass
class Panel:
    rows: dict[tuple[int, str], SeasonStat]
    seasons: list[str]                       # ascending
    by_season: dict[str, list[SeasonStat]]
    _index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self._index = {s: i for i, s in enumerate(self.seasons)}

    def next_season(self, season: str) -> str | None:
        i = self._index.get(season)
        if i is None or i + 1 >= len(self.seasons):
            return None
        return self.seasons[i + 1]

    def has_future(self, season: str) -> bool:
        return self.next_season(season) is not None


def make_panel(stats: list[SeasonStat]) -> Panel:
    rows = {(s.player_id, s.season): s for s in stats}
    by_season: dict[str, list[SeasonStat]] = {}
    for s in stats:
        by_season.setdefault(s.season, []).append(s)
    seasons = sorted(by_season)
    return Panel(rows=rows, seasons=seasons, by_season=by_season)


@dataclass
class StrategySpec:
    # Eligibility (all as-of decision season t)
    min_mpg: float = 20.0
    min_gp: int = 40
    min_age: int | None = None
    max_age: int | None = None
    positions: tuple[str, ...] | None = None
    min_bpm: float | None = None
    require_undervalued: bool = False       # gap_pct > 0
    min_value_pct: float | None = None
    # Ranking signal + sizing
    signal: str = "gap"
    portfolio_size: int = 10
    horizon: int = 3                         # seasons held
    # Decision window (inclusive); None = full available range
    start_season: str | None = None
    end_season: str | None = None


def production_value_pct(row: SeasonStat) -> float | None:
    """Real production expressed as % of cap, model-free. Win Shares primary, VORP fallback."""
    wins = row.ws
    if wins is None and row.vorp is not None:
        wins = row.vorp * WINS_PER_VORP
    if wins is None:
        return None
    return wins * PCT_OF_CAP_PER_WIN


def _base_eligible(r: SeasonStat, spec: StrategySpec) -> bool:
    """Rotation-player floor shared by the strategy and the random benchmark universe."""
    return r.mpg >= spec.min_mpg and r.gp >= spec.min_gp


def _eligible(r: SeasonStat, spec: StrategySpec) -> bool:
    if not _base_eligible(r, spec):
        return False
    if spec.min_age is not None and (r.age is None or r.age < spec.min_age):
        return False
    if spec.max_age is not None and (r.age is None or r.age > spec.max_age):
        return False
    if spec.positions and (r.position not in spec.positions):
        return False
    if spec.min_bpm is not None and (r.bpm is None or r.bpm < spec.min_bpm):
        return False
    if spec.require_undervalued and (r.gap_pct is None or r.gap_pct <= 0):
        return False
    if spec.min_value_pct is not None and (r.value_pct is None or r.value_pct < spec.min_value_pct):
        return False
    return True


def _signal_value(r: SeasonStat, signal: str) -> float:
    v = {"gap": r.gap_pct, "value": r.value_pct, "bpm": r.bpm, "ws": r.ws, "vorp": r.vorp}.get(signal)
    return v if v is not None else float("-inf")


def _rank_top(rows: list[SeasonStat], signal: str, n: int) -> list[SeasonStat]:
    # Deterministic: signal desc, then player_id asc for stable tie-breaks.
    return sorted(rows, key=lambda r: (-_signal_value(r, signal), r.player_id))[:n]


def _realized_surplus(panel: Panel, player_id: int, t: str, horizon: int) -> tuple[float, int]:
    """Sum of (real production % − salary % of cap) over the held seasons after t."""
    total = 0.0
    used = 0
    s = t
    for _ in range(horizon):
        s = panel.next_season(s)
        if s is None:
            break
        fut = panel.rows.get((player_id, s))
        if fut is None:
            continue  # left league: 0 production, 0 tracked cost
        prod = production_value_pct(fut)
        cost = fut.actual_pct
        if prod is None or cost is None:
            continue
        total += prod - cost
        used += 1
    return round(total, 3), used


@dataclass
class PickResult:
    player_id: int
    full_name: str
    decision_season: str
    signal_value: float
    value_pct: float | None
    actual_pct: float | None
    realized_surplus_pct: float
    seasons_realized: int
    hit: bool


def _score_portfolio(panel: Panel, picks: list[SeasonStat], horizon: int) -> list[PickResult]:
    out = []
    for p in picks:
        surplus, used = _realized_surplus(panel, p.player_id, p.season, horizon)
        out.append(PickResult(
            player_id=p.player_id, full_name=p.full_name, decision_season=p.season,
            signal_value=round(_signal_value(p, "gap") if p.gap_pct is not None else 0.0, 2),
            value_pct=p.value_pct, actual_pct=p.actual_pct,
            realized_surplus_pct=surplus, seasons_realized=used, hit=surplus > 0,
        ))
    return out


def _aggregate(picks: list[PickResult]) -> dict:
    if not picks:
        return {"n_picks": 0, "total_surplus_pct": 0.0, "surplus_per_slot_pct": 0.0, "hit_rate": 0.0}
    totals = [p.realized_surplus_pct for p in picks]
    return {
        "n_picks": len(picks),
        "total_surplus_pct": round(sum(totals), 2),
        "surplus_per_slot_pct": round(sum(totals) / len(totals), 3),
        "hit_rate": round(sum(p.hit for p in picks) / len(picks), 3),
    }


def _decision_seasons(panel: Panel, spec: StrategySpec) -> list[str]:
    out = []
    for s in panel.seasons:
        if not panel.has_future(s):
            continue
        if spec.start_season and s < spec.start_season:
            continue
        if spec.end_season and s > spec.end_season:
            continue
        out.append(s)
    return out


def _max_drawdown(equity: list[float]) -> float:
    """Largest peak-to-trough drop on the cumulative equity curve (0 if it only rises)."""
    peak = float("-inf")
    dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = min(dd, v - peak)
    return round(dd, 2)


def _benchmark(panel: Panel, spec: StrategySpec, decision_seasons: list[str], kind: str) -> dict:
    rng = random.Random(RANDOM_SEED)
    all_picks: list[PickResult] = []
    for t in decision_seasons:
        universe = [r for r in panel.by_season.get(t, []) if _base_eligible(r, spec)]
        if not universe:
            continue
        if kind == "random":
            samples = []
            for _ in range(RANDOM_BENCHMARK_SAMPLES):
                k = min(spec.portfolio_size, len(universe))
                chosen = rng.sample(universe, k)
                samples.extend(_score_portfolio(panel, chosen, spec.horizon))
            all_picks.extend(samples)
        elif kind == "chase_production":
            all_picks.extend(_score_portfolio(panel, _rank_top(universe, "ws", spec.portfolio_size), spec.horizon))
        elif kind == "chase_salary":
            top = sorted(universe, key=lambda r: (-(r.actual_pct or float("-inf")), r.player_id))[:spec.portfolio_size]
            all_picks.extend(_score_portfolio(panel, top, spec.horizon))
    return _aggregate(all_picks)


@dataclass
class BacktestResult:
    spec: dict
    decision_seasons: list[str]
    equity_curve: list[dict]           # [{season, cohort_surplus_pct, cumulative_surplus_pct}]
    n_picks: int
    total_surplus_pct: float
    surplus_per_slot_pct: float
    hit_rate: float
    surplus_std_pct: float
    sharpe: float                      # mean / std of per-pick surplus
    max_drawdown_pct: float
    benchmarks: dict                   # kind -> aggregate; each has surplus_per_slot_pct
    alpha_per_slot_pct: float          # strategy per-slot − random per-slot
    picks: list[dict]
    caveat: str


def run_backtest(panel: Panel, spec: StrategySpec) -> BacktestResult:
    decision_seasons = _decision_seasons(panel, spec)
    all_picks: list[PickResult] = []
    equity: list[dict] = []
    cumulative = 0.0
    for t in decision_seasons:
        eligible = [r for r in panel.by_season.get(t, []) if _eligible(r, spec)]
        chosen = _rank_top(eligible, spec.signal, spec.portfolio_size)
        scored = _score_portfolio(panel, chosen, spec.horizon)
        all_picks.extend(scored)
        cohort = round(sum(p.realized_surplus_pct for p in scored), 2)
        cumulative = round(cumulative + cohort, 2)
        equity.append({"season": t, "cohort_surplus_pct": cohort, "cumulative_surplus_pct": cumulative})

    agg = _aggregate(all_picks)
    totals = [p.realized_surplus_pct for p in all_picks]
    std = round(statistics.pstdev(totals), 3) if len(totals) > 1 else 0.0
    mean = agg["surplus_per_slot_pct"]
    sharpe = round(mean / std, 3) if std > 0 else 0.0

    benchmarks = {
        kind: _benchmark(panel, spec, decision_seasons, kind)
        for kind in ("random", "chase_production", "chase_salary")
    }
    random_per_slot = benchmarks["random"]["surplus_per_slot_pct"]
    alpha = round(mean - random_per_slot, 3)

    return BacktestResult(
        spec=vars(spec).copy(),
        decision_seasons=decision_seasons,
        equity_curve=equity,
        n_picks=agg["n_picks"],
        total_surplus_pct=agg["total_surplus_pct"],
        surplus_per_slot_pct=mean,
        hit_rate=agg["hit_rate"],
        surplus_std_pct=std,
        sharpe=sharpe,
        max_drawdown_pct=_max_drawdown([e["cumulative_surplus_pct"] for e in equity]),
        benchmarks=benchmarks,
        alpha_per_slot_pct=alpha,
        picks=[vars(p) for p in all_picks],
        caveat=CAVEAT,
    )
