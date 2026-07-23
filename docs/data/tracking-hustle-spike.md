# ScoutIQ — NBA Tracking/Hustle Data Feasibility Spike (issue #94)

> **Status: PARTIAL — probe infrastructure only, this is not a completed spike.** The source was
> unreachable from this environment (§6.1), so the things this spike exists to measure — the
> season-by-season **coverage matrix**, the **ID join rate**, **per-field null rates**, and this
> doc's own proceed/limitations/stop **recommendation** (§7) — are all **UNMEASURED**, not
> "clean" or "acceptable." What *is* done and stands as evidenced: the adapter/CLI probe itself,
> its offline fixtures/tests, and the reachability evidence in §6.1 showing the block is
> source-side (NBA edge/WAF), not a local network problem. None of that evidenced-blocking
> material below is softened or walked back by this status line — it stays as reported.
>
> **Purpose:** answer whether nba.com's tracking/hustle endpoints (Second Spectrum-derived
> player tracking, exposed via `nba_api`) are usable as future six-axis role inputs — before any
> DB migration, loader, or model change is attempted.
>
> **Scope of this doc:** the read-only probe (adapter + CLI + fixtures/tests) is built and verified
> offline in this pass. The **Live validation results** (§6) and **Recommendation** (§7) sections
> below are populated — but only with the live-run *attempt* and its outcome (source unreachable).
> They do not report the coverage/join/null numbers the spike set out to produce, because none
> were measured; see the status line above.

---

## 1. Endpoint & field inventory

Four player-level families, all confirmed present in `nba_api==1.11.4` (checked via
`inspect.signature` against the installed package — no network call):

| Family | nba_api class | Parameterised by | Fixed kwargs used |
|--------|---------------|-------------------|--------------------|
| `hustle` | `leaguehustlestatsplayer.LeagueHustleStatsPlayer` | — | `season` |
| `tracking` | `leaguedashptstats.LeagueDashPtStats` | `pt_measure_type` (`Drives`, `Passing`, `Rebounding`, `CatchShoot`) | `season`, `player_or_team="Player"` |
| `defense` | `leaguedashptdefend.LeagueDashPtDefend` | — | `season` |
| `shooting` | `leaguedashplayerptshot.LeagueDashPlayerPtShot` | — | `season` |

**Player-id join column is NOT uniform across families** — this is the single most important
gotcha for a future loader:

| Family | Player id column |
|--------|-------------------|
| `hustle` | `PLAYER_ID` |
| `tracking` | `PLAYER_ID` |
| `defense` | `CLOSE_DEF_PERSON_ID` |
| `shooting` | `PLAYER_ID` |

### Candidate columns per family (from nba_api's documented/observed response shape)

These are the columns this spike's fixtures encode and that the probe's null-rate check inspects.
They are believed accurate from nba_api's known response schema for these endpoints, but **have not
been confirmed against a live response in this pass** — the live run should record any column-name
drift (nba.com has changed field names across seasons before).

- **hustle**: `PLAYER_ID`, `PLAYER_NAME`, `TEAM_ABBREVIATION`, `AGE`, `G`, `MIN`, `CONTESTED_SHOTS`,
  `CONTESTED_SHOTS_2PT`, `CONTESTED_SHOTS_3PT`, `DEFLECTIONS`, `CHARGES_DRAWN`, `SCREEN_ASSISTS`,
  `SCREEN_AST_PTS`, `LOOSE_BALLS_RECOVERED`, `OFF_BOXOUTS`, `DEF_BOXOUTS`, `BOX_OUTS`
- **tracking / Drives**: `PLAYER_ID`, `PLAYER_NAME`, `TEAM_ABBREVIATION`, `GP`, `MIN`, `DRIVES`,
  `DRIVE_FGM`, `DRIVE_FGA`, `DRIVE_FG_PCT`, `DRIVE_FTM`, `DRIVE_FTA`, `DRIVE_PTS`, `DRIVE_PASSES`,
  `DRIVE_AST`, `DRIVE_TOV`, `DRIVE_PF`
- **tracking / Passing** (not fixture-covered, column list unconfirmed offline): expected
  `PASSES_MADE`, `PASSES_RECEIVED`, `AST`, `SECONDARY_AST`, `POTENTIAL_AST`, `AST_POINTS_CREATED` —
  **not verified against a live response; flag for the live run.**
