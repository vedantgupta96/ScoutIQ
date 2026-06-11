# ScoutIQ — Progress Log

_Last updated: 2026-06-07. Snapshot of what's built, what works, what broke, and what's next._

## Status at a glance
| Phase | Scope | Status |
|---|---|---|
| 1 | Data layer (schema, ETL, dataset) | ✅ complete |
| 2 | Valuation model + backtest | ✅ complete |
| 3 | Cap simulator + FastAPI + dashboard | ✅ core complete |
| 4 | Contract timeline, comps, grounded rationale | ⏳ next |

Twenty PRs are merged to `main`, with the current work adding player headshots. Workflow is feature
branch → PR → squash-merge per phase. Database is a live hosted **Neon** Postgres.

---

## What's been built

### Phase 1 — Data layer
A clean, query-ready NBA dataset that the model trains on.

- **Schema** (SQLAlchemy 2.0 + Alembic, Postgres + pgvector): `players`, `player_seasons` (box +
  advanced stats as JSONB), `player_salaries` (realized historical, from BBRef), `player_xref`
  (nba_id ↔ verified BBRef slug), `teams`, `cap_constants`.
- **Source adapters:** `nba_api` for stats (box + advanced: USG/TS/PIE/ratings); Basketball-Reference
  for all-in-one metrics (BPM/VORP/WS), position, and realized salary — scraped, comment-stripped,
  cached to disk, rate-limited.
- **ETL** (idempotent upserts): cap-constants seed, league-wide stats per season, BBRef enrichment, and
  a `check_coverage` gate that reports the trainable-row count.

**Result:** 2025-26 data is now loaded into the product path, with current roster state, cap constants,
forward Spotrac contract structure, and bridged 2025-26 contract cap hits for valuation comparisons.

### Phase 2 — Valuation model
Estimates a player's **production-implied market value** (salary as % of cap) from on-court production —
deliberately *not* using their current salary, so the gap to actual pay is the actionable signal.

- **Framing:** features = production at season *t* → value at *t+1*; strict temporal split (no leakage).
- **Model:** HistGradientBoosting (handles NaN natively).
- **Uncertainty:** split-conformal prediction intervals (marginal coverage guarantee).
- **Backtest:** train target-seasons ≤ 2023-24, test 2024-25 & 2025-26.
- **Outputs (committed):** `report.md`, calibration + predicted-vs-actual plots, `metrics.json`, and a
  per-player `valuations_test.csv`.

**Result (test 2024-26):** R² **0.767** · MAE **3.128% of cap** (~$4.6M) vs 6.98% naive · 80%
interval coverage **0.797**. Calibration lands almost exactly on target, and the 2025-26 rows use
Spotrac-sourced per-season cap hits as evaluation/pay comparison data.

### Phase 3 — API, dashboard, and simulator
The core product cockpit is now working.

- **FastAPI:** health/current-season, player search/profile, valuation, batched player cards, contract
  watchlist, simulator, backtest metadata/valuations, scout-rating eval, player scout-rating fixture
  aggregation, and cached player headshots.
- **Dashboard:** Next.js app with players/watchlist, player profile, simulator, and model/backtest views.
- **Simulator:** simplified-but-explicit CBA subset, 2025-26 default contract start, actual loaded
  2025-26 cap constants, future cap projection, option/guarantee sliders, and assumption flags.
- **Watchlist:** bucket/sort/position/search filters; valuation pinned to the displayed season so
  2025-26 stats and salary coverage do not silently drop players.
- **Scout eval:** offline synthetic fixture harness is exposed in API/UI, but live LLM/Sonar ingestion is
  intentionally not in the request path yet.

---

## Achievements
- End-to-end, reproducible pipeline from raw public sources → calibrated valuations, all verified against
  a live database.
- **Rigor, not just a model:** a published temporal backtest, conformal intervals with a calibration
  curve, permutation-importance explainability, and a naive baseline for context.
