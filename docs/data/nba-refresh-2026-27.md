# NBA data refresh for 2026-27 (SCO-49)

**Status, 2026-11-17:** the 2026-27 rosters and season-to-date box totals are in production, last
imported from an ESPN snapshot fetched 2026-11-17 04:50 to 04:53 UTC: 525 rostered players on 30
teams, 467 with a `player_seasons` row, 58 with no ESPN season-total record yet. 2025-26 remains the
completed-season valuation baseline; no valuation, salary, contract or completed-season row changed.
See "ESPN import" below for the procedure and the verified counts.

The official 2026-27 cap row is loaded: $164.961M cap, $200.428M tax, $209.015M first apron and
$221.686M second apron. Nothing here retrains or promotes a model.

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

None of this exercised a live nba.com response. The nba.com loaders have still not run against
2026-27 data; the 2026-27 rows in production came from the ESPN import.

## Source access on 2026-11-14

| Check | Result |
| --- | --- |
| `GET https://www.nba.com/` | HTTP 403 in 0.3 s |
| `GET https://stats.nba.com/` | HTTP 403 in 0.1 s |
| `nba.fetch_current_players("2026-27")` (roster feed) | read timeout at 25 s once and at 60 s twice |
| `nba._league_dash("2026-27", "Base")` (season stats) | read timeout at 25 s once and at 60 s twice |

The connection and TLS handshake succeed; the server then refuses or stalls. That is an access
control on the NBA source, not a network fault here. ScoutIQ does not work around source access
controls (no proxies, no browser impersonation), so the NBA-specific loaders below still wait for
a network that source accepts or for a licensed feed. The cache-only ESPN collection described next
is what the ESPN import below consumes.

### Free ESPN source proof

The public ESPN endpoints were reachable with ScoutIQ's ordinary user agent and a 15-second
timeout: its team feed, each team roster for season 2027, and each rostered athlete's regular
season total. The source-native snapshot records response URLs and original UTC fetch timestamps,
supports a validated resume in the same season-specific output directory, and preserves invalid
raw responses for audit rather than replacing them. ESPN's snapshot is roster-based, so it does
not cover players already waived or otherwise off roster. Its advanced placeholders are not used;
only exact box-score totals are retained, and the ESPN import below is the only step that writes them.

Run the collector from `backend/` with a new empty directory (or resume its own directory):

```sh
.venv/bin/python -m scoutiq.etl.collect_espn_refresh \
  --season 2026-27 \
  --output-dir scoutiq/data/snapshots/espn-2026-27 \
  --identity-evidence /path/to/verified-identity-evidence.json
```

`--identity-evidence` is optional. Its local JSON rows must provide `nba_id`, `name`, `dob`,
`bbref_slug`, and `verified`; only a unique normalized-name plus date-of-birth match is reported.
The collector's report is diagnostic: on 2026-11-14 it matched 408 roster identities and left 118
unresolved. Production identities come from `resolve_espn_identity` (see "Identity" below), which
resolved all 526.

A second run over a copy of the first run's directory confirmed the resume behaviour: all 494
cached responses were reused with their original fetch timestamps, the 959 raw and normalized
files were byte-identical afterwards, and the only network requests were the 63 athletes with no
stat response, which returned HTTP 404 again. A 404 is not cached, so each resume re-checks those
athletes.

## ESPN import

The import path is three commands, run from `backend/`. The first two write only to the snapshot
directory.

```sh
.venv/bin/python -m scoutiq.etl.collect_espn_refresh --season 2026-27 \
  --output-dir scoutiq/data/snapshots/espn-2026-27-<date>
.venv/bin/python -m scoutiq.etl.resolve_espn_identity \
  --snapshot-dir scoutiq/data/snapshots/espn-2026-27-<date> --fetch-evidence
.venv/bin/python -m scoutiq.etl.import_espn_snapshot \
  --snapshot-dir scoutiq/data/snapshots/espn-2026-27-<date> --dry-run \
  --json scoutiq/data/snapshots/espn-2026-27-<date>/import-plan-dry-run.json
```

Read the dry-run report, then run the last command without `--dry-run`. Take a
`check_refresh_coverage --snapshot-dir` snapshot first and `--compare` against it afterwards.

### Identity

`players.player_id` is the NBA id, and ESPN does not publish it. An ESPN athlete resolves only when
exactly one NBA id is proposed and at least two independent sources agree, one of which ties the id
to the athlete's birth date:

| Source | What it establishes |
| --- | --- |
| Basketball-Reference evidence (optional file) | stored NBA id for a normalized name plus verified birth date |
| Stored `players` row | NBA id for a normalized name |
| nba_api static player index (GitHub, refreshed by its maintainers) | NBA id for a normalized name, including rookies |
| Wikidata (`P3647` NBA.com player id, `P569` birth date) | birth date for an NBA id |

A name match alone never resolves. Anything else needs a row in
`scoutiq/data/espn_identity_overrides.csv`, which can only choose an id a source already proposed and
must give a reason. One unresolved athlete blocks the import, because a missing identity would clear
that player's stored team. The mapping is kept in `player_external_ids` with its basis and evidence.

