# ScoutIQ — Explainable NBA Contract Intelligence

A decision-support tool for NBA roster construction. ScoutIQ fuses structured stats, advanced metrics,
and salary-cap math into **explainable** valuations — not "what happened," but *what a player is worth,
what a proposed contract does to the cap, and why* — with confidence intervals rather than false precision.

> 🚧 **Work in progress.** Built in phases, data-first. See the roadmap below.

## Why it's different
Most sports tools predict stats. ScoutIQ's focus is the **synthesis**: combining production data + contract
math + (later) scouting text into a single recommendation, with a published backtest and calibrated
uncertainty as the credibility centerpiece.

## Architecture
| Layer | Stack |
|-------|-------|
| Data | Postgres (Neon) + pgvector, SQLAlchemy 2.0, Alembic |
| ETL | Python · `nba_api` (stats) · Basketball-Reference (advanced + salary, cached) |
| Model *(next)* | Gradient-boosted valuation + conformal prediction intervals |
| API *(later)* | FastAPI |
| UI *(later)* | Next.js + TypeScript + Tailwind |

## Repo structure
```
docs/      design + data-source spike (start here)
backend/   data layer: models, migrations, source adapters, ETL
spikes/    throwaway data-source probes
```

## Roadmap (build order: data-first)
- **Phase 1 — Data layer** ✅ players, per-season stats (box + advanced), realized salaries, cap constants
- **Phase 2 — Valuation model** salary-as-%-of-cap with confidence intervals + temporal backtest
- **Phase 3 — Cap simulator + API + dashboard** the signature what-if contract tool
- **Later** scouting-text LLM synthesis, similar-player search, forward contract structure

## Docs
- [Technical design](docs/02-technical-design.md) — schema, feature set, model plan
- [Data-source spike](docs/01-data-source-spike.md) — what data is actually available, and the gotchas
- [Project brief](ScoutIQ.md) — full vision

---
*Portfolio project. NBA data via public sources; scraped data is cached and rate-limited.*
