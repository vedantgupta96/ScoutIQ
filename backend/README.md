# ScoutIQ — Backend (Data Layer)

The v0 data layer for ScoutIQ: ETL that lands a clean, queryable NBA dataset (players, per-season stats,
realized salaries, cap constants) in Postgres. See `../docs/02-technical-design.md` for the design and
`../docs/01-data-source-spike.md` for data-source findings.

> Scope: **data only**. Valuation model, FastAPI, and UI are later phases.

## Stack
Python 3.10+ · SQLAlchemy 2.0 · Alembic · Postgres (Neon) + pgvector · pandas · nba_api · requests/lxml

## Data sources
- **nba.com** (`nba_api` → `leaguedashplayerstats`): box + advanced (USG/TS/PIE/ratings). Numbers, deterministic.
- **Basketball-Reference** (scraped, cached): advanced (BPM/VORP/WS + position) and realized salary.
  Polite: identified User-Agent, ~3.5s rate-limit, disk cache so re-runs never re-hit the site.

## Setup
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env          # paste your Neon connection string (postgresql+psycopg://...sslmode=require)
```

## Run order
```bash
alembic upgrade head                              # create extension + tables
python -m scoutiq.etl.load_cap_constants          # ~13 seasons of cap/tax/apron
python -m scoutiq.etl.load_stats --season 2023-24 # sanity-check one season first...
python -m scoutiq.etl.load_stats                  # ...then all configured seasons
python -m scoutiq.etl.load_bbref --limit 10       # validate scrape on 10 players first...
python -m scoutiq.etl.load_bbref                  # ...then full (slow first run; cached after)
python -m scoutiq.etl.check_coverage              # data-quality gate -> trainable row count
```

## Config
`scoutiq/config.py` (env-overridable): `SEASON_START_YEAR`/`SEASON_END_YEAR` (default 2012–2024),
`BBREF_DELAY_SECONDS`, `BBREF_USER_AGENT`.

## Layout
```
scoutiq/
  config.py  db.py  models.py
  sources/   nba.py  bbref.py  crosswalk.py
  etl/       load_cap_constants.py  load_stats.py  load_bbref.py  check_coverage.py
  data/      cap_constants_seed.csv   raw/ (cached HTML, gitignored)
alembic/     versions/0001_initial.py
```
