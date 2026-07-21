# 10 — Strategy Backtesting (and renaming today's "Model & Backtest")

_Research + integration design from the 2026-07-21 discussion. Two things:_
1. _Today's **Model & Backtest** tab is misnamed — it verifies **model accuracy**, not a
   strategy. Rename it and free the word "backtest."_
2. _Design a **real backtesting feature** in the financial sense: apply a roster-building
   **strategy** to historical NBA data and measure how it would have performed._

---

## 1. What today's tab actually is (and why to rename it)

`/model` ("Model & Backtest") is the valuation model's **report card**. It shows
prediction error (MAE, R²), interval calibration, a predicted-vs-actual scatter, the
scout-extraction eval, caution cases, and bargain/overpay leaderboards — all drawn from
one held-out artifact. It answers **"how accurate is the AI at valuing NBA players?"**

That is *model validation*, not *strategy backtesting*. Using "backtest" for it collides
with the financial meaning the new feature needs. **Rename it** — candidates:
**"Model Trust"** (recommended), "Model Diagnostics", or "Model Report Card". This is a
label/route change only; no logic moves.

## 2. What "strategy backtesting" means for ScoutIQ

**Finance:** apply an investment strategy to historical data and measure how it would have
performed (return, risk, vs a benchmark).

**ScoutIQ analog:** at a past decision point, select a **portfolio of players** using a
repeatable **rule**, "hold" them for a few seasons, and measure the **realized surplus**
(on-court value produced minus salary paid) versus a benchmark. Players are the assets;
salary is the price; production is the dividend; the strategy is the roster-building
philosophy.

Concrete question it answers: _"If I had always signed the most **undervalued** rotation
players under 25 since 2016, would that roster philosophy actually have produced more
value-per-dollar than chasing big names?"_

## 3. Is this already covered elsewhere? (Audit — No.)

| Feature | What it does | Time frame | Overlap with strategy backtest |
|---|---|---|---|
| **Model & Backtest** (`/model`) | Model accuracy vs held-out truth | Historical, but measures the *model* | None — different question |
| **Offseason Plan** (`/offseason`) | One team's signings/option calls → multi-season payroll ledger | Forward, single offseason | None — prescriptive, present-state |
| **Cap Simulator** (`/simulator`) | One player's proposed contract → cap/apron impact | Forward, single player | None |
| **Trade Lab** (`/trade-lab`) | Evaluate one specific trade now | Present | None |
| **Free Agency** (`/free-agency`) | This summer's FA board / options / team targets | Present market | None — no historical replay |

Every existing surface is **forward-looking, present-state, single-scenario**. None replay
a *repeatable rule across history to measure realized performance*. A code scan found no
existing `strategy`/`portfolio` concept. **Conclusion: this is a genuinely new capability.**

### Integrate or standalone? → **Standalone, with two bridges**
The mental model (define rule → simulate over history → returns vs benchmark) is distinct
from every forward feature; folding it into Offseason Plan would muddy that tool's purpose.
So build a **new feature** ("Strategy Lab" / nav label "Backtesting"), with two bridges:
- **Bridge A (naming):** rename `/model` → "Model Trust" to free "Backtesting."
- **Bridge B (forward payoff):** a strategy that backtests well can be **applied to the
  current offseason** — rank *this* summer's free agents (Free Agency) or seed Offseason
  Plan targets with the validated rule. Backtesting → validated conviction → action.

## 4. The data is already here (key finding — no new sources)

Every ingredient exists in Postgres, 14 seasons deep:

| Table | Coverage | Role in backtest |
|---|---|---|
| `player_seasons` (box + advanced: **WS, BPM, VORP, PER…**) | **2012-13 → 2025-26** | Features **and** independent realized-production outcome |
| `player_salaries` (realized $) | 2012-13 → 2025-26 | Price paid / cost |
| `player_valuations` (model value % of cap, per season) | 2012-13 → 2025-26 | Selection **signal** (value gap) |
| `cap_constants` | full | Convert %-of-cap ↔ dollars per era |
| `contract_years`, `free_agent_rights` | 2020-21 → (recent) | Optional: restrict universe to the FA market |

The model's training framing is **leakage-safe by construction** (`model/dataset.py`:
features are season ≤ t, target is t+1), so the per-season value signal is genuinely
forward-looking. One honesty caveat in §7.

## 5. The core model (how a backtest runs)

### 5a. Universe (the "investable" set at decision season _t_)
- **v1 (recommended):** all **qualified rostered players** in season _t_ (≥ min MPG/GP),
  treated as a selectable pool. Simple, complete, no FA-history gaps.
