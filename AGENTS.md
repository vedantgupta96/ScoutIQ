# ScoutIQ Codex Adapter

This file is the Codex-facing adapter for ScoutIQ, a project originally built in Claude Code.
`CLAUDE.md` was expected as the source of Claude project knowledge, but it is not present in this
checkout. Until it exists, treat the following docs as the source of truth:

- `README.md` for the current project summary, architecture, roadmap, and results.
- `ScoutIQ.md` for the product vision, target user, long-term architecture, and feature posture.
- `backend/README.md` for backend setup, ETL run order, and data-source details.
- `docs/02-technical-design.md` and `docs/03-progress-log.md` for implementation decisions and status.

Keep this file as a thin adapter. Do not duplicate long project docs here; update the docs instead and
keep this page focused on how Codex should navigate the repo.

## Project Map

- `backend/`: Python backend package, database layer, ETL, model, and FastAPI API.
- `backend/scoutiq/api/`: FastAPI application and routers.
- `backend/scoutiq/etl/`: idempotent data loaders for cap constants, nba.com stats, BBRef enrichment,
  contracts, and coverage checks.
- `backend/scoutiq/model/`: production-implied valuation model, feature pipeline, prediction code, and
  committed backtest artifacts.
- `backend/scoutiq/sources/`: source adapters and crosswalk logic for nba.com and Basketball-Reference.
- `backend/scoutiq/models.py`: authoritative SQLAlchemy schema.
- `backend/alembic/`: migrations.
- `backend/scoutiq/data/`: small tracked seed data; raw scrape cache is intentionally ignored.
- `docs/`: technical design, data-source spike, and progress log.
- `spikes/`: throwaway probes used to validate data sources.
- `graphify-out/`: generated graph/report artifacts; cache and working files are ignored.

## Working Conventions

- Use Python 3.10+ and the backend package in `backend/`.
- Keep secrets out of git. `backend/.env.example` is tracked; real `.env` files are not.
- Numeric data, salary-cap math, and ETL should be deterministic and reproducible. Do not use LLMs for
  stats, salaries, or cap constants.
- Basketball-Reference scraping should remain polite: identified User-Agent, rate limit, disk cache,
  and resumable per-player failure handling.
- Cap constants are data, not code. Prefer table/seed updates over hard-coded season values.
- The valuation model predicts production-implied value as percent of cap and intentionally excludes
  current salary as a feature.
- Favor small, focused changes that preserve the data-first roadmap: data layer and valuation model are
  built; cap simulator, API, and dashboard are next.

## Validation Commands

From `backend/` after dependencies and env are configured:

```bash
alembic upgrade head
python -m scoutiq.etl.check_coverage
python -m scoutiq.model.train
```

Use targeted commands for narrower changes. Avoid running networked ETL unless the task requires it.

## Claude-to-Codex Adapter Notes

- Project-level Codex config lives in `.codex/config.toml`.
- Shared skills for agents belong in `.agents/skills/`, not `.codex/skills/`.
- No project Claude skills are present in `.claude/skills/` in this checkout. If they are restored later,
  copy each skill directory into `.agents/skills/` with its `SKILL.md` and supporting files together.
- No project Claude agents are present in `.claude/agents/` in this checkout. If they are restored later,
  convert each Claude agent `.md` file into a `.codex/agents/*.toml` file and place the original
  instructions under `developer_instructions`.