Result for the 2026-11-16 snapshot: 526 of 526 resolved. 406 by all four sources, 1 by three
(Bobby Portis, indexed as "Bobby Portis Jr."), 45 existing players without a verified
Basketball-Reference birth date by stored name, index and Wikidata birth date, 68 new players by
index and Wikidata birth date, and 6 by override: Zach Edey, Quadir Copeland, Maliq Brown and
Michael Ajayi (the sources disagree on the birth date) and Richie Saunders and Rafael Castro (signed
after the index was last refreshed, so Wikidata is the only source). All 408 earlier name plus
birth-date matches were confirmed by Wikidata's birth date under the same NBA id.

### What the importer writes, and when it refuses

One transaction: new `players` rows, current-team assignments stamped `espn.roster:<season>` with the
roster response's fetch time, cleared assignments for players on no roster, the ESPN id mapping, and
`player_seasons` rows with `source = 'espn'` and `source_fetched_at` set to that player's stat
response time. Stored names and `advanced` are never touched; ESPN rows carry box totals only.
A cleared assignment is stamped with the oldest roster response time, because absence from every
roster is only established as of the earliest roster fetch. A 2026-27 row has no `team_id`: ESPN's totals are not split by team, so after a trade they would
credit one team with production from two. The current team lives on `players.current_team_id`.

It refuses, writing nothing, when:

- the season is at or before the 2025-26 baseline;
- the manifest has errors, fewer than 30 validated rosters, or counts that do not match the files;
- any raw stat response fails validation, or a rostered athlete has neither a stat response nor a
  recorded 404;
- any athlete is unresolved, an NBA id is claimed twice, or a stored ESPN mapping disagrees;
- any roster or stat response is more than 36 hours old;
- a stored assignment or stat row is newer than the snapshot's (an older snapshot never overwrites
  newer data; the write statements repeat this check);
- a row for that season already exists from another source;
- the roster completeness gate fails.

### Stat coverage and the 404 responses

A 404 from ESPN's season-total endpoint means no season-total record exists yet. Checked against
ESPN's per-player event log for the 63 such players in the 2026-11-15 snapshot: 59 had no
regular-season appearance, and 4 debuted in games on 2026-11-15 and 2026-11-16. ESPN's totals trail
the latest game day: totals fetched at 08:34 UTC on 2026-11-16 did not include the previous
evening's games, for players with and without earlier appearances. So `source_fetched_at` is the
fetch time, not a guarantee that every completed game is included, and a 404 can hide a debut in the
last game day. These players get no `player_seasons` row; a missing record is not a zero.

### Verified counts, 2026-11-16

| Measure | Before | After |
| --- | --- | --- |
| `players` | 1,777 | 1,850 (73 new) |
| Current roster assignments | 530, from `nba_api.commonallplayers:2025-26` | 526, from `espn.roster:2026-27` |
| Marked not on a roster | 0 | 89 |
| Moved teams / newly assigned / unchanged | | 117 / 85 / 324 |
| `player_seasons` | 7,411 | 7,876 (465 for 2026-27, all `espn`) |
| `player_external_ids` | 0 | 526 |
| Completed seasons, `player_salaries`, `contracts`, `player_valuations`, `cap_constants` | | unchanged |

A second import on 2026-11-17 (snapshot fetched 04:50 to 04:53 UTC, 525 rostered) ran with the
review fixes in place: 465 rows updated and 2 added (467 for 2026-27), `team_id` cleared on all of
them, one more player marked not on a roster (90), 525 assignments. Fed the 2026-11-15 snapshot, the
same importer refused it for stale responses and for older assignments, clears and stat rows.

Until the valuation guard in this change is deployed, an explicit `?season=2026-27` valuation request
still runs the model on partial-season rows. No page requests it; the guard makes it a 404.

## Remaining NBA-loader refresh steps

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
   - `player_valuations`, `player_salaries`, `contracts` and `raw_cache` are unchanged;
   - `cap_constants` is unchanged against a snapshot taken after the 2026-27 cap row was loaded.
     Against the `pre-refresh-20261114T0849Z` snapshot it shows that one added row: 15 seasons,
     latest 2026-27.

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
| 2026-27 maximum salaries | The official cap, tax and apron figures are loaded. The three maximum-salary columns for 2026-27 use the existing 25/30/35% of cap approximation, not the exact CBA formulas. SCO-46 covers the reference tables. |
| nba.com advanced metrics for 2026-27 | ESPN rows carry exact box totals only. USG%, TS%, ratings and the rest stay empty until nba.com accepts requests again; `load_stats --season 2026-27` then replaces the ESPN rows. |
| Showing 2026-27 in the product | The rows are stored and labelled, but no page displays season-to-date stats yet. |
| Basketball-Reference metrics for 2026-27 | Needs the permission decision and a cache policy that keeps the June 2026 pages. |
| `CURRENT_SEASON` setting | Still 2025-26. It drives the free-agent class, the draft year and several loader defaults, so changing it is part of designing live-season behaviour. Pass `--season 2026-27` explicitly until then. |
| Ingestion timestamps for completed seasons | `player_seasons.source` and `source_fetched_at` exist and are set on every row loaded from now on. The 7,411 rows loaded earlier have neither, so their freshness is still reported as unknown. |