- **tracking / Rebounding** (not fixture-covered, unconfirmed offline): expected
  `REB_CHANCES`, `REB_CHANCE_PCT`, `OREB_CONTEST`, `DREB_CONTEST` — **unconfirmed, flag for live run.**
- **tracking / CatchShoot** (not fixture-covered, unconfirmed offline): expected
  `CATCH_SHOOT_FGM`, `CATCH_SHOOT_FGA`, `CATCH_SHOOT_FG_PCT`, `CATCH_SHOOT_PTS`,
  `CATCH_SHOOT_EFG_PCT` — **unconfirmed, flag for live run.**
- **defense**: `CLOSE_DEF_PERSON_ID`, `PLAYER_NAME`, `PLAYER_LAST_TEAM_ABBREVIATION`,
  `PLAYER_POSITION`, `AGE`, `GP`, `G`, `FREQ`, `D_FGM`, `D_FGA`, `D_FG_PCT`, `NORMAL_FG_PCT`,
  `PCT_PLUSMINUS`
- **shooting**: `PLAYER_ID`, `PLAYER_NAME`, `TEAM_ABBREVIATION`, `GP`, `G`, `FGA_FREQUENCY`, `FGM`,
  `FGA`, `FG_PCT`, `EFG_PCT`, `FG3M`, `FG3A`, `FG3_PCT`

**Explicit gap:** only `hustle`, `tracking/Drives`, `defense`, and `shooting` have sanitized
fixtures backing the offline tests in this pass. The other three `tracking` measure types
(`Passing`, `Rebounding`, `CatchShoot`) are wired into the probe and adapter but their exact column
names could not be confirmed without a network call — the live run should capture and correct these.

### Sampling methodology (rotation-player qualification)

The probe does not compute join rate and null rate over `frame.head(N)` — an unfiltered `head(N)`
samples whatever order the endpoint happened to return rows in, which is not a representative
rotation-player set and would let a handful of two-minute-per-game players who never touch the
ball skew both rates. Instead:

- Rows are **qualified** by a minutes threshold before sampling: `--min-minutes` (default `200`)
  against whichever of `MIN`/`MINUTES`/`MIN_TOTAL` is present on the frame.
- Qualified rows are **sorted by minutes, descending**, and only then capped to `--sample-size`
  rows — so a bounded sample is the highest-minutes rows, not an arbitrary prefix.
- If the frame has **no minutes column at all**, the probe cannot qualify rows. It falls back to
  raw endpoint order (`head(N)`) and **prints a warning** (`sample.qualified = False` in the JSON
  output) stating that this fallback sample is **NOT representative** and that any rate computed
  from it should be treated accordingly. This is a deliberate degrade-and-say-so, not a silent
  substitution.

---

## 2. Proposed canonical input schema (for a future loader — not built in this pass)

If a loader is built later, the natural shape mirrors `player_seasons.advanced`/`box` (JSONB per
player-season), keyed the same way:

| Field | Type | Unit | Source family |
|-------|------|------|----------------|
| `player_id` | int | nba.com numeric id | join key — resolved per-family (see §1 id-column table) |
| `season` | str | `'2023-24'` | all |
| `contested_shots` | float | count, per season (Totals) | hustle |
| `deflections` | float | count | hustle |
| `screen_assists` | float | count | hustle |
| `loose_balls_recovered` | float | count | hustle |
| `drives` | float | count | tracking/Drives |
| `drive_pts_per_drive` | float | derived: `DRIVE_PTS / DRIVES` | tracking/Drives |
| `drive_ast_pct` | float | fraction [0,1] | tracking/Drives |
| `catch_shoot_efg_pct` | float | fraction [0,1] | tracking/CatchShoot |
| `def_fg_pct_allowed` | float | fraction [0,1] | defense |
| `def_fg_pct_diff` | float | derived: `D_FG_PCT - NORMAL_FG_PCT` | defense |
| `fg3_pct` (tracked shots) | float | fraction [0,1] | shooting |

All rate fields (`*_PCT`) are already fractions in nba.com's response, not percentages — a loader
must not re-divide by 100.

**Grain:** one row per `(player, season, family, measure_type)` — i.e. one row per player per
season per stat family, and for the `tracking` family, additionally per `pt_measure_type`
(`Drives`/`Passing`/`Rebounding`/`CatchShoot`). `hustle`, `defense`, and `shooting` have no
`measure_type` axis, so their grain collapses to `(player, season, family)`.

