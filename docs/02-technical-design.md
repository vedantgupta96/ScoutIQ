# ScoutIQ — Technical Design

> The doc you code against. Vision lives in `ScoutIQ.md`; feasibility in `docs/01-data-source-spike.md`.
> **Do not finalize the schema until the contract-data row of the spike is green.**

---

## 0. Scope & non-goals (the useful 10% of a PRD)

**In scope (Phase 1):** NBA player + contract DB, stats/contracts ETL, contract valuation model with
confidence intervals + backtest, What-If cap simulator, front-office dashboard.

**Non-goals:** real-time/in-game data, multiple sports, full CBA fidelity, mobile app, auth/multi-tenant,
trade-machine matching rules. (These are explicit *non-goals*, not "later" — keep the surface small.)

---

## 1. System shape

```
Next.js (TS, App Router)  ──HTTP──>  FastAPI
   shadcn/ui, Recharts,                  ├── valuation service (ML)
   D3 (cap timeline only)                ├── cap/contract engine (pure Python, deterministic)
                                         ├── LLM service (Claude: extract / consensus / rationale)
                                         └── ingestion (Sonar, cached)
                                              │
        Postgres + pgvector  <───────────────┤   system of record + embeddings
        Redis  <──────────────────────────────┘   cache LLM/Sonar/model calls, sessions
```

Principles:
- **Numbers are deterministic.** Cap math lives in plain Python, fully unit-tested, no LLM, no cache needed.
- **LLM/Sonar calls are cached** in Redis by a content key; never in the hot path.
- **Cap constants are data, not code** (`cap_constants` table) — they change every season.

---

## 2. Postgres schema (Phase 1)

> **v0 build update (2026-06-06):** the authoritative schema now lives in `backend/scoutiq/models.py`.
> Changes vs. the SQL below: added **`player_salaries`** (historical realized salary from BBRef — what v0
> trains on) and **`player_xref`** (nba_id ↔ verified BBRef slug). `contracts`/`contract_years` are
> **defined-later** (forward structure from Spotrac), not populated in this phase.

