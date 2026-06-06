# ScoutIQ — Explainable NBA Contract Intelligence

A decision-support tool for NBA roster construction. ScoutIQ fuses structured stats, advanced metrics,
and salary-cap math into **explainable** valuations — not "what happened," but *what a player is worth,
what a proposed contract does to the cap, and why* — with confidence intervals rather than false precision.

> 🚧 **Work in progress.** Built in phases, data-first. Phases 1–2 complete; see the roadmap and the
> [progress log](docs/03-progress-log.md).

## Why it's different
Most sports tools predict stats. ScoutIQ's focus is the **synthesis**: combining production data + contract
math + (later) scouting text into a single recommendation, with a published backtest and calibrated
uncertainty as the credibility centerpiece.

## Results so far (valuation model, backtest on 2023–25)
A model that estimates a player's **production-implied market value** (salary as % of cap) — deliberately
*without* using their current salary, so the gap to actual pay is the signal.

| Metric | Value |
|---|---|
| R² | **0.77** |
| MAE | **2.9% of cap** (~$4.0M) vs 6.9% for a mean-predictor |
| 80% prediction-interval coverage | **0.85** (target 0.80 — well-calibrated) |

The largest gaps are basketball-credible — flags Bane / Haliburton / J. Williams as underpaid (all later
got max extensions) and Simmons / LaVine / Beal / Gobert as overpaid. Full write-up, plots, and per-player
valuations: [`model/artifacts/report.md`](backend/scoutiq/model/artifacts/report.md).

## Architecture
| Layer | Stack | Status |
|-------|-------|--------|
| Data | Postgres (Neon) + pgvector, SQLAlchemy 2.0, Alembic | ✅ |
| ETL | Python · `nba_api` (stats) · Basketball-Reference (advanced + salary, cached) | ✅ |
| Model | HistGradientBoosting valuation + split-conformal intervals + temporal backtest | ✅ |
| API | FastAPI | ⏳ next |
| UI | Next.js + TypeScript + Tailwind (Recharts/visx) | ⏳ later |

## Repo structure
```
docs/      design, data-source spike, progress log (start here)
backend/   data layer (models, migrations, ETL) + model/ (valuation + backtest)
spikes/    throwaway data-source probes
```

## Roadmap (build order: data-first)
- **Phase 1 — Data layer** ✅ 6,829 player-seasons, advanced metrics, salaries, cap constants (2012–25)
- **Phase 2 — Valuation model** ✅ production-implied value, conformal intervals, calibrated backtest
- **Phase 3 — Cap simulator + API + dashboard** ⏳ the signature what-if contract tool
- **Later** scouting-text LLM synthesis, similar-player search, forward contract structure (Spotrac)

## Quickstart (data + model)
See [backend/README.md](backend/README.md) for full setup. In short: point `backend/.env` at a Postgres
(Neon), `alembic upgrade head`, run the ETL, then `python -m scoutiq.model.train`.

## Docs
- [Progress log](docs/03-progress-log.md) — what's built, results, problems faced, decisions
- [Technical design](docs/02-technical-design.md) — schema, locked feature set, model plan
- [Data-source spike](docs/01-data-source-spike.md) — what data is actually available, and the gotchas
- [Project brief](ScoutIQ.md) — full vision

---
*Portfolio project. NBA data via public sources; scraped data is cached and rate-limited.*
