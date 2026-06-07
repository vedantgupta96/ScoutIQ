# ScoutIQ — Backend

The ScoutIQ backend: ETL, Postgres schema, production-implied valuation model, and the Phase 3 FastAPI
surface for valuation lookup and the honest v0 What-If Contract Simulator. See
`../docs/02-technical-design.md` for the design and `../docs/03-progress-log.md` for current status.

## Stack
Python 3.10+ · FastAPI · SQLAlchemy 2.0 · Alembic · Postgres (Neon) + pgvector · pandas · nba_api ·
requests/lxml · scikit-learn

## Data sources
- **nba.com** (`nba_api` → `leaguedashplayerstats`): box + advanced (USG/TS/PIE/ratings). Numbers, deterministic.
- **Basketball-Reference** (scraped, cached): advanced (BPM/VORP/WS + position) and realized salary.
  Polite: identified User-Agent, ~3.5s rate-limit, disk cache so re-runs never re-hit the site.
- **Spotrac** (scraped, cached): forward contract structure and season cap hits. Used to bridge 2025-26
  salary comparisons because realized salary tables lag the current season.

## Setup
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env          # paste your Neon connection string (postgresql+psycopg://...sslmode=require)
```

For local tests:
```bash
pip install -e ".[dev]"
```

## Run order
```bash
alembic upgrade head                              # create extension + tables
python -m scoutiq.etl.load_cap_constants          # ~13 seasons of cap/tax/apron
python -m scoutiq.etl.load_stats --season 2023-24 # sanity-check one season first...
python -m scoutiq.etl.load_stats                  # ...then all configured seasons
python -m scoutiq.etl.load_bbref --limit 10       # validate scrape on 10 players first...
python -m scoutiq.etl.load_bbref                  # ...then full (slow first run; cached after)
python -m scoutiq.etl.repair_team_history         # cache-only: fix historical team_id from BBRef
python -m scoutiq.etl.load_current_rosters        # current roster team -> players.current_team_*
python -m scoutiq.etl.load_contracts              # Spotrac forward contract structure (networked)
python -m scoutiq.etl.bridge_contract_salaries    # bridge 2025-26 cap hits into player_salaries
python -m scoutiq.etl.check_coverage              # data-quality gate -> trainable row count
python -m scoutiq.model.train                     # regenerate model.joblib + backtest artifacts
uvicorn scoutiq.api.main:app --reload             # serve API at http://127.0.0.1:8000
```

Do not run networked ETL (`load_stats`, `load_bbref`, `load_contracts`, `load_current_rosters`) as part of ordinary API testing.
The tests below use fake sessions/dependency overrides and do not require a live database.

## API
```bash
curl 'http://127.0.0.1:8000/health'
curl 'http://127.0.0.1:8000/players?query=bane&limit=5'
curl 'http://127.0.0.1:8000/players/cards?query=bane&limit=5'
curl 'http://127.0.0.1:8000/players/watchlist?bucket=all&limit=24&offset=0'
curl 'http://127.0.0.1:8000/players/1630217'
curl 'http://127.0.0.1:8000/players/1630217/valuation?season=2024-25'
curl 'http://127.0.0.1:8000/players/1630217/headshot'
curl 'http://127.0.0.1:8000/players/1630217/scout-ratings'
curl 'http://127.0.0.1:8000/backtest'
curl 'http://127.0.0.1:8000/llm/scout-ratings/eval'
curl -X POST 'http://127.0.0.1:8000/simulate/contract' \
  -H 'content-type: application/json' \
  -d '{"player_id":1630217,"aav_pct":20,"years":4,"player_option_years":1,"start_season":"2025-26"}'
```

`POST /simulate/contract` is the canonical simulator endpoint. The older `POST /simulator/cap` path is
kept as a deprecated compatibility alias.

Player endpoints intentionally separate team concepts:
- `latest_stats_team`: the team represented by the latest loaded stat season.
- `current_team`: the current roster team loaded from `nba_api.commonallplayers`.

Run `repair_team_history` after `load_bbref` if nba.com historical stat rows have inherited current
roster team metadata. This command is cache-only and uses local BBRef pages, so it does not hit the
network. Run `load_current_rosters` separately when you want current roster/team state.

Player headshots are served through a backend proxy/cache at `GET /players/{player_id}/headshot`; missing
images are negative-cached and the frontend falls back to initials.

The v0 simulator is intentionally narrow: it models a standalone proposed contract against cap constants
and the valuation model, not full team payroll, luxury tax owed, Bird rights, MLE/BAE, repeater tax, or
trade exceptions. Future seasons beyond stored cap constants are projected at 4.5% annual growth and are
flagged in the response.

## Tests
```bash
pytest
python3 -m py_compile scoutiq/api/main.py scoutiq/api/cap_simulator.py scoutiq/api/routers/*.py
```

`backend/scoutiq/model/artifacts/model.joblib` is intentionally gitignored because it is regenerable.
The API returns `503` from valuation endpoints if the model binary is missing.

## LLM scout-rating eval
Phase 2 starts with an offline-first eval harness for scouting-text → structured ratings. The gold set
and deterministic fixture predictions are synthetic, project-authored JSONL files; tests never call the
network.

Offline fixture mode:
```bash
python -m scoutiq.llm.eval_scout_ratings \
  --gold scoutiq/llm/eval_data/scout_ratings_gold.jsonl \
  --predictions scoutiq/llm/eval_data/scout_ratings_predictions_fixture.jsonl
```

The CLI writes `scoutiq/llm/artifacts/scout_ratings_eval.json` with trait coverage, exact score
agreement, within-1 agreement, evidence hit rate, and invalid-output counts. Generated JSON reports are
gitignored.

The API exposes the same committed fixture as read-only metadata for the model page:
```bash
curl 'http://127.0.0.1:8000/llm/scout-ratings/eval'
```
That endpoint computes the offline fixture report on demand and does not write artifacts or call a live
LLM.

Optional live Claude mode is manual only:
```bash
ANTHROPIC_API_KEY=... SCOUTIQ_LLM_MODEL=... \
python -m scoutiq.llm.eval_scout_ratings \
  --gold scoutiq/llm/eval_data/scout_ratings_gold.jsonl \
  --live
```

If either environment variable is missing, live mode exits cleanly without writing a report. Do not
commit API keys, model names, or live LLM outputs.

Player scout ratings are exposed from a committed synthetic fixture:
```bash
curl 'http://127.0.0.1:8000/players/1630217/scout-ratings'
```
This is a player-profile UI/API contract preview. It does not read real scouting reports, Sonar results,
or live Claude outputs yet.

## Config
`scoutiq/config.py` (env-overridable): `SEASON_START_YEAR`/`SEASON_END_YEAR` (default 2012–2025),
`BBREF_DELAY_SECONDS`, `BBREF_USER_AGENT`.

## Layout
```
scoutiq/
  config.py  db.py  models.py
  sources/   nba.py  bbref.py  crosswalk.py
  etl/       load_cap_constants.py  load_stats.py  load_bbref.py  load_current_rosters.py
             repair_team_history.py  load_contracts.py  bridge_contract_salaries.py  check_coverage.py
  api/       main.py  routers/players.py  routers/simulator.py  routers/backtest.py  routers/headshots.py
  model/     train.py  predict.py  artifacts/
  llm/       schemas.py  scoring.py  eval_scout_ratings.py  eval_data/  artifacts/
  data/      cap_constants_seed.csv   raw/ (cached HTML, gitignored)
alembic/     versions/0001_initial.py  versions/0002_contracts.py
```
