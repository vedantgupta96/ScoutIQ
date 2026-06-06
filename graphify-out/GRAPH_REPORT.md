# Graph Report - .  (2026-06-06)

## Corpus Check
- Corpus is ~15,715 words - fits in a single context window. You may not need a graph.

## Summary
- 167 nodes · 239 edges · 19 communities
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 22 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_BBRef Scraper & Parser|BBRef Scraper & Parser]]
- [[_COMMUNITY_Database Schema & ORM|Database Schema & ORM]]
- [[_COMMUNITY_Valuation Model Training|Valuation Model Training]]
- [[_COMMUNITY_ETL Data Pipeline|ETL Data Pipeline]]
- [[_COMMUNITY_Player Identity Resolution|Player Identity Resolution]]
- [[_COMMUNITY_Model Performance Metrics|Model Performance Metrics]]
- [[_COMMUNITY_Data Source Spikes|Data Source Spikes]]
- [[_COMMUNITY_NBA API Data Ingestion|NBA API Data Ingestion]]
- [[_COMMUNITY_Model Visualization Artifacts|Model Visualization Artifacts]]
- [[_COMMUNITY_Configuration & Settings|Configuration & Settings]]
- [[_COMMUNITY_Advanced Stats Exploration|Advanced Stats Exploration]]
- [[_COMMUNITY_Valuation Engine Design|Valuation Engine Design]]
- [[_COMMUNITY_Phase 3 Product Roadmap|Phase 3 Product Roadmap]]
- [[_COMMUNITY_LLM & Scouting Features|LLM & Scouting Features]]