```sql
-- ── Reference ────────────────────────────────────────────────
CREATE TABLE teams (
  id            SERIAL PRIMARY KEY,
  abbreviation  TEXT UNIQUE NOT NULL,      -- 'BOS'
  name          TEXT NOT NULL,
  conference    TEXT,
  division      TEXT
);

CREATE TABLE players (
  id            SERIAL PRIMARY KEY,
  nba_api_id    INTEGER UNIQUE,            -- crosswalk to stats source
  full_name     TEXT NOT NULL,
  birth_date    DATE,
  position      TEXT,                      -- 'PG','SF', etc.
  height_in     INTEGER,
  weight_lb     INTEGER,
  draft_year    INTEGER,
  nba_debut     DATE
);
CREATE INDEX ON players (full_name);

-- ── Performance (numbers backbone) ───────────────────────────
CREATE TABLE player_seasons (
  id            SERIAL PRIMARY KEY,
  player_id     INTEGER REFERENCES players(id),
  season        TEXT NOT NULL,             -- '2023-24'
  team_id       INTEGER REFERENCES teams(id),
  age           INTEGER,
  games_played  INTEGER,
  minutes       NUMERIC,
  -- keep volatile/advanced metrics flexible:
  basic_stats   JSONB,                     -- pts, reb, ast, ...
  advanced      JSONB,                     -- per, bpm, vorp, ws, usg, ts%
  UNIQUE (player_id, season, team_id)
);

-- ── Contracts (the make-or-break data) ───────────────────────
CREATE TABLE contracts (
  id              SERIAL PRIMARY KEY,
  player_id       INTEGER REFERENCES players(id),
  team_id         INTEGER REFERENCES teams(id),
  signed_date     DATE,                    -- CRITICAL for backtest leakage control
  start_season    TEXT,
  end_season      TEXT,
  total_value     BIGINT,                  -- dollars
  guaranteed_value BIGINT,
  contract_type   TEXT,                    -- 'rookie','veteran','extension','max','min'
  source          TEXT,                    -- provenance: 'spotrac', etc.
  retrieved_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE contract_years (
  id            SERIAL PRIMARY KEY,
  contract_id   INTEGER REFERENCES contracts(id) ON DELETE CASCADE,
  season        TEXT NOT NULL,
  cap_hit       BIGINT,
  guaranteed    BIGINT,
  option_type   TEXT,                      -- 'player','team','none','non_guaranteed'
  incentives    BIGINT DEFAULT 0,
  UNIQUE (contract_id, season)
);

-- ── League cap parameters (data, not code) ───────────────────
CREATE TABLE cap_constants (
  season         TEXT PRIMARY KEY,         -- '2024-25'
  salary_cap     BIGINT,
  tax_line       BIGINT,
  first_apron    BIGINT,
  second_apron   BIGINT,
  max_25         BIGINT,                   -- 0–6 yrs experience
  max_30         BIGINT,                   -- 7–9 yrs
  max_35         BIGINT                    -- 10+ yrs
);

-- ── ML outputs ───────────────────────────────────────────────
CREATE TABLE valuations (
  id              SERIAL PRIMARY KEY,
  player_id       INTEGER REFERENCES players(id),
  as_of_date      DATE NOT NULL,
  model_version   TEXT NOT NULL,
  pred_pct_cap    NUMERIC,                 -- target = first-yr salary as % of cap
  pred_value      BIGINT,                  -- pct_cap * season cap, for display
  ci_low          BIGINT,
  ci_high         BIGINT,
  features        JSONB,                   -- snapshot for explainability
  UNIQUE (player_id, as_of_date, model_version)
);

-- ── Phase 2: scouting text + embeddings ──────────────────────
CREATE TABLE scout_reports (
  id            SERIAL PRIMARY KEY,
  player_id     INTEGER REFERENCES players(id),
  author        TEXT,
  source        TEXT,
  report_date   DATE,
  raw_text      TEXT,
  embedding     VECTOR(1536)               -- pgvector
);
CREATE TABLE scout_ratings (              -- LLM-extracted, validated vs gold set
  id              SERIAL PRIMARY KEY,
  scout_report_id INTEGER REFERENCES scout_reports(id) ON DELETE CASCADE,
  trait           TEXT,                    -- 'leadership','coachability',...
  score           NUMERIC,
  evidence_span   TEXT
);
CREATE TABLE player_news (                -- Perplexity Sonar cache (text only!)
  id            SERIAL PRIMARY KEY,
  player_id     INTEGER REFERENCES players(id),
  query_key     TEXT,                      -- 'player:{id}|2024-25' → cache key
  summary       TEXT,
  citations     JSONB,                     -- [{title,url}]
  retrieved_at  TIMESTAMPTZ DEFAULT now()
);
```

**Why target = salary as % of cap (not raw dollars):** the cap inflates ~10%/yr, so raw dollars leak the
era. Predicting **% of cap** normalizes across seasons; multiply by the season's cap for display. This
single choice makes the backtest honest.

---

## 3. Valuation model (the flagship)

> **v0 BUILT (2026-06-06).** Implemented in `backend/scoutiq/model/` (results in `model/artifacts/`).
> Key change from the original plan: the model predicts **production-implied value** and **excludes the
> player's current salary** as a feature — testing showed a paid-salary target is dominated by contract
> mechanics (persistence beats any model on mid-contract players). See
> [progress log](03-progress-log.md) for the pivot rationale and backtest results (R² 0.77, 80%
> coverage 0.85).

### LOCKED feature set (confirmed available 2026-06-06)
- **nba.com** (`leaguedashplayerstats` Advanced + Base): `MIN, GP, USG_PCT, TS_PCT, PIE, NET_RATING,
  OFF_RATING, DEF_RATING, AST_PCT, REB_PCT` + key box rates. (572 players/season, ~0.2s.)
