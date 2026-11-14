# NBA data refresh for 2026-27 (SCO-49)

**Status, 2026-11-14:** the refresh path is fixed and tested, but the refresh itself has not run.
`stats.nba.com` refused every request from this machine, so no row was written. The database is
exactly as the baseline below describes. The remaining steps are listed in order under
[Remaining refresh steps](#remaining-refresh-steps).

2025-26 stays the completed-season valuation baseline. Nothing here retrains or promotes a model.

## What the loader fixes change

| Problem before | Behaviour now |
| --- | --- |
| `load_stats` replaced the whole `player_seasons.advanced` value, deleting the Basketball-Reference metrics (BPM, OBPM, DBPM, VORP, WS, WS/48, PER) that `load_bbref` had merged in. Re-running it for 2025-26 would have stripped them from 528 rows. | It replaces only the keys nba.com owns and leaves every other key in place. Running it twice gives the same row. |
| `load_stats` also overwrote `player_seasons.team_id` with nba.com's team, undoing `repair_team_history` (which stores the historical team, or no team for a multi-team season). | A row that already carries Basketball-Reference metrics keeps its stored team. Rows without them, which includes every in-progress season, still take nba.com's team. |
| `load_stats` wrote whatever the source returned. | It refuses an empty, duplicated, undersized (fewer than 300 players by default) or advanced-less response before opening a transaction. |
| `load_current_rosters` only updated players present in the feed. A player who left the league kept a stale `current_team_id`. | Players absent from the feed have their current team cleared and are marked `…:not_on_roster`, but only after the feed passes a completeness gate. `player_seasons.team_id` is untouched, so the historical stat team survives. |
| Several read paths took a player's latest `player_seasons` row with no upper bound. Loading partial 2026-27 stats would have made that row the default valuation input. | Latest-row selection is bounded by `LATEST_SEASON` (2025-26) in player summaries, the free-agent pool, the backtest panel and the valuation publisher. An explicit `?season=` request still works. |

The roster completeness gate rejects the whole refresh, writing nothing, when any of these holds:

- the feed has no rostered players, or lacks a required column;
- a player appears on more than one roster row;
- any of the 30 teams is missing, or the feed names a team that is not one of the 30;
- a team has fewer than 12 or more than 23 players;
- more than 40% of currently assigned players would be cleared (`--max-departed-fraction` changes the limit).

`publish_valuations` now refuses a season after the baseline, and its default covers completed
seasons only. The Data Provenance page states when an in-progress season is on file and that it is
excluded from default valuations.

## Baseline before any refresh

Read-only audit of the production database, 2026-11-14.

| Dataset | Count |
| --- | --- |
| `player_seasons`, all seasons | 7,411 rows, 6,886 with Basketball-Reference BPM |
| `player_seasons` 2025-26 | 582 rows; 528 with BPM, VORP and WS; 582 with nba.com usage rate; 67 with no single team |
| `player_seasons` 2024-25 | 569 rows; 513 with BPM, VORP and WS; 73 with no single team |
| `player_seasons` 2026-27 | none |
| `player_salaries` | 6,818 rows; 2025-26 has 536, all bridged from `contract_years`; 2024-25 has 470 from Basketball-Reference |
| Current roster assignments | 530 players on 30 teams, 16 to 18 per team, all from `nba_api.commonallplayers:2025-26`, last refreshed 2026-06-07 00:31 UTC |
| `players` | 1,777 |
| `cap_constants` | 14 seasons, latest 2025-26, all four thresholds present |
| `contracts` | 580, last scraped 2026-07-10, contract years run to 2030-31 |
| `player_valuations` | 7,411 rows; 2025-26 has 582, computed 2026-07-18 |
| Raw page cache | 3,051 files, 1.49 GB, written 2026-06-06 to 2026-07-22 |

The same numbers, plus every 2025-26 `player_seasons` and `player_salaries` row and every roster
assignment, are saved in `backend/scoutiq/data/snapshots/pre-refresh-20261114T0849Z/`. That
directory is git-ignored and exists only on the machine that ran the audit.

## How the fixes were verified

- Offline tests cover the merge statement, input validation, the roster plan and its completeness
  gate, the coverage tool, and each bounded read path.
- The real upsert ran twice against a temporary table that shadowed `player_seasons` inside one
  rolled-back transaction, seeded with nine production 2025-26 rows. Rows with
  Basketball-Reference metrics kept all seven keys and their stored team, including three
  multi-team rows with no team. Rows without them took nba.com's team. Stale nba.com keys were
  dropped, the second run changed nothing, and `public.player_seasons` was byte-identical
  afterwards.
- The roster planner, fed the 530 stored assignments as if they were the feed, reported 530
  unchanged and no departures. Fed the first 300 of them, it refused the refresh.
- The coverage tool ran read-only against production and produced the table above.

None of this exercised a live nba.com response. The first real run of steps 2 to 4 below is the
first test of the loaders against 2026-27 data.

## Source access on 2026-11-14

| Check | Result |
| --- | --- |
| `GET https://www.nba.com/` | HTTP 403 in 0.3 s |
| `GET https://stats.nba.com/` | HTTP 403 in 0.1 s |
| `nba.fetch_current_players("2026-27")` (roster feed) | read timeout at 25 s once and at 60 s twice |
| `nba._league_dash("2026-27", "Base")` (season stats) | read timeout at 25 s once and at 60 s twice |

The connection and TLS handshake succeed; the server then refuses or stalls. That is an access
control on the source, not a network fault here. ScoutIQ does not work around source access controls
(no proxies, no browser impersonation), so the refresh waits for a network the source accepts or for
a licensed feed.

## Remaining refresh steps

Run from `backend/`, in this order. Steps 1 and 5 are read-only. Stop at the first failure; every
loader below either writes a validated result in one transaction or writes nothing.

1. **Snapshot and before-counts.** Writes the coverage report plus the affected rows to a new,
   git-ignored directory. It refuses to overwrite an existing snapshot. Take a fresh one if the
   database has changed since 2026-11-14; otherwise reuse the snapshot named above.

   ```sh
   .venv/bin/python -m scoutiq.etl.check_refresh_coverage \
     --snapshot-dir scoutiq/data/snapshots/pre-refresh-$(date -u +%Y%m%dT%H%MZ)
   ```

2. **Roster dry run.** Fetches the 2026-27 roster feed and prints the plan without writing to the
   database. Exits 1 if the completeness gate fails.

   ```sh
   .venv/bin/python -m scoutiq.etl.load_current_rosters --season 2026-27 --dry-run \
     --json scoutiq/data/snapshots/roster-plan-2026-27.json
   ```

   Read the `departed` list before continuing: those are the assignments step 3 clears. Roughly
   five months of offseason movement is expected, so a large list is normal. If it exceeds the 40%
   limit, check the list by hand before raising `--max-departed-fraction`.

3. **Roster refresh.** Same command without `--dry-run`. The plan file is written before the
   database is touched, so the record of cleared assignments exists even if the write fails.

   ```sh
   .venv/bin/python -m scoutiq.etl.load_current_rosters --season 2026-27 \
     --json scoutiq/data/snapshots/roster-applied-2026-27.json
   ```

4. **Season-to-date stats.** Loads 2026-27 only. Do not run `load_stats` without `--season`: it is
   now safe, but it would re-request fourteen completed seasons for no gain.

   ```sh
   .venv/bin/python -m scoutiq.etl.load_stats --season 2026-27
   ```

5. **After-counts.** Compare against the step 1 report.

   ```sh
   .venv/bin/python -m scoutiq.etl.check_refresh_coverage \
     --compare scoutiq/data/snapshots/pre-refresh-<stamp>/coverage.json
   ```

   Expected differences, and nothing else:

   - `player_seasons.by_season.2026-27` appears with no Basketball-Reference metrics,
     `player_seasons.rows` grows by the same number, and `seasons_beyond_baseline` lists `2026-27`;
   - every completed season under `player_seasons.by_season` is unchanged, with 2025-26 still at
     582 rows and 528 carrying BPM;
   - `rosters.by_source` shows `nba_api.commonallplayers:2026-27` and
     `nba_api.commonallplayers:2026-27:not_on_roster` in place of the 2025-26 source,
     `rosters.newest_update` is the run time, and `rosters.not_on_roster_marked` equals the
     `departed` count from step 2;
   - `rosters.players` grows by the rookies and new signings;
   - `player_valuations`, `player_salaries`, `contracts`, `cap_constants` and `raw_cache` are
     unchanged.

6. **Confirm the baseline held.** `GET /health` still reports `2025-26`, and a player profile with
   no `season` parameter still values the player on 2025-26.

Do not run these as part of this refresh:

- `scoutiq.model.train` or `scoutiq.model.publish_valuations` for 2026-27. The publisher refuses.
- `scoutiq.etl.load_bbref`. It would request Basketball-Reference pages for players new this
  season, which expands scraping before the permission question is settled, and it only enriches
  seasons up to 2025-26 anyway.
- Anything that deletes or re-fetches `scoutiq/data/raw/`. It holds the only copy of the
  transaction history the contract-decision audit (SCO-20) reads.

## Still open in SCO-49

These acceptance items are not addressed by the loader fixes.

| Item | Why it waits |
| --- | --- |
| 2026-27 contracts and salaries | `load_contracts` replaces a player's stored contract outright, and `player_salaries` keeps one team's row for a multi-team season. Refreshing first would overwrite reliable history. SCO-44 covers the salary rows. |
| 2026-27 cap, tax and apron figures | Not in `cap_constants`. They need the official figures, entered as data, not a projection. SCO-46 covers the reference tables. |
| Basketball-Reference metrics for 2026-27 | Needs the permission decision and a cache policy that keeps the June 2026 pages. |
| `CURRENT_SEASON` setting | Still 2025-26. It drives the free-agent class, the draft year and several loader defaults, so changing it is part of designing live-season behaviour. Pass `--season 2026-27` explicitly until then. |
| Ingestion timestamps for stats | `player_seasons` has no timestamp column, so stats freshness is still reported as unknown. Adding one is a schema change. |
