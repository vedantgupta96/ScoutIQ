# Graph Report - .  (2026-06-07)

## Corpus Check
- Corpus is ~37,445 words - fits in a single context window. You may not need a graph.

## Summary
- 625 nodes · 1097 edges · 50 communities (43 shown, 7 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 179 edges (avg confidence: 0.61)
- Token cost: 45,171 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Player API & Valuation Endpoints|Player API & Valuation Endpoints]]
- [[_COMMUNITY_Scout-Rating LLM Eval|Scout-Rating LLM Eval]]
- [[_COMMUNITY_ETL & DB Migrations|ETL & DB Migrations]]
- [[_COMMUNITY_Data-Source Decisions & Rationale|Data-Source Decisions & Rationale]]
- [[_COMMUNITY_Frontend API Client|Frontend API Client]]
- [[_COMMUNITY_Frontend Package Deps|Frontend Package Deps]]
- [[_COMMUNITY_Model Features & Prediction|Model Features & Prediction]]
- [[_COMMUNITY_Basketball-Reference Adapter|Basketball-Reference Adapter]]
- [[_COMMUNITY_Backend API Tests|Backend API Tests]]
- [[_COMMUNITY_Spotrac Contracts ETL|Spotrac Contracts ETL]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Cap Simulator Engine|Cap Simulator Engine]]
- [[_COMMUNITY_App Shell & Layout|App Shell & Layout]]
- [[_COMMUNITY_Player Page & UI Helpers|Player Page & UI Helpers]]
- [[_COMMUNITY_Model Backtest Metrics|Model Backtest Metrics]]
- [[_COMMUNITY_nba_api Stats Adapter|nba_api Stats Adapter]]
- [[_COMMUNITY_Cap Simulator UI|Cap Simulator UI]]
- [[_COMMUNITY_Scout Ratings UI|Scout Ratings UI]]
- [[_COMMUNITY_ModelBacktest Page UI|Model/Backtest Page UI]]
- [[_COMMUNITY_Contract Watchlist UI|Contract Watchlist UI]]
- [[_COMMUNITY_Model Training & Conformal|Model Training & Conformal]]
- [[_COMMUNITY_Scout Eval Metrics|Scout Eval Metrics]]
- [[_COMMUNITY_Data-Source Probe Scripts|Data-Source Probe Scripts]]
- [[_COMMUNITY_Backtest API Endpoint|Backtest API Endpoint]]
- [[_COMMUNITY_Calibration Chart Figures|Calibration Chart Figures]]
- [[_COMMUNITY_Value Gauge Component|Value Gauge Component]]
- [[_COMMUNITY_Next.js Boilerplate Icons|Next.js Boilerplate Icons]]
- [[_COMMUNITY_Advanced Stats Probes|Advanced Stats Probes]]
- [[_COMMUNITY_Scout-Rating Eval Harness|Scout-Rating Eval Harness]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 43|Community 43]]

