# Sports Reference salary-schedule export

An offline importer for the user-supplied Sports Reference (Basketball-Reference) player contracts table export. This card builds a validated parser, an immutable snapshot, and a read-only dry-run plan. There is no apply path: writing any of this into the database is SCO-52's job.

## What the export is

A file with an `.xls` extension that is really an HTML document (an Excel-HTML wrapper around one `<table>`). It is treated as untrusted data: it is parsed, never executed, and the real file is never committed. Test fixtures are small synthetic HTML files in the same shape (`backend/tests/fixtures/sportsref/`).

Each body row is one salary-schedule obligation: rank, player (with the Basketball-Reference id in `data-append-csv`), team abbreviation, one cell per season (`y1`..`yN`), and the `remain_gtd` ("Guaranteed") cell. Season labels are read from the header, never hardcoded.

## Provenance and its limits

- Claimed source: the Basketball-Reference player contracts table (`https://www.basketball-reference.com/contracts/players.html`). The export itself carries no source URL; this is a claim, recorded as such.
- Legend evidence: the Color Key on the cached copy of that page (`backend/scoutiq/data/raw/bbref_contracts_players.html`, cached 2026-07-09) defines `salary-pl` as Player Option and `salary-tm` as Team Option, and `remain_gtd` as "The amount of a player's remaining salary that is guaranteed." No other `salary-*` classes appear there. The export has no legend of its own.
- Export time is unknown. The export carries no timestamp and file-system times are not source times, so the manifest records `export_time: null` with a note.
- `received_at_utc` in the manifest is when ScoutIQ snapshotted the file, not when the source produced it.

## Parsing rules

- Amounts come from the cell's `csk` attribute and are cross-checked against the digits of the displayed text; a disagreement is recorded as a problem (the `csk` value is kept).
- A blank cell (class `iz`, no `csk`, empty text) is `None` and `blank`, never 0. An explicit `$0` is 0.
- `salary-pl` maps to `player_option` and `salary-tm` to `team_option`. Any other `salary-*` class is a problem and yields no option.
- Rows without `data-append-csv` are skipped, counted, and reported as problems. Repeated `<tr class="thead">` rows are skipped.
- A malformed header (missing player/team/remain_gtd columns, no `yK` columns, an invalid or non-consecutive season label) raises `ExportFormatError`.
- Multi-obligation rows are never collapsed or summed. A player such as Damian Lillard can have a MIL dead-money row and a separate POR row; they are distinct obligations kept in document order (`row_ordinal`).
- No schedule totals are computed and nothing is inferred about guarantees. `remaining_guaranteed` is reported only as the export states it.
- A salary schedule is not a signed-contract event. It has no signing date, signing mechanism, or full contract terms.

## Identity rule

Rows match players only through `player_xref` rows with `status = 'verified'` and a non-null `bbref_slug`. A slug with more than one verified player is ambiguous; a slug present only with `mismatch` or `not_found` is reported as not verified; a slug with no xref row is unmatched. There is no fuzzy or name matching; names are display text only.

### Team abbreviations

Basketball-Reference spells some teams differently from the `teams` table (BRK, CHO, PHO against BKN, CHA, PHX). Export teams are resolved through the existing `TEAM_ABBREV_ALIASES` map in `scoutiq/sources/nba.py` before lookup and comparison. The report keeps both `obligation_team_source` (raw) and `obligation_team` (resolved), and `unknown_team_abbreviations` lists only abbreviations that do not resolve after aliasing. A matched player with no current team is reported separately under `no_current_team`, not as a team difference.

### Unmatched identities