**Uniqueness key:** `(player_id, season, family, measure_type)`, with `measure_type = NULL` for
the three families that don't have one. `player_id` is the per-family id resolved via the §1
id-column table (`CLOSE_DEF_PERSON_ID` for `defense`, `PLAYER_ID` for the other three) — never a
name-based key.

**Provenance fields** (required on every row, not just the metric columns):

| Field | Meaning |
|-------|---------|
| `source_endpoint` | The `nba_api` class used, e.g. `leaguedashptstats.LeagueDashPtStats` |
| `season` | `'2023-24'`-style season string |
| `measure_type` | `pt_measure_type` for `tracking` rows, `NULL` otherwise |
| `fetched_at_utc` | Ingestion timestamp, from `FetchOutcome.fetched_at_utc` (§4) |
| `source` | Literal `'nba_stats'` — distinguishes this family from BBRef-sourced rows in the same eventual schema |

**Qualification thresholds:** a row is a *rotation-player* row only above a minutes floor
(`--min-minutes`, default `200`, see the Sampling methodology subsection in §1) — low-minutes
players produce noisy per-possession rates on small samples, so a loader should carry the
qualifying threshold (minutes, and possessions where the family exposes them) alongside the row
rather than filtering silently, so downstream consumers can re-qualify with a different bar.

**Missingness policy:** a null in any metric column means nba.com did not report that field for
that player-season (e.g. a stat introduced in a later season, or a `tracking/Passing`-style
measure type this spike could not confirm — §1). **A null must never be coerced to 0** — 0 drives
and "not reported" are different facts, and collapsing them would fabricate a rotation player who
never drives. A loader must preserve the null and let downstream consumers decide how to handle
it (exclude the player-season from that axis, impute explicitly and label it as imputed, etc.).

---

## 3. Metric → six-axis mapping

| Axis | Candidate metrics | Support |
|------|--------------------|---------|
| **Creation load** | `DRIVES`, `DRIVE_PASSES`, `DRIVE_AST`, `POTENTIAL_AST` (tracking/Passing, unconfirmed) | Plausibly supported — drive/passing volume is a reasonable creation-load proxy, pending Passing column confirmation. |
| **Rim pressure** | `DRIVES`, `DRIVE_FGA`, `DRIVE_PTS` | Partially supported — `DRIVES` is a **proxy** for rim pressure (how often a player drives), not direct rim-attempt evidence: a drive can end in a kick-out pass, a pull-up jumper, or a floater well outside the restricted area, none of which this family's columns distinguish. `DRIVE_FGA`/`DRIVE_PTS` narrow this somewhat but remain drive-outcome stats, not shot-location stats. |
| **Shooting gravity** | `CATCH_SHOOT_FGA`, `CATCH_SHOOT_EFG_PCT` (unconfirmed), `FG3A`/`FG3_PCT` (shooting) | Partially supported — catch-and-shoot volume/efficiency is the closest proxy available; true gravity (defender attention, closeout rates) is **not measured by any of these four families**. |
| **Connective play** | `DRIVE_PASSES`, `DRIVE_AST`, `SCREEN_ASSISTS` (hustle) | Supported — screen assists plus drive-and-kick passing are reasonable connective-play signals. |
| **Perimeter disruption** | `DEFLECTIONS` (hustle), `D_FGA`/`D_FG_PCT`/`PCT_PLUSMINUS` (defense) | Partially supported — `DEFLECTIONS` (hustle) is a reasonable perimeter-disruption signal on its own. The `defense` family (`LeagueDashPtDefend`) measures a defender's **overall** closest-defender field-goal-percentage impact, not specifically perimeter disruption — `D_FGA`/`D_FG_PCT`/`PCT_PLUSMINUS` are not filtered to perimeter possessions, so this axis is **not directly supported by the defense family**; that would need a shot-distance/zone filter this spike does not probe. |
| **Interior/rebounding impact** | `OFF_BOXOUTS`, `DEF_BOXOUTS`, `BOX_OUTS` (hustle), `REB_CHANCES`/`REB_CHANCE_PCT` (tracking/Rebounding, unconfirmed) | Partially supported — box-out counts are solid; true rebounding-chance conversion rate depends on the unconfirmed Rebounding columns. |

**Axes NOT credibly supported by these four families alone:** none of the six axes are fully
unsupported, but **shooting gravity** is the weakest — these endpoints measure a shooter's own
catch-and-shoot output, not the defensive attention a shooter draws off the ball (closeout speed,
gravity-driven driving lanes for teammates). That would require shot-quality/defender-distance data
this spike does not probe.

