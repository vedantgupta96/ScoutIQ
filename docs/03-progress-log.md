# ScoutIQ — Progress Log

_Last updated: 2026-06-06. Snapshot of what's built, what works, what broke, and what's next._

## Status at a glance
| Phase | Scope | Status |
|---|---|---|
| 1 | Data layer (schema, ETL, dataset) | ✅ complete |
| 2 | Valuation model + backtest | ✅ complete |
| 3 | Cap simulator + FastAPI + dashboard | ⏳ next |

Three PRs merged to `main` (data layer · scrape-robustness fix · valuation model). Workflow is
feature-branch → PR → squash-merge per phase. Database is a live hosted **Neon** Postgres.

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

**Result:** 6,829 player-seasons · 1,673 players · 13 seasons (2012-13 → 2024-25); 1,552 players matched
to BBRef and verified; **4,719 trainable rows**.

### Phase 2 — Valuation model
Estimates a player's **production-implied market value** (salary as % of cap) from on-court production —
deliberately *not* using their current salary, so the gap to actual pay is the actionable signal.

- **Framing:** features = production at season *t* → value at *t+1*; strict temporal split (no leakage).
- **Model:** HistGradientBoosting (handles NaN natively).
- **Uncertainty:** split-conformal prediction intervals (marginal coverage guarantee).
- **Backtest:** train target-seasons ≤ 2022-23, test 2023-24 & 2024-25.
- **Outputs (committed):** `report.md`, calibration + predicted-vs-actual plots, `metrics.json`, and a
  per-player `valuations_test.csv`.

**Result (test 2023-25):** R² **0.77** · MAE **2.9% of cap** (~$4.0M) vs 6.9% naive · 80% interval
coverage **0.85**. Calibration tracks nominal across all levels. The largest value-vs-pay gaps are
basketball-credible (underpaid: Bane, Haliburton, J. Williams; overpaid: Simmons, LaVine, Beal, Gobert).

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

---

## Key decisions & pivots
- **Sport = NBA, persona = front office, posture = calibrated/honest.** NBA is the only league where
  valuation + a real cap + guaranteed contracts + scouting text all coexist.
- **Hosted Neon over local Postgres/Docker; SQLAlchemy + Alembic; nba.com Advanced + BBRef BPM/VORP/WS.**
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
- **No forward contract structure yet** — `contracts`/`contract_years` are defined-later; the cap
  simulator (Phase 3) will start with a simplified subset.
- **Name matching:** ~15 `mismatch` / ~106 `not_found` players remain (accents, Jr./Sr., no BBRef page).
- **Cap rules** are a simplified subset of the CBA (no Bird rights / exceptions / repeater tax yet).

---

## Next (Phase 3)
The part that makes it a product: a **FastAPI** service wrapping the model + the **What-If Contract & Cap
Simulator** (the signature feature) + a first dashboard. Forward contract structure (Spotrac) unlocks the
v1 contract-AAV target and richer cap math.