- **Honesty as a feature:** documented where the model *loses* (see below) instead of hiding it.
- Clean engineering: idempotent/resumable ETL, disk caching, fault-tolerance, secrets kept out of git.

---

## Problems faced (and how they were solved)
Most were caught by actually running the pipeline, not by reading code:

| Problem | Cause | Fix |
|---|---|---|
| Accented names became mojibake (`Dončić`) | `requests` decoded UTF-8 page as Latin-1 | force `resp.encoding = "utf-8"` |
| `varchar(16)` overflow crashed the scrape | BBRef puts notes ("Did not play…") in the `Pos` cell | validate position to real codes only |
| One bad player aborted a 1,600-player run | unhandled exception per player | per-player try/except; log + continue |
| 5 players errored mid-scrape | pandas `read_html` needed a fallback parser | add `html5lib` + `beautifulsoup4` |
| ~30 players unmatched (e.g. Jalen Green) | common surnames push BBRef slugs past suffix 03 | deepen collision search (`max_suffix` 3 → 12) |
| Crosswalk flagged correct slugs as mismatch | exact-match vs the page `<title>` ("Name Stats, …") | prefix-match the title |
| `DetachedInstanceError` | read an ORM attr after the session closed | read inside the session scope |
| Watchlist dropped players after 2025-26 data load | values were computed against latest stats season with incomplete salary coverage | pin card valuation to the watchlist target season |
| Watchlist candidate cap hid top mismatches | alphabetical candidate cap excluded relevant players before ranking | order candidates by minutes and use a season-sized candidate cap |
| Spotrac pages shifted columns / extension tables | fixed-index first-table parser missed cap-hit rows | header-driven parser scans all cap-hit tables |
| Contract re-scrapes left stale duplicates | dedup key changed when parser/source shifted `season_start` | clean-replace existing player contracts before insert |
| Missing headshots could repeatedly hit the CDN | no negative cache for players without NBA CDN images | cache missing-image sentinels and fall back to initials |

---

## Key decisions & pivots
- **Sport = NBA, persona = front office, posture = calibrated/honest.** NBA is the only league where
  valuation + a real cap + guaranteed contracts + scouting text all coexist.
- **Hosted Neon over local Postgres/Docker; SQLAlchemy + Alembic; nba.com Advanced + BBRef BPM/VORP/WS.**
- **Current season is backend-owned.** `/health.current_season` drives the shell label so the UI does not
  drift from `LATEST_SEASON`.
- **Target as % of cap, not raw dollars** — normalizes ~10%/yr cap inflation so the backtest is honest.
- **The big pivot — value model, not salary forecast.** The original plan predicted next-year *paid*
  salary. Testing revealed that's dominated by contract mechanics: a dumb "next year = this year"
  persistence baseline beats any model on mid-contract players, because their pay is contractually
  locked. So we reframed to predict **production-implied value** (excluding current salary). This is
  more on-thesis for "what is a player worth," and it produces the bargains/overpays output that makes
  the model genuinely useful.

---

## Known limitations
- **Salary stickiness:** persistence beats the model on mid-contract players (expected; we exclude salary
  on purpose). The fix is forward contract data (Spotrac) to evaluate at contract-decision points.
- **Forward contract structure is present but not yet fully surfaced.** `contracts`/`contract_years`
  exist and feed 2025-26 salary bridging; the next product step is a visible current-contract timeline
  and extension simulation flow.
- **Name matching:** ~15 `mismatch` / ~106 `not_found` players remain (accents, Jr./Sr., no BBRef page).
- **Cap rules** are a simplified subset of the CBA (no Bird rights / exceptions / repeater tax yet).

---

## Experiment: playoff features (null result, reverted — 2026-06-09)
**Question:** does adding playoff performance to the model improve the production-implied value backtest?
Teams pay for playoff impact, so it's a plausible signal the regular-season-only model misses.