- **v2:** restrict to the **free-agent market** each summer (more realistic "buying"),
  using `free_agent_rights` + contract-end inference. Requires deeper FA history.

### 5b. Strategy = filters + signal + sizing
A `StrategySpec`:
- **Filters (eligibility):** age band, position, minutes/GP floor, contract status, value-gap
  sign, stat thresholds (e.g. BPM ≥ x, trailing BPM trend > 0).
- **Signal (ranking):** the ordering used to pick — e.g. value **gap** (undervaluation),
  projected surplus, BPM, or a blend.
- **Sizing (budget):** top-N players, or fill a cap budget (e.g. $X of room), or one per
  position. Bounds portfolio size so returns are comparable.

Preset strategies to ship: **"Value"** (most undervalued qualified), **"Youth upside"**
(≤ 23, rising BPM), **"Avoid aging max"** (exclude ≥ 31 on > 15% cap), **"Chase
production"** (highest BPM regardless of cost — a naive benchmark).

### 5c. Execution loop (no look-ahead)
For each decision season _t_ in a window (e.g. 2015-16 … 2023-24):
1. Build the universe with features known **as-of _t_** (season ≤ t only).
2. Apply the strategy → a **selected portfolio** for _t_.
3. "Hold" **K seasons** (t+1 … t+K, K≈2–3).
4. Per pick, compute **realized outcome** from what actually happened (§6).
5. Aggregate across picks and seasons → the portfolio's return for cohort _t_.
Roll cohorts up into an **equity-curve-like** cumulative series + summary metrics.

## 6. Defining "return" (the crux)

Return per held season _s_ for a picked player = **realized surplus**:
```
surplus_s = production_value(s)  −  salary_paid(s)      (in % of cap, then × cap$)
```
- **`salary_paid(s)`** = `player_salaries` (real, unambiguous).
- **`production_value(s)` — LOCKED to independent real production** (decision 2). We map a
  player's actual advanced stats at _s_ to dollars **without the valuation model**, so
  selection and grading never share a model (§7 circularity).

### Production → dollars: the "$ / win" bridge (independent of the valuation model)
A transparent, documented, tunable mapping — same spirit as the pick-value curve:
```
wins(s)              = Win Shares at s          (WS is already in win units; primary)
                       fallback/ blend: VORP × WINS_PER_VORP  when WS missing
production_value$(s) = wins(s) × DOLLARS_PER_WIN(s)
production_value%(s) = production_value$(s) / salary_cap(s)
```
- **`WS`** (Win Shares) is the primary signal — it's literally "wins contributed."
- **`DOLLARS_PER_WIN(s)`** is a documented per-season anchor (≈ league total salary ÷ league
  total wins produced, or a fixed research value ~$2.5–3.5M/win, era-scaled by the cap). One
  constant, stated in the caveat, tunable — no hidden weights.
- **`BPM`** is used as an eligibility/quality **filter signal**, not the value scale (BPM is
  a rate, not a win total). **`WINS_PER_VORP`** (~2.7) only fills WS gaps.
This keeps the whole outcome side traceable and model-free.

Portfolio metrics (financial analogs):
- **Total realized surplus** ($ and % of cap) — the headline **return**.
- **Surplus per roster slot** and **per dollar spent** — ROI.
- **Hit rate** — % of picks with positive cumulative surplus (win rate).
- **Risk** — std-dev of per-pick surplus; **bust rate** (picks below a loss threshold);
  **max drawdown** (worst pick/cohort).
- **Risk-adjusted** — Sharpe-like = mean surplus / std surplus.
- **Alpha** — strategy return **minus a benchmark** (§ below).