## God Nodes (most connected - your core abstractions)
1. `Player` - 22 edges
2. `FakeDB` - 22 edges
3. `PlayerSeason` - 21 edges
4. `CapConstants` - 19 edges
5. `DB` - 18 edges
6. `ScoutRating` - 17 edges
7. `compilerOptions` - 16 edges
8. `PlayerSummary` - 14 edges
9. `PlayerSalary` - 14 edges
10. `Player` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Data Pipeline Architecture (numbers→ETL, words→LLM)` --conceptually_related_to--> `parse_advanced()`  [INFERRED]
  /Users/vedantgupta/Documents/Claude/Projects/Nexus AI/docs/02-technical-design.md → backend/scoutiq/sources/bbref.py
- `Data Pipeline Architecture (numbers→ETL, words→LLM)` --conceptually_related_to--> `fetch_season()`  [INFERRED]
  /Users/vedantgupta/Documents/Claude/Projects/Nexus AI/docs/02-technical-design.md → backend/scoutiq/sources/nba.py
- `ScoutIQ Codex Adapter` --semantically_similar_to--> `Frontend CLAUDE.md (Includes AGENTS.md)`  [INFERRED] [semantically similar]
  AGENTS.md → frontend/CLAUDE.md
- `Polite Basketball-Reference Scraping` --rationale_for--> `Basketball-Reference Source`  [INFERRED]
  AGENTS.md → docs/01-data-source-spike.md
- `Cap Constants Are Data Not Code` --conceptually_related_to--> `cap_constants Table (Never Hard-Code)`  [INFERRED]
  AGENTS.md → docs/01-data-source-spike.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **LLM / AI Feature Layer** — scoutiqmd_scout_report_analysis, scoutiqmd_llm_eval_harness, scoutiqmd_perplexity_sonar_layer [INFERRED 0.85]
- **Phase 3 Product Layer** — scoutiqmd_what_if_cap_simulator, docs_techdesign_salary_cap_modeling, docs_progresslog_phase3 [EXTRACTED 0.95]
- **Production-Implied Valuation Model Pipeline** — readme_production_implied_value, readme_histgradientboosting, readme_conformal_intervals, readme_temporal_backtest [INFERRED 0.85]
- **Data-Source Go/No-Go Decision Set** — 01_data_source_spike_nba_api, 01_data_source_spike_bbref_salaries_table, 01_data_source_spike_forward_structure_risk, 01_data_source_spike_cap_constants_table [INFERRED 0.75]
- **Offline Scout-Rating Eval Flow** — backend_readme_offline_scout_eval, backend_readme_scout_ratings_eval_endpoint, backend_readme_synthetic_fixtures [INFERRED 0.85]

## Communities (50 total, 7 thin omitted)

### Community 0 - "Player API & Valuation Endpoints"
Cohesion: 0.09
Nodes (63): DB, Player, DB, Player, BaseModel, DeclarativeBase, PlayerScoutRatings, PlayerSeason (+55 more)

### Community 1 - "Scout-Rating LLM Eval"
Cohesion: 0.06
Nodes (54): ArgumentParser, Any, Path, ScoutRatingExtraction, Path, ScoutRating, Any, ScoutRating (+46 more)

### Community 2 - "ETL & DB Migrations"
Cohesion: 0.06
Nodes (37): Alembic environment — pulls the DB URL from scoutiq.config and metadata from sco, Session, Any, BaseSettings, Data-quality gate: how much of the data is actually trainable?  A v0 training ex, run(), _scalar(), _enrich_one() (+29 more)

### Community 3 - "Data-Source Decisions & Rationale"
Cohesion: 0.08
Nodes (29): Data-Source Spike, Basketball-Reference Source, BBRef Salaries Table (Historical Realized Salary), cap_constants Table (Never Hard-Code), Simplified-But-Correct CBA Subset, Forward Contract Structure Risk (Spotrac Plan B), BBRef Tables Buried in HTML Comments Gotcha, nba_api Source (leaguedashplayerstats) (+21 more)

### Community 4 - "Frontend API Client"
Cohesion: 0.10
Nodes (27): apiFetch(), BacktestCalibrationPoint, BacktestMetrics, ConfidenceMix, getBacktest(), getBacktestValuations(), getPlayer(), getPlayerCards() (+19 more)

### Community 5 - "Frontend Package Deps"
Cohesion: 0.08
Nodes (25): dependencies, clsx, framer-motion, lucide-react, next, @radix-ui/react-avatar, @radix-ui/react-slider, react (+17 more)

### Community 6 - "Model Features & Prediction"
Cohesion: 0.12
Nodes (21): get_db(), get_model(), FastAPI dependency providers., Session, Any, Session, primary_position(), Feature specification for the v0 valuation model.  Target: a player's salary as (+13 more)

### Community 7 - "Basketball-Reference Adapter"
Cohesion: 0.13
Nodes (21): DataFrame, bbref_slug(), fetch_player_html(), normalize_name(), page_player_name(), parse_advanced(), parse_salaries(), player_url() (+13 more)

### Community 8 - "Backend API Tests"
Cohesion: 0.22
Nodes (15): _client(), FakeDB, FakeScalarResult, test_backtest_returns_committed_metrics(), test_deprecated_simulator_alias_still_works(), test_player_cards_returns_batched_valuation_snippets(), test_player_scout_ratings_returns_fixture_aggregate(), test_player_search_accepts_reordered_name_tokens() (+7 more)

### Community 9 - "Spotrac Contracts ETL"
Cohesion: 0.17
Nodes (20): Path, _build_name_index(), _cache_path(), _cache_stale(), _get(), load_all(), _match_player(), _normalize() (+12 more)

### Community 10 - "TypeScript Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 11 - "Cap Simulator Engine"
Cohesion: 0.23
Nodes (15): build_season_sequence(), CapSimulation, ContractYear, _project_cap(), Cap simulator logic — simplified 2023 CBA subset.  Rules modeled:   - Salary cap, Run the cap simulation.      Option logic (applied from the END of the contract), Project cap thresholds forward from a base season using CAP_GROWTH_RATE., Return cap data for `years` seasons starting at start_season.      Uses DB data (+7 more)

### Community 12 - "App Shell & Layout"
Cohesion: 0.13
Nodes (11): metadata, NAV, Shell(), ShellProps, TITLES, Badge(), BadgeProps, Size (+3 more)

### Community 13 - "Player Page & UI Helpers"
Cohesion: 0.21
Nodes (15): PlayerPage(), capTier(), fmtM(), fmtPct(), gapLabel(), gapTone(), signed(), LeaderRow() (+7 more)

### Community 14 - "Model Backtest Metrics"
Cohesion: 0.13
Nodes (14): calibration, interval_80_coverage, interval_80_half_width_pct, mae_pct_of_cap, mae_usd, model_version, n_calibration, n_midcontract (+6 more)

### Community 15 - "nba_api Stats Adapter"
Cohesion: 0.17
Nodes (13): DataFrame, Data Pipeline Architecture (numbers→ETL, words→LLM), fetch_current_players(), fetch_season(), _league_dash(), nba.com (stats.nba.com) adapter via nba_api.  We use `LeagueDashPlayerStats` (le, Return one row per player for `season`, merging Base + Advanced on PLAYER_ID., Current NBA team reference rows from nba_api static metadata. (+5 more)

### Community 16 - "Cap Simulator UI"
Cohesion: 0.15
Nodes (9): ContractYearResponse, SimulatorResponse, TIER_COLORS, AssumptionFlag(), AssumptionFlagProps, Tone, TONE_COLORS, Card() (+1 more)

### Community 17 - "Scout Ratings UI"
Cohesion: 0.16
Nodes (9): FEATURE_META, ScoutTraitRow(), traitLabel(), PlayerScoutRatingsResponse, PlayerScoutTraitRating, ValuationResponse, SIZE, StatTile() (+1 more)

### Community 18 - "Model/Backtest Page UI"
Cohesion: 0.18
Nodes (11): BacktestResponse, BacktestValuationRow, ScoutRatingEvalResponse, ScoutRatingRow, compactSeasonRange(), fmtRate(), ModelPage(), RatingPill() (+3 more)

### Community 19 - "Contract Watchlist UI"
Cohesion: 0.16
Nodes (9): getPlayerWatchlist(), PlayerWatchlistResponse, WatchlistBucket, BUCKETS, POSITIONS, Avatar(), AvatarProps, initials() (+1 more)

### Community 20 - "Model Training & Conformal"
Cohesion: 0.26
Nodes (11): DataFrame, DataFrame, build_dataset(), conformal_q(), main(), _plots(), Train + backtest the v0 valuation model.  - Model: HistGradientBoostingRegressor, Split-conformal quantile of |residual| for a target coverage `level`. (+3 more)

### Community 21 - "Scout Eval Metrics"
Cohesion: 0.20
Nodes (9): evidence_hit_rate, exact_score_agreement, expected_trait_count, invalid_output_count, predicted_trait_count, total_notes, trait_coverage, validation_errors (+1 more)

### Community 22 - "Data-Source Probe Scripts"
Cohesion: 0.40
Nodes (9): bbref_slug(), main(), probe_bbref_contracts(), probe_nba_api(), Reproduce BBRef's player-id slug heuristic: first 5 of last name + first 2 of fi, Sports-Reference buries many tables inside <!-- ... --> comments. Unwrap them., require(), section() (+1 more)

### Community 23 - "Backtest API Endpoint"
Cohesion: 0.32
Nodes (7): BacktestResponse, get_backtest(), get_backtest_valuations(), GET /backtest — committed valuation-model backtest metadata and valuation rows., Return metadata for the published v0 valuation backtest., Return all rows from the committed test-set valuation artifact., ValuationRow

### Community 24 - "Calibration Chart Figures"
Cohesion: 0.40
Nodes (6): Interval Calibration Chart (conformal prediction), Conformal Prediction Coverage (well-calibrated empirical ≈ nominal), Ideal Calibration Diagonal (nominal = empirical), Model Accuracy Signal (R²=0.77, salary % of cap), High-salary Prediction Variance (overpaid outliers visible), Predicted vs Actual Scatter Plot (test 2023-25)

### Community 25 - "Value Gauge Component"
Cohesion: 0.47
Nodes (4): computeMax(), formatPct(), ValueGauge(), ValueGaugeProps

### Community 26 - "Next.js Boilerplate Icons"
Cohesion: 0.40
Nodes (5): File Icon (file.svg), Globe Icon (globe.svg), Next.js Logo (next.svg), Vercel Logo (vercel.svg), Window Icon (window.svg)

### Community 27 - "Advanced Stats Probes"
Cohesion: 0.70
Nodes (4): bbref_slug(), probe_bbref_advanced(), probe_nba_advanced(), section()

### Community 28 - "Scout-Rating Eval Harness"
Cohesion: 0.50
Nodes (4): Perplexity Sonar Scouting-Text Probe, Offline-First Scout-Rating Eval Harness, GET /llm/scout-ratings/eval Endpoint, Synthetic Project-Authored Eval Fixtures

### Community 29 - "Community 29"
Cohesion: 0.67
Nodes (3): Phase 3 — Cap Simulator + FastAPI + Dashboard, Simplified CBA Salary Cap Model, What-If Contract & Cap Simulator

### Community 30 - "Community 30"
Cohesion: 0.67
Nodes (3): LLM Evaluation Harness, Perplexity Sonar Qualitative Layer, Scout Report Analysis (LLM → structured ratings)

## Knowledge Gaps
- **124 isolated node(s):** `Session`, `Session`, `Any`, `evidence_hit_rate`, `exact_score_agreement` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_enrich_one()` connect `ETL & DB Migrations` to `nba_api Stats Adapter`, `Basketball-Reference Adapter`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `Player` connect `Player API & Valuation Endpoints` to `Backend API Tests`, `Spotrac Contracts ETL`, `Model Features & Prediction`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `ScoutRatingExtraction` connect `Scout-Rating LLM Eval` to `Player API & Valuation Endpoints`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `Player` (e.g. with `DB` and `Player`) actually correct?**
  _`Player` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `FakeDB` (e.g. with `CapConstants` and `Player`) actually correct?**
  _`FakeDB` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `PlayerSeason` (e.g. with `DB` and `Player`) actually correct?**
  _`PlayerSeason` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `CapConstants` (e.g. with `DB` and `Player`) actually correct?**
  _`CapConstants` has 15 INFERRED edges - model-reasoned connections that need verification._