All of the above are **measured facts about tracked plays**, not official NBA ratings. Any derived
six-axis score built from them is ScoutIQ's own role-axis construction — it must never be presented
as, or confused with, a proprietary NBA/Second Spectrum rating.

---

## 4. Source freshness, attribution, pacing, and failure behavior

- **Freshness**: these are current-season, continuously updated stats.nba.com endpoints (same
  update cadence as the box-score endpoints `nba.py` already loads) — not historical archives with
  a fixed cutoff.
- **Attribution**: data originates from stats.nba.com (Second Spectrum tracking); ScoutIQ does not
  claim it as proprietary and would credit nba.com/Second Spectrum in any UI surface, matching the
  existing BBRef attribution posture in `bbref.py`.
- **Caching policy**: `backend/scoutiq/sources/nba_tracking.py` disk-caches every successful fetch
  to JSON under `backend/scoutiq/data/raw/tracking/`, keyed by `(family, season, measure_type)`. A
  cache hit never touches the network — verified by `test_cache_hit_never_touches_network`.
- **Pacing policy**: a minimum `1.5s` sleep between live requests (`DEFAULT_PAUSE_SECONDS`), a
  30–60s per-request timeout (default `45s`), and up to 3 bounded retry attempts with linear
  backoff (`pause * attempt`) before a request is reported as failed.
- **Failure behavior**: every fetch returns a structured `FetchOutcome` (`ok`, `rows`, `source`,
  `http_status`, `error_type`, `error_message`, `attempts`, `elapsed_s`, `fetched_at_utc`). A
  failure is never papered over with fabricated rows — `ok=False` propagates to the probe CLI,
  which prints it and exits non-zero, and to any caller (see
  `test_failed_outcome_reported_as_failure_not_fabricated`).

---

## 5. Reproducible commands

```bash
# Help text only — no network, no DB:
backend/.venv/bin/python -m scoutiq.etl.check_tracking_coverage --help

# Full probe against the two most recent seasons, machine-readable output:
backend/.venv/bin/python -m scoutiq.etl.check_tracking_coverage \
  --season 2024-25 --season 2023-24 \
  --measure-types Drives,Passing,Rebounding,CatchShoot \
  --sample-size 200 --min-minutes 200 \
  --pause 1.5 --timeout 45 \
  --json

# Force live requests, bypassing the disk cache:
backend/.venv/bin/python -m scoutiq.etl.check_tracking_coverage --season 2024-25 --no-cache

# Offline tests (fixtures only, no network):
backend/.venv/bin/pytest backend/tests/test_tracking_coverage.py -q
```

---

## 6. Live validation results

The live run was attempted and **the source was unreachable from this environment**. Per the
spike's own rule, that is recorded here as an evidenced result. **No coverage matrix, join rate,
or null rate is reported, because none was measured.** Nothing in this section is derived from the
offline fixtures — the fixtures exist only to test the probe's logic and carry no coverage meaning.

### 6.1 Reachability evidence

The environment itself has working outbound access; NBA-owned hosts specifically refuse it.

| # | Target | Method | Result | Timestamp (UTC) |
|---|---|---|---|---|
| 1 | `example.com` | curl | **HTTP 200** in 0.05 s | 2026-07-22T03:59:39Z |
| 2 | `api.github.com` | curl | **HTTP 200** in 0.13 s | 2026-07-22T03:59:39Z |
| 3 | `cdn.nba.com/static/json/...` | curl | **HTTP/2 403** in 0.06 s — body `<TITLE>Access Denied</TITLE>` ("You don't have permission to access…"), edge-style denial | 2026-07-22T04:02:10Z |
| 4 | `official.nba.com` | curl | **HTTP 403** in 0.09 s | 2026-07-22T03:59:39Z |
| 5 | `stats.nba.com/stats/leaguedashptstats` (browser-style headers incl. `Referer`, `x-nba-stats-origin`, `x-nba-stats-token`) | curl ×3 with backoff | **HTTP 000** (no response), 20.0 s each, 3/3 attempts | 2026-07-22T04:02:10Z |
| 6 | `stats.nba.com` via `nba_api` `LeagueHustleStatsPlayer` | library call | **`ReadTimeout`** after 41.1 s | 2026-07-22T04:05:07Z |