- **BBRef** (per-player Advanced table): `BPM, OBPM, DBPM, VORP, WS, WS/48, PER`. Same table also yields
  **`Pos`** (position) — so position is free, no extra calls.
- **Context:** `AGE` (from nba.com), position (BBRef), season salary cap (from `cap_constants`).

### Target
- **v0 (build now):** a player's **season salary as % of that season's cap**, predicted from
  **prior-season** production (clean temporal split; fully supported by `player_salaries` + `player_seasons`).
- **v1 (after Spotrac):** first-year salary of a *new contract* as % of cap — upgrade once forward
  contract structure exists.

- **Legacy note — features (strict leakage control, only data before the predicted season):**
  prior 1–3 seasons production (BPM, VORP, WS, usage, TS%, minutes), **age**, position,
  **availability** (games played), prior-season salary tier, and market context (cap inflation).
- **Model:** start with gradient-boosted trees (XGBoost/LightGBM). You have ML experience, so:
  - **Confidence intervals** via **quantile regression** (predict P10/P50/P90) or **conformal
    prediction** (cleaner coverage guarantees — recommended).
- **Backtest protocol (temporal, no leakage):**
  - Train on contracts signed **2015–2022**, test on **2023–2025**.
  - Report MAE in **$** *and* in **% of cap**; report **interval coverage** (does the 80% CI contain
    truth ~80% of the time?) with a reliability plot.
  - Ship these numbers in the UI — calibration is the credibility centerpiece.

---

## 4. Cap / contract engine (deterministic Python)

Pure functions, fully unit-tested, no ML:
- `cap_hits(contract) -> {season: amount}`
- `team_total(team, season) -> amount`
- `tax_owed(team_total, season)` — progressive brackets from `cap_constants` (repeater = Phase 3)
- `apron_flags(team_total, season) -> {over_tax, over_first_apron, over_second_apron}`
- `max_salary(experience_years, season) -> amount` (25/30/35% tiers; 8% Bird / 5% non-Bird raises)
- `simulate(team, proposed_terms) -> {year_by_year cap, tax delta, apron flags, flexibility}`

Every output that relies on a non-modeled rule carries an **assumption flag** the UI surfaces.

---

## 5. API surface (FastAPI)

```
GET  /players?query=                     # search
GET  /players/{id}                       # profile + latest valuation
GET  /players/{id}/seasons               # stat history
GET  /players/{id}/valuation             # value + CI + feature snapshot
GET  /players/{id}/comparables           # pgvector similar players          (P2)
GET  /players/{id}/news                  # Sonar-cached narrative + citations (P2)

GET  /teams/{id}/cap?season=             # current cap/tax/apron state
POST /simulate/contract                  # body: terms → cap impact + value delta + rationale
                                         #   (rationale via LLM service, grounded in returned numbers)

POST /scout-reports                      # ingest text → embed → LLM extract ratings (P2)
GET  /backtest                           # serve published calibration metrics
```

---

## 6. Build order (matches roadmap)

1. **Migrations + `cap_constants` seed** → 2. **stats ETL** → 3. **contracts ETL** (riskiest; spike first)
→ 4. **valuation v0 + backtest** → 5. **cap engine + `/simulate`** → 6. **dashboard + signature viz**.
Phase 2 (LLM/Sonar/pgvector) and Phase 3 (forecast/injury/graph/Monte Carlo) layer on after Phase 1 ships.

---

## 7. Testing & rigor checklist
- [ ] Cap engine: unit tests against 3–4 real known team cap sheets.
- [ ] Valuation: temporal backtest with leakage check (assert no feature post-dates `signed_date`).
- [ ] CI coverage validated (P2: LLM eval harness vs gold set).
- [ ] Every UI claim that depends on a non-modeled CBA rule shows its assumption flag.
