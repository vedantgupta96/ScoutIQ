# ScoutIQ — Explainable NBA Contract Intelligence

A decision-support tool for NBA roster construction. ScoutIQ fuses structured stats, advanced metrics,
and salary-cap math into **explainable** valuations — not "what happened," but *what a player is worth,
what a proposed contract does to the cap, and why* — with confidence intervals rather than false precision.

> 🚧 **Work in progress.** The core cockpit is now live: data pipeline, 2025-26 valuation model,
> FastAPI, cap simulator, free-agency board, offseason planner, dashboard, watchlist filters, offline scout-rating eval,
> and player headshots.
> See the [progress log](docs/03-progress-log.md).

## Why it's different
Most sports tools predict stats. ScoutIQ's focus is the **synthesis**: combining production data + contract
math + (later) scouting text into a single recommendation, with a published backtest and calibrated
uncertainty as the credibility centerpiece.

## Results so far (valuation model, backtest on 2024–26)
A model that estimates a player's **production-implied market value** (salary as % of cap) — deliberately
*without* using their current salary, so the gap to actual pay is the signal.

| Metric | Value |
|---|---|
| R² | **0.767** |
| MAE | **3.128% of cap** (~$4.6M) vs 6.98% for a mean-predictor |
| 80% prediction-interval coverage | **0.797** (target 0.80 — well-calibrated) |

The largest gaps are basketball-credible and useful for front-office triage: rookie-scale breakouts,
buyout/value contracts, and expensive veteran risk all surface clearly. Full write-up, plots, and
per-player valuations: [`model/artifacts/report.md`](backend/scoutiq/model/artifacts/report.md).

## Architecture
| Layer | Stack | Status |
|-------|-------|--------|
| Data | Postgres (Neon) + pgvector, SQLAlchemy 2.0, Alembic | ✅ |
| ETL | Python · `nba_api` (stats) · Basketball-Reference (advanced + salary, cached) | ✅ |
| Model | HistGradientBoosting valuation + split-conformal intervals + temporal backtest | ✅ |
| API | FastAPI valuation, watchlist, free agency, offseason planning, simulator, backtest, scout-eval, headshots | ✅ |
| UI | Next.js dashboard: players/watchlist, profiles, teams, free agency, offseason plan, simulator, model/backtest | ✅ |

## Repo structure
```
docs/      design, data-source spike, progress log (start here)
backend/   data layer, ETL, model, FastAPI, simulator
frontend/  Next.js cockpit
```

## Roadmap (build order: data-first)
- **Phase 1 — Data layer** ✅ player seasons, advanced metrics, salaries, cap constants, contracts
- **Phase 2 — Valuation model** ✅ production-implied value, conformal intervals, calibrated backtest
- **Phase 3 — Cap simulator + API + dashboard** ✅ signature what-if contract tool and dashboard
- **Phase 3.5 — Free agency** ✅ derived FA board, option decisions, team targets
- **Phase 3.6 — Offseason planning** ✅ multi-move contracts/options with a four-season cap ledger
- **Next** official FA/rights data, cap holds, qualifying offers, and plan comparison
- **Later** backtested aging forecasts, injury indicators, and Monte Carlo cap scenarios

## Quickstart
See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md) for setup. In
short: point `backend/.env` at Postgres, run `alembic upgrade head`, run or reuse the ETL/model
artifacts, start FastAPI, then run the Next.js frontend.

## Docs
- [Progress log](docs/03-progress-log.md) — what's built, results, problems faced, decisions
- [Technical design](docs/02-technical-design.md) — schema, locked feature set, model plan
- [Data-source spike](docs/01-data-source-spike.md) — what data is actually available, and the gotchas
- [Deployment](docs/04-deployment.md) — hosting the cockpit (Vercel + Railway/Render + Neon)
- [Project brief](ScoutIQ.md) — full vision

---
*Portfolio project. NBA data via public sources; scraped data is cached and rate-limited.*