Rows 1–2 establish that outbound network access is not blocked. Rows 3–6 establish that the refusal
is specific to NBA hosts: an immediate 403 at the CDN/official edge, and a silent connection
timeout at `stats.nba.com` even with the headers `nba_api` normally sends. The 403 body is a
generic edge "Access Denied" page, consistent with a WAF/edge rule rejecting this client or IP
range rather than an application error.

### 6.2 Probe run

Command (exactly as in §5, with a shortened timeout so three retries fit a bounded run):

```bash
.venv/bin/python -m scoutiq.etl.check_tracking_coverage \
  --season 2024-25 --season 2023-24 --measure-types Drives \
  --timeout 12 --pause 1.5 --json
```

Window: **2026-07-22T04:28:36Z → 04:34:04Z**. Process **exit code 1** (the probe's non-zero-on-
source-failure contract). Sample definition: all four families × two seasons; the `tracking` family
restricted to `PtMeasureType=Drives` to bound total runtime. Every request was `source=live`
(cold cache).

| Family | Season | Outcome | Attempts | Elapsed | HTTP status | Error | `fetched_at_utc` |
|---|---|---|---|---|---|---|---|
| hustle | 2024-25 | FAILED | 3 | 40.62 s | none | `ReadTimeout` | 04:29:19Z |
| hustle | 2023-24 | FAILED | 3 | 40.65 s | none | `ReadTimeout` | 04:30:00Z |
| tracking (Drives) | 2024-25 | FAILED | 3 | 40.63 s | none | `ReadTimeout` | 04:30:42Z |
| tracking (Drives) | 2023-24 | FAILED | 3 | 40.84 s | none | `ReadTimeout` | 04:31:24Z |
| defense | 2024-25 | FAILED | 3 | 40.72 s | none | `ReadTimeout` | 04:26:09Z¹ |
| defense | 2023-24 | FAILED | 3 | 40.63 s | none | `ReadTimeout` | 04:26:50Z¹ |
| shooting | 2024-25 | FAILED | 3 | 40.62 s | none | `ReadTimeout` | 04:27:30Z¹ |
| shooting | 2023-24 | FAILED | 3 | 40.63 s | none | `ReadTimeout` | 04:28:11Z¹ |

¹ Timestamps for `defense`/`shooting` are from the first of two identical consecutive runs
(04:22:44Z → 04:28:11Z); the second run reproduced the same outcome for all eight combinations.

All eight failed identically: `HTTPSConnectionPool(host='stats.nba.com', port=443): Read timed
out.` — 8/8 request failures, 0 rows returned, 24 total attempts. Retrying did not change the
outcome.

### 6.3 What therefore remains unmeasured

- Season-by-season **coverage matrix** — unmeasured.
- **ID-based join rate** against `players.player_id` — unmeasured.
- **Per-field null rates** — unmeasured.
- The unconfirmed `tracking/Passing`, `tracking/Rebounding`, and `tracking/CatchShoot` column names
  (§1) remain **unconfirmed**.

---

## 7. Recommendation

**Blocked — cannot assess feasibility from this environment.** Not a "stop": nothing observed says
the data is unsuitable, only that it could not be reached here.

| Question | Verdict |
|---|---|
| Is the source reachable from this environment? | **No** — NBA edge refuses this client (§6.1) |
| Is outbound access itself the problem? | **No** — unrelated hosts return 200 |
| Can six-axis feasibility be judged yet? | **No** — no rows retrieved, so no join/null evidence |
| Is the probe ready to produce that evidence? | **Yes** — deterministic CLI, exits 1 on failure, caches, paces, tested offline |

### Next step

Re-run §6.2's command from a network NBA does not refuse (a residential/office connection is the
usual remedy; `stats.nba.com` is well known to reject cloud and datacenter ranges). The probe
caches to disk, so a single successful run is enough to populate §6 permanently and the results can
be committed without re-hitting the source.

Two decisions should stay open until those numbers exist:

1. Whether the **ID join rate** is high enough to avoid name matching. The probe deliberately joins
   on `PLAYER_ID` only and reports unmatched ids rather than guessing; if the rate is poor, that is
   a finding about identity, not licence to add fuzzy matching.
2. Whether **shooting gravity** is supportable at all. §3 already flags it as the weakest of the six
   axes on the available fields; a live column inventory decides whether it survives as a measured
   axis or has to be dropped from Role Intelligence v2.

Until then, no percentile, index, or axis derived from this source should be presented anywhere in
the product — and per §3, a derived percentile must never be described as an official NBA rating.