For each unmatched id the plan adds evidence only: players whose normalized full name (the crosswalk's `normalize_name`) equals the export name, each with player_id, current team, and its xref status and slug. These are `exact_name_candidates` ("candidate only - not assigned"); ids with no exact-name player are `no_player_record` (for example new rookies). If an exact-name candidate already has a verified crosswalk row under a different BBRef id, the id is categorized `verified_slug_conflict` and listed under `identity.verified_slug_conflicts` (export id, export name, player_id, stored verified slug). One side may be wrong and it must be resolved before any apply; it is never assigned. Each evidence entry also carries the export row's player name and team. The evidence is never used to match or compare; `matched` counts stay verified-slug only.

### Uncertain cells

A non-empty cell with no `csk` and no digits (for example "TBD") is not treated as blank: amount is None, `blank` is false, a problem is recorded, and the cell is marked `uncertain` with the reason. A cell carrying both `salary-pl` and `salary-tm` gets no option, a "conflicting option markers" problem, and is also uncertain. Uncertain cells are counted in `coverage.uncertain_cells`, and every comparison reports them as `uncertain_in_export`, never as same, missing, or blank.

### Comparison outcomes

Each comparison covers matched single-obligation players only; multi-obligation players are listed under `not_compared_multi_obligation` (id and row count) with a count. Every outcome is explicit, with counts in `summary` and per-item `details`:

- Contract years: `same`, `amount_differs`, `option_differs`, `missing_in_stored`, `missing_in_export`, `uncertain_in_export`.
- `player_salaries` (per export season): `same`, `amount_differs`, `missing_in_stored`, `extra_in_stored` (a stored row where the export is blank), `uncertain_in_export`.
- `player_team_salaries`: keyed by player, season and resolved team. Both the export team and the stored `team_abbr` pass through `TEAM_ABBREV_ALIASES` before keying, so CHO matches CHA. Each export obligation matches at most one stored row (`same`, or `amount_differs` when only the amount differs); `missing_in_stored` when none exists; every unconsumed stored row is `extra_in_stored`, never dropped.

## Rerun steps

From `backend/`:

```
python -m scoutiq.etl.plan_sportsref_salaries snapshot --input ~/Downloads/sportsref_download.xls
python -m scoutiq.etl.plan_sportsref_salaries plan --snapshot backend/scoutiq/data/snapshots/sportsref-salaries-<hash> --json plan.json
```

`snapshot` copies the file byte-identically (read-only, 0444) into `scoutiq/data/snapshots/sportsref-salaries-<first 12 hex of sha256>/` (gitignored) with a `manifest.json`. An existing snapshot is reused only if its hash matches; it is never overwritten. `plan` refuses (exit 2) if `input.html` no longer matches the manifest hash, then parses, reads the database inside a `SET TRANSACTION READ ONLY` transaction, and prints a summary (optionally JSON).

The plan reports provenance, coverage, identity buckets, multi-obligation players, team checks (unknown abbreviations and "obligation team differs from current roster team", with no roster-status inference), a per-season comparison against each matched single-row player's latest stored contract, and comparisons against `player_salaries` and `player_team_salaries`. Applying any of it is SCO-52's job.

## Applying a snapshot

`scoutiq.etl.apply_sportsref_salaries` turns a validated snapshot into database rows. It is a dry run unless
`--apply` is passed. Every write happens in one transaction and nothing stored is ever updated or deleted by
`apply`.

```
# dry run: reads the DB in a read-only transaction, prints the plan, writes nothing
python -m scoutiq.etl.apply_sportsref_salaries apply --snapshot DIR [--json plan.json]

# apply: --confirm must equal the first 12 hex chars of the snapshot sha256 (the directory name suffix)
python -m scoutiq.etl.apply_sportsref_salaries apply --snapshot DIR --apply --confirm SHA12

# remove exactly what this snapshot wrote
python -m scoutiq.etl.apply_sportsref_salaries rollback --snapshot DIR [--apply --confirm SHA12]
```

Exit codes: 0 ok; 2 snapshot hash mismatch; 3 export format error; 4 missing or wrong `--confirm`; 5 apply
refused because a `player_team_salaries` conflict exists; 6 the post-write row-count check failed (rolled back).

### What is written

- `player_team_salaries` (raw per-team evidence): one row per matched export row and season cell that has an
  amount and is not uncertain. `team_name` is `teams.name` of the resolved team (`TEAM_ABBREV_ALIASES` first),
  `source = sportsref_export`, `source_ref` = snapshot directory name, `source_fetched_on` = date of the
  manifest `received_at_utc`. Multi-obligation players and team-differs rows are included, because each team row
  is distinct evidence. Key: (player_id, season, source, team_name, row_ordinal). Same key and salary is
  `unchanged`; same key and a different salary is a `conflict` and the whole apply refuses.
- `contracts` + `contract_years` (what the app reads as the player's contract): one new contract per eligible
  player, `source = sportsref_export`, `scraped_at` = manifest `received_at_utc`, `season_start` = first
  scheduled season, `total_value` = sum of amounts, `cap_pct` = amount / `cap_constants.salary_cap` rounded to 4
  places (null when the season has no cap row), option flags from the cell markers (`is_guaranteed` only when
  there is no option).
- `player_salaries` is never written: season totals are not derivable from per-team obligation rows, and
  valuation pay remains the completed-season figure.

### Contract eligibility and held reasons

A player is eligible when identity is matched, there is exactly one export row, no cell in it is uncertain, its
team resolves, and the team equals the player's current team (or the player has no current team). Then, against
the latest stored contract (season_start desc, scraped_at desc): no stored contract, or one with no year in the
export schedule, is an `insert`; one that matches the schedule amounts and options for every season from the
first export season on is `unchanged`; anything else is held.

| Reason | Meaning |
| --- | --- |
| `not_matched` | no crosswalk row for the BBRef id |
| `not_verified` | crosswalk row exists but is not `verified` |
| `ambiguous_identity` | several verified players share the id |
| `multi_obligation` | more than one export row for the player; team rows are still written |
| `unknown_team` | export team does not resolve to a `teams` row |
| `uncertain_cells` | a season cell was unparseable or had conflicting markers |
| `no_amounts` | the row has no non-blank amounts |
| `team_differs_from_current` | export team differs from the player's current team |
| `season_start_collision` | a stored contract already starts in the new first season |
| `stored_contract_differs` | the stored contract overlaps the schedule but differs; the report carries a per-season diff |

Uncertain cells are listed under `held_uncertain_cells` and are not written to `player_team_salaries`.

### Idempotency, journal and rollback

Re-running `--apply` on the same snapshot inserts nothing: written team rows are `unchanged`, written contracts
are `unchanged`. Under Postgres the apply takes `LOCK TABLE contracts, contract_years, player_team_salaries IN
SHARE ROW EXCLUSIVE MODE`, re-reads state inside the transaction, refuses on conflicts, and asserts that each
table grew by exactly the planned inserts before committing. After commit it writes
`apply-<UTC timestamp>.json` into the snapshot directory: sha256, confirm, plan counts, a before-record per
affected player (latest stored contract with years, existing `sportsref_export` team rows), inserted contract
and team-salary ids, and table counts before and after.

`rollback` selects `contracts` with `source = sportsref_export` and `scraped_at` equal to the manifest
`received_at_utc` (plus their `contract_years`) and `player_team_salaries` with `source = sportsref_export` and
`source_ref` equal to the snapshot directory name. It deletes them in one transaction (years, contracts, team
salaries) after verifying counts. Rows from other sources or other snapshots are untouched. Applying again after
a rollback re-inserts the same rows.

Production apply needs explicit owner approval after PR review. Always run the dry run first and review the
report, including the `spot_checks` entry for `jamesle01`.