### Benchmarks (what "good" is measured against)
- **Random qualified portfolio** (Monte-Carlo average of same-size random picks).
- **"Chase name/salary"** — pick the highest-paid (the market's implicit bet).
- **"Chase production"** — highest current BPM ignoring cost.
- **League-average slot.**

## 7. Honesty & pitfalls (must be designed in, per PRODUCT.md "uncertainty as a feature")

1. **Circularity (biggest risk).** If the same valuation model both **selects** and
   **scores**, the backtest grades the model against itself. **Mitigation:** select on the
   model signal at _t_, but **score on independent realized production** (WS/VORP/BPM) +
   real salary (§6 option A). Separates signal from ground truth.
2. **Look-ahead in model parameters.** Per-season stored valuations use as-of *features*
   but a model trained on *all* seasons (`publish_valuations.py`). Fine for relative
   strategy comparison; flag it. A rigorous v-next uses **walk-forward retraining** (train
   only on ≤ t) for the signal.
3. **Survivorship bias.** Busts who leave the league must **stay in the portfolio as a
   loss** (missing future season ⇒ near-zero production but salary/dead-money still paid),
   not silently drop out.
4. **Small samples.** ~8 decision cohorts × modest picks ⇒ wide error bars. Show
   confidence bands / n, never a single hero number.
5. **Salary stickiness** (same caveat the current tab already states). Mid-contract pay is
   locked, so "buying" bite is real mainly for players who actually re-sign/switch — the
   v2 FA-market universe sharpens this.
6. **Determinism & ties.** Fixed tie-breaks and seed so a backtest is reproducible.

## 8. Architecture

**Backend** — a pure, deterministic `scoutiq/backtest/engine.py`:
- Input: `StrategySpec`, window, horizon K, universe mode, benchmark set.
- Reads only existing tables; optionally precompute an **as-of player-season panel**
  (features + realized production + salary + cap) once, cached, for speed.
- Output: `BacktestResult` — per-cohort picks, per-pick realized surplus path, aggregate
  metrics, benchmark comparisons, confidence. No hidden weights; every number traceable.
- **Tests:** synthetic panels with hand-computable surplus; survivorship handling;
  benchmark sanity; determinism.

**API** — `POST /strategy/backtest` (spec → result), `GET /strategy/presets`. (Later:
`saved_strategies` table + `GET/POST /strategy/saved` to persist named strategies.)

**Frontend** — new `/strategy` page ("Strategy Lab", nav "Backtesting"):
- **Strategy builder** — filters + signal + sizing controls (reuse sliders/selects; presets
  as one-click starting points).
- **Results** — an **equity-curve** style chart (cumulative realized surplus by season, with
  benchmark overlay + confidence band), a **scorecard** (return, hit rate, Sharpe-like,
  alpha), and a **per-pick ledger** (who was bought, cost, realized surplus, hit/miss),
  click-through to player profiles. Honest caveat block, like the current tab.

**No new data sources.** v1 needs **no new tables** (derive from existing); a
`saved_strategies` table is the only optional addition (Phase 4+).

## 9. Phased plan

- **Phase 1 ✅ (2026-07-21)** Renamed `/model` → **"Model trust"** (nav, topbar, `<h1>`,
  player-page cross-ref). Route kept as `/model`.
- **Phase 2 ✅ (2026-07-21)** `scoutiq/backtest/engine.py` (pure) + `panel.py` (DB). As-of
  panel, `StrategySpec`, execution loop, model-free WS→value bridge (market-clearing
  **2.5% cap/win**, so avg player ≈ 0 surplus), realized surplus, hit rate, Sharpe-like, max
  drawdown, and 3 benchmarks (random / chase-production / chase-salary). 7 engine tests.
- **Phase 3 ✅ (2026-07-21)** API `POST /strategy/backtest`, `GET /strategy/presets|meta`
  (cached 14-season panel). Strategy Lab page `/strategy` (nav "Backtesting"): preset chips
  + full custom builder, verdict scorecard (alpha vs random), cumulative-surplus equity
  curve, benchmark bars, best-to-worst pick ledger with profile click-through, caveat.
  Live-verified: the naive "Value" preset returns **−9.2% alpha vs random** — a real,
  honest finding (extreme value signals mean-revert; cheap players get expensive).
- **Phase 4 ✅ light (2026-07-21)** 80% bootstrap interval on the edge-vs-random
  (`alpha_lo/hi_pct`, `edge_conclusive`); surfaced in the verdict ("holds up
  statistically" / "not conclusive") and the scorecard range. Saved strategies deferred.
- **Phase 5 ✅ (2026-07-21)** Forward bridge: `current_targets(panel, spec)` applies the
  same filters + ranking to the latest season → the players the rule would sign now, shown
  in a "What this rule would sign now" panel with a Free-agency cross-link. Live: the
  Win-Shares/age-≤28 bargain rule points to SGA, Amen Thompson, Wembanyama, Chet Holmgren.
- **Phase 6 (stretch) — Fidelity.** Walk-forward retrained signal; FA-market universe.

## 10. Decisions — LOCKED 2026-07-21

1. **Universe:** ✅ **all qualified rostered players** in season _t_ (≥ min MPG/GP).
2. **Outcome measure:** ✅ **real production (WS/VORP/BPM)** via the model-free $/win bridge
   in §6 — selection uses the model signal, grading uses real production.
3. **Names:** ✅ rename `/model` → **"Model Trust"**; new feature → **"Strategy Lab"** (page),
   nav label **"Backtesting"**.
4. **v1 scope:** ✅ **full custom builder** (filters + signal + sizing), with presets as
   one-click starting points on top of it.

## Sequencing note
Independent of the open Trade Lab PR (#82); touches new files plus a small rename on
`/model`. Phase 1 (rename) can land on its own.