## God Nodes (most connected - your core abstractions)
1. `Base` - 8 edges
2. `parse_advanced()` - 8 edges
3. `get_session()` - 7 edges
4. `fetch_season()` - 7 edges
5. `0001_initial migration` - 7 edges
6. `clean()` - 6 edges
7. `load_season()` - 6 edges
8. `main()` - 6 edges
9. `parse_salaries()` - 6 edges
10. `resolve_slug()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `Data Pipeline Architecture (numbers→ETL, words→LLM)` --conceptually_related_to--> `parse_advanced()`  [INFERRED]
  docs/02-technical-design.md → backend/scoutiq/sources/bbref.py
- `Data Pipeline Architecture (numbers→ETL, words→LLM)` --conceptually_related_to--> `fetch_season()`  [INFERRED]
  docs/02-technical-design.md → backend/scoutiq/sources/nba.py
- `Contract Valuation Engine` --references--> `Model Metrics JSON (R²=0.77, MAE=2.9%)`  [INFERRED]
  ScoutIQ.md → backend/scoutiq/model/artifacts/metrics.json
- `parse_advanced()` --semantically_similar_to--> `fetch_season()`  [INFERRED] [semantically similar]
  backend/scoutiq/sources/bbref.py → backend/scoutiq/sources/nba.py
- `Contract Valuation Engine` --references--> `Valuation Model Backtest Report v0`  [INFERRED]
  ScoutIQ.md → backend/scoutiq/model/artifacts/report.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **ETL pipeline: nba.com stats + BBRef enrichment -> DB via shared db/config/models** — etl_load_stats, etl_load_bbref, etl_load_cap_constants, scoutiq_db, scoutiq_models [EXTRACTED 0.95]
- **Model training pipeline: dataset -> features -> train (with conformal intervals + temporal split)** — model_dataset, model_features, model_train, concept_conformal_intervals, concept_temporal_split [EXTRACTED 0.95]
- **Data layer: ORM models + Alembic migration + engine/session form the persistent storage foundation** — scoutiq_models, alembic_versions_0001_initial, scoutiq_db, alembic_env [EXTRACTED 0.95]
- **BBRef Scraping + Crosswalk Pipeline** — sources_bbref_fetch_player_html, sources_bbref_parse_advanced, sources_bbref_parse_salaries, sources_crosswalk_resolve_slug [EXTRACTED 0.95]
- **LLM / AI Feature Layer** — scoutiqmd_scout_report_analysis, scoutiqmd_llm_eval_harness, scoutiqmd_perplexity_sonar_layer [INFERRED 0.85]
- **Phase 3 Product Layer** — scoutiqmd_what_if_cap_simulator, docs_techdesign_salary_cap_modeling, docs_progresslog_phase3 [EXTRACTED 0.95]

## Communities (19 total, 0 thin omitted)

### Community 0 - "BBRef Scraper & Parser"
Cohesion: 0.14
Nodes (21): DataFrame, bbref_slug(), fetch_player_html(), normalize_name(), page_player_name(), parse_advanced(), parse_salaries(), player_url() (+13 more)

### Community 1 - "Database Schema & ORM"
Cohesion: 0.16
Nodes (16): Alembic environment — pulls the DB URL from scoutiq.config and metadata from sco, 0001_initial migration, JSONB columns for evolving stats (box + advanced), NBA API IDs as natural primary keys (no surrogate crosswalk for stats), DeclarativeBase, Base, CapConstants, Player (+8 more)

### Community 2 - "Valuation Model Training"
Cohesion: 0.14
Nodes (18): DataFrame, DataFrame, Split-conformal prediction intervals, Production-implied market value (no salary leakage), Salary stickiness — persistence baseline beats production model on mid-contract, Strict temporal train/test split (no leakage), build_dataset(), primary_position() (+10 more)

### Community 3 - "ETL Data Pipeline"
Cohesion: 0.16
Nodes (13): Trainable row definition: advanced@t + salary@t+1 + cap@t+1, Data-quality gate: how much of the data is actually trainable?  A v0 training ex, run(), _scalar(), _int_or_none(), Seed cap_constants from the reference CSV. Idempotent (upsert by season).  max_2, run(), Build the modeling table from the data layer.  One row per (player, season t) th (+5 more)

### Community 4 - "Player Identity Resolution"
Cohesion: 0.18
Nodes (15): Any, nba_id -> BBRef slug crosswalk (PlayerXref), _enrich_one(), _players_to_enrich(), Enrich with Basketball-Reference: advanced metrics (BPM/VORP/WS/...) + position, run(), _valid_pos(), load_season() (+7 more)

### Community 5 - "Model Performance Metrics"
Cohesion: 0.13
Nodes (14): calibration, interval_80_coverage, interval_80_half_width_pct, mae_pct_of_cap, mae_usd, model_version, n_calibration, n_midcontract (+6 more)

### Community 6 - "Data Source Spikes"
Cohesion: 0.40
Nodes (9): bbref_slug(), main(), probe_bbref_contracts(), probe_nba_api(), Reproduce BBRef's player-id slug heuristic: first 5 of last name + first 2 of fi, Sports-Reference buries many tables inside <!-- ... --> comments. Unwrap them., require(), section() (+1 more)

### Community 7 - "NBA API Data Ingestion"
Cohesion: 0.32
Nodes (7): DataFrame, Data Pipeline Architecture (numbers→ETL, words→LLM), _league_dash (LeagueDashPlayerStats wrapper), fetch_season(), _league_dash(), nba.com (stats.nba.com) adapter via nba_api.  We use `LeagueDashPlayerStats` (le, Return one row per player for `season`, merging Base + Advanced on PLAYER_ID.

### Community 8 - "Model Visualization Artifacts"
Cohesion: 0.40
Nodes (6): Interval Calibration Chart (conformal prediction), Conformal Prediction Coverage (well-calibrated empirical ≈ nominal), Ideal Calibration Diagonal (nominal = empirical), Model Accuracy Signal (R²=0.77, salary % of cap), High-salary Prediction Variance (overpaid outliers visible), Predicted vs Actual Scatter Plot (test 2023-25)

### Community 9 - "Configuration & Settings"
Cohesion: 0.33
Nodes (3): BaseSettings, ['2012-13', '2013-14', ..., '2024-25'] — NBA season string format., Settings

### Community 10 - "Advanced Stats Exploration"
Cohesion: 0.70
Nodes (4): bbref_slug(), probe_bbref_advanced(), probe_nba_advanced(), section()

### Community 11 - "Valuation Engine Design"
Cohesion: 0.67
Nodes (3): Model Metrics JSON (R²=0.77, MAE=2.9%), Valuation Model Backtest Report v0, Contract Valuation Engine

### Community 12 - "Phase 3 Product Roadmap"
Cohesion: 0.67
Nodes (3): Phase 3 — Cap Simulator + FastAPI + Dashboard, Simplified CBA Salary Cap Model, What-If Contract & Cap Simulator

### Community 13 - "LLM & Scouting Features"
Cohesion: 0.67
Nodes (3): LLM Evaluation Harness, Perplexity Sonar Qualitative Layer, Scout Report Analysis (LLM → structured ratings)

## Knowledge Gaps
- **25 isolated node(s):** `Session`, `Any`, `model_version`, `n_train`, `n_calibration` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_advanced()` connect `BBRef Scraper & Parser` to `NBA API Data Ingestion`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `fetch_season()` connect `NBA API Data Ingestion` to `BBRef Scraper & Parser`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `Settings` connect `Configuration & Settings` to `ETL Data Pipeline`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `parse_advanced()` (e.g. with `Data Pipeline Architecture (numbers→ETL, words→LLM)` and `fetch_season()`) actually correct?**
  _`parse_advanced()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `fetch_season()` (e.g. with `Data Pipeline Architecture (numbers→ETL, words→LLM)` and `parse_advanced()`) actually correct?**
  _`fetch_season()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Alembic environment — pulls the DB URL from scoutiq.config and metadata from sco`, `Central config. Reads DATABASE_URL (and friends) from backend/.env.`, `['2012-13', '2013-14', ..., '2024-25'] — NBA season string format.` to the rest of the system?**
  _59 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `BBRef Scraper & Parser` be split into smaller, more focused modules?**
  _Cohesion score 0.14130434782608695 - nodes in this community are weakly interconnected._