**Method:** ingested nba.com postseason stats (`SeasonType=Playoffs`, all 14 seasons) into two new JSONB
columns, derived 6 NaN-tolerant features — `made_playoffs`, `po_minutes`, `po_pie`, `po_net_rating`, and
the **elevation deltas** `pie_delta`/`net_rating_delta` (playoff − regular). Ran an **ablation on
identical data** (same 4321 train / 795 test rows; only the feature set varied) so the comparison was
clean, not confounded by the data refresh that came with reloading nba.com stats.

**Result — no framing earns its place:**

| subset | R² | MAE % cap |
|---|---|---|
| none (baseline) | **0.7692** | 3.098 |
| made_playoffs flag only | 0.7692 | 3.090 |
| deltas only | 0.7675 | 3.091 |
| po_minutes only | 0.7661 | 3.087 |
| all 6 | 0.7622 | 3.107 |

The best case (flag only) ties baseline R² with an MAE delta inside the noise; everything richer
regresses. Playoff quality is collinear with the regular-season production the model already ingests
(BPM/PIE/ratings), so it adds dimensionality without lift. **Per the "keep only if it improves" rule, the
model + data-layer changes were reverted.** A documented null result, not a shipped feature.

**Process note / lesson:** re-running the full `load_stats` to backfill playoff columns overwrote the
`advanced` JSONB that `load_bbref` co-owns (BPM/VORP/WS), which zeroed trainable rows; recovered by
re-merging from the cached BBRef HTML (no data permanently lost). Takeaway: prefer a *targeted* column
update over a broad table reload, and/or make `load_stats` merge into `advanced` rather than overwrite it.

---

## Hardening + simulator depth pass (2026-06-10)

A focused post-Phase-2 pass on four maintenance/depth items (plus a housekeeping decision), all
backend-only or API-client-only — no Next.js component changes.

- **Season-label hardening.** Added `scoutiq.api.season` (`is_valid_season` / `validate_season` /
  `next_season`) and routed every season entry point through it. A malformed season in the simulator
  (`start_season` / `valuation_season`) or the team cap-sheet now returns a clean **422** instead of a
  leaked `int()` ValueError; `players._next_season` delegates to the shared helper (also fixes a century
  rollover, e.g. `1999-00 → 2000-01`).
- **Rationale coverage clarity.** A scouted player with no valuation-capable season (load-managed /
  injured) now gets a specific, actionable 404 instead of a generic "no stats." Added
  `scoutiq.etl.check_rationale_coverage`, an offline read-only audit bucketing every rostered/scouted/
  valued player into `ready` / `load_managed` / `no_scout_coverage` / `no_coverage` (never calls Sonar
  or Claude).
- **Cap-simulator depth.** The what-if simulator now overlays a proposed first-year cap hit onto a real
  team's payroll (optional `team_id`, netting out the player's existing figure on a re-sign) to show the
  resulting tax/apron **tier and its 2023-CBA consequences**. New `POST /simulate/compare` runs 2–5
  proposed contracts side by side with face-value totals, the value gap, and best-value/cheapest picks.
  Tier classification and the contract-then-salary cap-hit precedence are now shared helpers
  (`classify_tier`, `team_cap_hits`) the team cap sheet reuses.
- **Housekeeping.** `skills-lock.json` (local installed-skill lock) is gitignored as local agent config,
  alongside `.claude/` and `.agents/skills/`.

Tests went from 52 → 81 passing; frontend `npm run build` + TypeScript clean; impeccable a11y detector
reports no issues. One latent note: API tests run on SQLite where `DISTINCT ON` is silently ignored
(prod is Neon Postgres, where it works) — a test-fidelity gap, not a prod bug.

---

## Next
The highest-leverage next feature is **current contract timeline + one-click extension simulation**:
show what the player is owed, compare it to production-implied value, and let the user launch a proposed
extension from the current deal. After that, similar-player/contract comps and grounded rationale
generation are the most natural additions.
