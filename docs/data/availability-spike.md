# Availability Ledger source spike (issue #95)

**Status:** spike complete — code, offline tests, and live validation at five sampled dates across both edition-naming eras: 2022-01-10, 2024-03-10, 2025-12-19, 2026-01-14, 2026-04-08. The source is retrievable at all five; continuity between sampled dates is not established and needs a broader date sweep (see §Source inventory and §Recommendation).
**Scope:** the official NBA injury-report PDF archive as a source for an Availability Ledger event stream

## Source inventory & retrieval method

- **URL pattern:** `https://ak-static.cms.nba.com/referee/injury/Injury-Report_{YYYY-MM-DD}_{EDITION}.pdf`
- **Editions — two naming eras.** Up to **2025-12-21** the token is a whole hour (`05PM`, `08PM`). From **2025-12-22** it carries minutes with an underscore (`12_45PM`, `05_30PM`, `08_30PM`), and many more editions are published per day (on 2026-02-11, all of `11_30AM, 12_45PM, 01_30PM, 02_30PM, 04_30PM, 05_30PM, 06_30PM, 07_30PM, 08_30PM, 09_30PM` returned 200). `default_editions_for(date)` selects the right set. Editions correspond to the day-before/game-day publication schedule described on the [NBA's official injury-report page](https://official.nba.com/nba-injury-report-2025-26-season/).
- **Successful response:** HTTP 200, `Content-Type: application/pdf`, PDF v1.4, roughly 10 pages and 31–95 KB for a typical slate. `Last-Modified` reflects the edition's actual publish time (e.g. `2025-12-20_05PM` → `Sat, 20 Dec 2025 22:45:09 GMT`).
- **Absent-edition response:** HTTP 403 with an XML body `<Error><Code>AccessDenied</Code>...<RequestId>...`. This is S3's standard response for a nonexistent object when bucket listing is denied — it usually means the edition was never published, **not** that the request was blocked. `nba_injury_reports.fetch_edition` classifies this as `status="absent"`, separate from `status="failed"` (timeouts, connection errors, non-403 error statuses). **This classification is explicitly provisional**, not a confirmed archive fact: a 403+`AccessDenied` cannot by itself distinguish "this object was never published" from "access to this object is now restricted" — both produce the identical response. The adapter carries this forward as `absent_is_provisional=True` plus a `classification_note` on every `absent` outcome, and the probe prints a caveat whenever any edition comes back absent. A sudden shift from mostly-`ok` to mostly-`absent` across a run should be read as a possible access change worth investigating, not treated as evidence the archive ended.
- **Host reachability:** this CDN host (`ak-static.cms.nba.com`) is reachable from this environment. This is unlike `stats.nba.com`, which is blocked here — the two should not be conflated when reasoning about NBA-source risk.
- **The filename-convention change is not an archive cutoff — but continuity is not proven.** An earlier pass of this spike concluded the archive stopped at 2025-12-21, because every 2026 date returned 403. That conclusion was **wrong**: it probed only the legacy `05PM`-style token. Using the modern `05_30PM`-style token, 2026 dates return 200 normally; the filename convention changed on 2025-12-22, and that change alone explains the earlier false conclusion. What this does **not** show is that the archive is continuous. The source is **retrievable at all five sampled dates** — 2022-01-10, 2024-03-10, 2025-12-19, 2026-01-14, 2026-04-08 — but five dates prove retrievability at those points, not continuity of everything in between; that needs a broader date sweep. See §Live validation results. A 403 here means *this edition token was not published*, and must never be generalised into an archive boundary without trying the other convention — and retrievability at sampled dates must never be generalised into proven continuity, either.

## Retrieval outcome semantics (adapter contract)

`scoutiq/sources/nba_injury_reports.py` returns a structured `EditionOutcome` per (date, edition) with:

- `status`: `ok` | `absent` | `failed` — plus, for `absent`, `absent_is_provisional=True` and a `classification_note` (see §Source inventory above: a 403 cannot distinguish "never published" from "access now denied").
- `http_status` (populated on every non-2xx outcome, not just 403 — a bare transport failure with no response still has `http_status=None`, but an HTTP 500 or similar carries its real status code through to the final outcome), `attempts`, `elapsed_s`, `source` (`cache` | `live`)
- **four separate timestamps, not two, and not three:**
  - `report_effective_utc` — the **authoritative** effective time: parsed from the PDF's own header line (`Injury Report: M/D/YY HH:MM AM|PM` — the extracted text is one token per line for modern editions, space-separated for older ones; the parser's regex is tolerant of either), interpreted in America/New_York and converted to UTC. `None` if the header line is absent or unparseable — the parser never guesses a time for a row it can't read.
  - `edition_token_utc` — what the edition's **filename token claims** to be: the filename's date + edition token (`05PM`, `05_30PM`, `11_30AM`, ...), interpreted in the league's publication timezone (US/Eastern) and converted to UTC. This is a **fallback/label**, not the authoritative effective time — see the measured divergence below. On any successfully-retrieved (`ok`) edition it is populated whenever the filename token parses — independent of whether the PDF *header* parsed — so it is the fallback when `report_effective_utc` is `None`. It is itself `None` on `failed` and `absent` outcomes, where there is no retrieved edition to label.
  - `source_last_modified_utc` — the response's own `Last-Modified` header, converted to UTC. Only ever populated on a **live** fetch (a cache hit re-reads bytes with no header attached, so this is `None` on cache hits — see the caveat below).
  - `fetched_at_utc` — this run's ingestion time.

`report_effective_utc` is authoritative because it is the report's own claim about itself, not an inference about it. `edition_token_utc` is kept because on a retrieved edition it is available even when the header is missing or unparseable, and it is the identity a reprocessing job keys on — but it must never be presented as the effective time (and it is `None` on failed/absent outcomes, which carry no edition to label). The two diverge by 30–45 minutes in the legacy whole-hour-token era, measured directly against the real cached PDFs used by this spike's tests:

| Edition | Header (`report_effective_utc`) | Token (`edition_token_utc`) | Offset |
|---|---|---|---|
| `2025-12-19_05PM` | 05:45 PM ET | 05:00 PM ET | 45 min |
| `2024-03-10_05PM` | 05:30 PM ET | 05:00 PM ET | 30 min |
| `2022-01-10_05PM` | 05:30 PM ET | 05:00 PM ET | 30 min |
| `2026-04-08_05_30PM` (modern) | 05:30 PM ET | 05:30 PM ET | 0 min — matches |

The whole-hour token cannot express the minute the report actually went out; the minute-precision token can, and (per the modern-era row above) does. Treating `edition_token_utc` as the true publish time would misdate a legacy-era row by up to 45 minutes — exactly why the filename-derived value is never presented as "the effective time" anywhere in this codebase.

`source_last_modified_utc` and `fetched_at_utc` are distinct again from both of the above and from each other: for legacy whole-hour tokens the true `Last-Modified` measured 30–45 minutes after the nominal hour the token encodes (closely tracking `report_effective_utc` — both reflect when the report actually went out, from two independent signals: the server's header and the PDF's own printed header), while for modern minute-precision tokens `edition_token_utc` and `source_last_modified_utc` are within seconds. `fetched_at_utc` is separate again — when ScoutIQ observed the snapshot, which diverges from all three above whenever ingestion runs later than publication (backfills, reruns, a lagging cron).

## Candidate event schema

Each edition fetch is an **immutable snapshot** — a status printed in one edition must never overwrite
an earlier edition's row. The ledger is append-only, and is modeled as **two tables**, not one, because
a single table conflates two different grains: "one fetch of one edition" (which `source_sha256` and
`revision_seq` describe) and "one player-status row inside that fetch" (which every player row in the
same fetch shares the same `source_sha256` for). A unique constraint on the fetch-grain columns,
applied directly to the player-row table, would allow only one player row per edition — see
§Key/idempotency proposal for why that is wrong and how the split resolves it.

```sql
edition_revisions
  id                          surrogate key
  report_date                 DATE          -- the date encoded in the filename
  edition                     TEXT          -- '05PM', '08PM', '05_30PM', ...
  source_sha256               TEXT          -- hash of the RAW PDF bytes = source identity (not the parse)
  parser_version              TEXT          -- which extractor read this revision
  parsed_rows_sha256          TEXT NULL     -- optional hash of the canonical parsed rows; recomputed on reparse
  revision_seq                 INT           -- 1, 2, ... per (report_date, edition), ordered by fetched_at_utc
  superseded_by                BIGINT NULL   -- FK to a later edition_revisions.id for the same (report_date, edition); set once a later revision lands
  report_effective_utc         TIMESTAMPTZ NULL -- the PDF header's own effective time (authoritative); NULL if the header line is absent/unparseable
  edition_token_utc            TIMESTAMPTZ   -- what the filename token claims (ET -> UTC); fallback/label, not authoritative
  source_last_modified_utc     TIMESTAMPTZ NULL -- the response's Last-Modified header, when available
  fetched_at_utc               TIMESTAMPTZ   -- ingestion time
  source_url                   TEXT
  UNIQUE (report_date, edition, source_sha256)
```

```sql
availability_events
  id                          surrogate key
  edition_revision_id          BIGINT        -- FK -> edition_revisions.id
  game_date                    TEXT          -- verbatim from the PDF row
  game_time                    TEXT          -- verbatim from the PDF row
  matchup                      TEXT          -- e.g. 'HOU@DEN'
  team_raw                     TEXT          -- verbatim team name as printed
  team_id                      BIGINT NULL   -- resolved FK, NULL if unmatched
  player_name_raw              TEXT          -- verbatim 'Last, First' as printed
  player_id                    BIGINT NULL   -- resolved FK, NULL if unmatched or ambiguous
  identity_match_status        TEXT          -- 'matched' | 'unmatched' | 'ambiguous'
  suspected_truncated_name     BOOLEAN       -- heuristic flag, see Parsing caveats — NOT a corrected name
  status_raw                   TEXT          -- verbatim: Out / Doubtful / Questionable / Probable / Available
  reason_raw                   TEXT          -- verbatim reason text
  UNIQUE (edition_revision_id, matchup, player_name_raw, status_raw)
```

`report_effective_utc`, `edition_token_utc`, `source_last_modified_utc`, and `fetched_at_utc` live on
`edition_revisions` — they describe the fetch, not any individual player row — and are kept as four
separate columns rather than collapsed into one or two; see §Retrieval outcome semantics for why
conflating them misrepresents freshness and authority.

A later edition that lists the same player with a changed status inserts a **new `availability_events`
row** under a **new `edition_revisions` row**, not an update — the ledger's value is in the sequence of
snapshots, not a single current-state table.

## Key / idempotency proposal

`availability_events` holds one row per player-status line, and every player row from the same fetch
shares the same `(report_date, edition, source_sha256)` — a unique constraint on that tuple, applied
to the player-row table directly, would allow only **one** player row per edition, when a real edition
prints 40–160. That grain mismatch is a defect in an earlier draft of this section, which proposed
exactly that constraint at the edition level *and* separately claimed a silently-corrected
republication of the same edition would be preserved as a distinct fact — those two claims conflict,
because a strict `UNIQUE(report_date, edition)`-style constraint on the row table is exactly what would
block a second, differently-content edition from landing as new rows. The two-table split above
resolves it by putting each grain's uniqueness on its own table:

- **`edition_revisions` is the parent, keyed on the fetch grain:** `UNIQUE (report_date, edition,
  source_sha256)`, where **`source_sha256` is the hash of the raw PDF bytes** — source identity must
  be a property of the source object, not of our parse. Hashing the parsed row set would make a
  *parser* change (a bug fix, a new column) look like a *source* revision of an unchanged PDF, and
  conversely could mask a real republication whose parsed output happened to collapse to the same
  rows. The revision therefore also stores `parser_version` and an **optional** `parsed_rows_sha256`
  as separate columns: the raw hash answers "is this the same published document?", the parser
  version answers "with which extractor did we read it?", and the parsed-row hash (recomputable on
  reprocessing) answers "did our interpretation of it change?" — three independent questions that a
  single hash conflated.
  - A byte-identical refetch (same date, edition, and `source_sha256` — e.g. a cache-warm rerun) is a
    **no-op** against the ledger: the unique constraint rejects the duplicate and nothing new is
    written. Reparsing the same bytes with a newer `parser_version` updates `parsed_rows_sha256` and
    the derived child rows for that revision without creating a new source revision.
  - If the archive republishes `(report_date, edition)` with *different bytes* — a silently
    corrected edition — that lands as a **new `edition_revisions` row** with the same
    `(report_date, edition)` but a different `source_sha256`, carrying `revision_seq` incremented
    from the prior revision for that edition (ordered by `fetched_at_utc`). `superseded_by`
    (nullable, set once a later revision for the same edition is ingested) lets consumers cheaply
    find "the latest revision of this edition" while every earlier revision stays in the table,
    unmodified. Nothing is ever overwritten or deleted; a republication is a new fact, not a
    correction applied in place.
- **`availability_events` is the child, keyed on the row grain within one revision:**
  `UNIQUE (edition_revision_id, matchup, player_name_raw, status_raw)` — this is what "row" means
  inside a single snapshot, scoped to the specific revision it was printed in via
  `edition_revision_id`. It is intentionally *not* a global player-availability key, because the whole
  point of the ledger is that the same player can appear in a later edition (or revision) with the
  same or a different status, and both must be retained.
- Identity resolution (`player_id`, `team_id`) is a derived/enrichment step applied after ingestion,
  not a precondition for storing the raw event — an unmatched or ambiguous name is still stored
  (with `identity_match_status` recorded honestly), never dropped or silently guessed.

## Refresh cadence & attribution

- Cadence should mirror the league's own publication schedule (day-before and game-day editions, updated through the day) — polling faster than editions are published wastes requests without adding data; polling less often than the edition cadence loses the finer-grained event history the ledger exists to capture.
- Every surface built on this data must show: source (NBA official injury report), the edition's `report_effective_utc` (falling back to `edition_token_utc` when the header is absent/unparseable), and `fetched_at_utc`. Per the [NBA.com Terms of Use](https://www.nba.com/termsofuse), any public display must attribute NBA.com and stay within permitted use.

## Edition enumeration strategy: sample vs. production

**This spike's edition list is a sample, not a production enumeration strategy.** `MODERN_EDITIONS`
hard-codes three tokens (`12_45PM`, `05_30PM`, `08_30PM`) because those three are known-good from
the 2026-02-11 probe (§Source inventory), but that same probe returned 200 for **ten** tokens that
day (`11_30AM, 12_45PM, 01_30PM, 02_30PM, 04_30PM, 05_30PM, 06_30PM, 07_30PM, 08_30PM, 09_30PM`). A
production loader that only ever asks for three of the ten editions a day silently under-collects
the intraday history this ledger exists to capture, and would never notice, because it never asked
for the other seven.

Proposed production strategy: enumerate a **candidate grid** of plausible tokens per day (e.g. every
half-hour slot from late morning through the following early morning, matching the pattern observed
on 2026-02-11) and probe every slot in the grid. A token that comes back `absent` is treated as *not
published at that slot* — provisionally, per the caveat above, not as a confirmed fact — never as
evidence about anything else. Even a full-grid probe **cannot prove completeness**: the source
publishes no index of "which editions exist today," so a grid probe only reports what the candidate
slots returned; it cannot rule out an edition published at a token outside the grid. The grid itself
should be re-derived periodically rather than hard-coded indefinitely — the schedule has already
changed once (the 2025-12-22 convention change) and there is no guarantee it will not change again.

## Required semantics — do not blur these

1. **Listed on an injury report** is not the same as **available status**. A report entry records what a team submitted for that edition at that moment; it can change edition to edition for the same game.
2. **Available status** (Out / Doubtful / Questionable / Probable / Available) is not the same as **games played or missed**. The report is a pre-game participation forecast, not a record of what actually happened on the court.
3. Nothing in this ledger — the PDF text, the parsed rows, or the identity-matched joins — supports a medical inference, a severity score, or an injury-risk prediction. `status_raw` and `reason_raw` are stored and displayed verbatim, exactly as submitted, and are never mapped to a diagnosis, a severity tier, or a risk value anywhere in this codebase.

## Parsing caveats observed against a real edition

- The PDF's extracted text layout is one token per line with no reliable columnar structure; the parser reconstructs rows using known anchors (date/time/matchup regexes and a bundled list of official team full names) rather than positional columns.
- PDF line-wrapping occasionally breaks a hyphenated last name across two extraction lines (e.g. `Caldwell-Pope` renders as `Caldwell-` / `Pope,`). The parser has no way to reattach the `Caldwell-` fragment to the following `Pope, Kentavious` anchor, so the row parses as a **valid-looking but truncated** name: `Pope, Kentavious`. **This is silent corruption, not a parse failure** — the row still matches the player-status pattern completely, so `total_status_words - len(rows)` still balances and `ParseSummary.unparseable_lines` does **not** count it. The reported ~0.9% unparseable-line rate (§Live validation results) therefore measures only outright parse failures, not this truncation class, and understates the true error rate by an unknown amount. A heuristic `suspected_truncated_names` counter flags rows whose player-name anchor is immediately preceded by a hyphen glued to a word with no intervening space (e.g. `Caldwell-` immediately before `Pope,`). It is a heuristic, not a guarantee: it only flags the row as suspect, it does not recover the missing prefix, and it will miss any truncation that doesn't leave that exact dangling-hyphen pattern next to the anchor (for instance, if extraction ever drops the fragment entirely rather than leaving it dangling).
- A small number of matchups appear in the text without an immediately preceding game-time token (apparently a PDF page-break artifact); `game_time` in that case carries over from the last-seen value rather than being left blank. This is a candidate for follow-up if the ledger is taken past spike stage.

## Live validation results

Unlike the tracking spike (issue #94), **this source is reachable from this environment** and was
measured for real. Every figure below came from the probe hitting `ak-static.cms.nba.com`; none is
derived from the offline fixtures, which exist only to test parser logic.

### Reachability

`ak-static.cms.nba.com` behaves differently from the hosts blocked in the #94 spike
(`stats.nba.com` times out; `cdn.nba.com` / `official.nba.com` return an Akamai HTML block page).
Here, existing editions return real PDFs (v1.4, ~10 pages, 31–95 KB, `Content-Type: application/pdf`)
and missing editions return an **S3 `<Error><Code>AccessDenied</Code>` XML body** — S3's response for
a nonexistent object when listing is denied. The adapter classifies that as `absent`, not `failed`.

### The edition filename convention changed on 2025-12-22

The single most important finding, and one this spike initially got wrong.

| Date | `..._05PM.pdf` (legacy) | `..._05_30PM.pdf` (modern) |
|---|---|---|
| 2022-01-10 → 2025-12-21 | **200** | 403 / absent |
| 2025-12-22 onward | 403 / absent | **200** |

Probing only the legacy token made every date from 2025-12-22 onward — the entire current season —
look like an archive cutoff. It is not *this* — the filename-convention change on its own is not the
cause: using the modern token, dates from 2025-12-22 onward return 200 normally, because the filename
token simply gained minutes (`05PM` → `05_30PM`). That rules out the convention change as an archive
boundary; it does not by itself establish that every date in between is retrievable — this run only
sampled five dates (see §Source inventory above and §Recommendation below). The modern era also
publishes far more editions per day; on 2026-02-11 all of `11_30AM, 12_45PM, 01_30PM, 02_30PM,
04_30PM, 05_30PM, 06_30PM, 07_30PM, 08_30PM, 09_30PM` returned 200.

`nba_injury_reports.default_editions_for(date)` now picks the right token set per date, and the
probe uses it whenever `--editions` is not given, so neither era can silently look absent again.

### Bounded live run (both eras)

```bash
.venv/bin/python -m scoutiq.etl.check_availability_coverage \
  --date 2026-04-08 --date 2026-01-14 --date 2025-12-19 \
  --date 2024-03-10 --date 2022-01-10 \
  --no-cache --pause 2 --timeout 30 --json
```

Five dates spanning **2022-01-10 → 2026-04-08**, straddling the convention change, all fetched
live with the cache bypassed. Window 2026-07-22T05:21:47Z → 05:22:13Z. Exit code **0**.

**Retrieval — 12 ok / 0 absent / 0 failed**

| Date | Edition | `report_effective_utc` (header) | `edition_token_utc` (token) | `source_last_modified_utc` (measured) | Token offset |
|---|---|---|---|---|---|
| 2026-04-08 | 12_45PM | 16:45:00Z | 16:45:00Z | 16:45:05Z | 0 |
| 2026-04-08 | 05_30PM | 21:30:00Z | 21:30:00Z | 21:30:05Z | 0 |
| 2026-04-08 | 08_30PM | 00:30:00Z (+1d) | 00:30:00Z (+1d) | 00:30:08Z (+1d) | 0 |
| 2026-01-14 | 12_45PM | 17:45:00Z | 17:45:00Z | 17:45:04Z | 0 |
| 2026-01-14 | 05_30PM | 22:30:00Z | 22:30:00Z | 22:30:04Z | 0 |
| 2026-01-14 | 08_30PM | 01:30:00Z (+1d) | 01:30:00Z (+1d) | 01:30:07Z (+1d) | 0 |
| 2025-12-19 | 05PM | 22:45:00Z | 22:00:00Z | 22:45:07Z | **+45 m** |
| 2025-12-19 | 08PM | 01:45:00Z (+1d) | 01:00:00Z (+1d) | 01:45:07Z (+1d) | **+45 m** |
| 2024-03-10 | 05PM | 21:30:00Z | 21:00:00Z | 21:30:03Z | **+30 m** |
| 2024-03-10 | 08PM | 00:30:00Z (+1d) | 00:00:00Z (+1d) | 00:30:03Z (+1d) | **+30 m** |
| 2022-01-10 | 05PM | 22:30:00Z | 22:00:00Z | 22:30:02Z | **+30 m** |
| 2022-01-10 | 08PM | 01:30:00Z (+1d) | 01:00:00Z (+1d) | 01:30:03Z (+1d) | **+30 m** |

This is the measured evidence for the timestamp hierarchy (§Retrieval outcome semantics).
`report_effective_utc` (parsed from each PDF's own header) and `source_last_modified_utc` (the
server's header) agree to within seconds on all 12 editions — two independent signals confirming the
same real publish time. `edition_token_utc` (the filename token) tracks both closely in the modern
minute-precision era (offset 0, seconds of jitter only), but in the legacy whole-hour era it
consistently lands **30–45 minutes before** the true time, because the whole-hour token literally
cannot express the minute the report went out. Treating `edition_token_utc` as the true publish time
for a legacy-era row would misdate it by up to 45 minutes — which is exactly why `report_effective_utc`
is authoritative and `edition_token_utc` is kept only as a fallback/label. `fetched_at_utc` (this run's
ingestion time) is distinct again from all three.

**Intraday progression is visible and is exactly the event behaviour the ledger needs.** On
2026-04-08 the same day's editions grew 40 → 137 → 145 rows as statuses were filed through the day.
A snapshot model would have destroyed that; the event model preserves it.

**Parsed rows — 1,427 total, 13 unparseable lines (~0.9 %), 7 additional suspected-truncated names**

| Edition | Rows | Unparseable | Suspected truncated |
|---|---|---|---|
| 2026-04-08 12_45PM / 05_30PM / 08_30PM | 40 / 137 / 145 | 1 / 2 / 2 | 1 / 1 / 1 |
| 2026-01-14 12_45PM / 05_30PM / 08_30PM | 67 / 117 / 157 | 0 / 0 / 0 | 0 / 1 / 2 |
| 2025-12-19 05PM / 08PM | 111 / 159 | 2 / 3 | 0 / 1 |
| 2024-03-10 05PM / 08PM | 122 / 150 | 1 / 2 | 0 / 0 |
| 2022-01-10 05PM / 08PM | 99 / 123 | 0 / 0 | 0 / 0 |

**The ~0.9 % unparseable-line figure understates the true error rate, and by how much is unknown.**
`unparseable_lines` counts only outright parse failures. It does **not** count the silent-corruption
class described in *Parsing caveats* — a hyphenated surname whose prefix is dropped by PDF
line-wrapping still parses as a complete, valid-looking row with the wrong name. Re-running the
parser's new `suspected_truncated_names` heuristic against these same 12 cached editions finds
**7** such rows, confirmed by inspection to be `Caldwell-Pope` (×3, on 2026-04-08 — the same identity
flagged as the most frequent unmatched player below), `Finney-Smith` (×2), and `Hayes-Davis` (×2).
The heuristic is not exhaustive (see *Parsing caveats*), so 7 is a **measured lower bound**, not a
complete count — the true parse-fidelity rate is therefore **unknown, and lower than ~99 %**.

**Identity matching (over all 1,427 rows)**

| Entity | Matched | Unmatched | Ambiguous | Match rate |
|---|---|---|---|---|
| Player | 1,403 | 24 | **0** | **98.3 %** |
| Team | 1,385 | 42 | 0 | 97.1 % |

> **This is name matching, not ID matching.** The injury report carries no player or team id, so —
> unlike #94's `PLAYER_ID` join — identity can only be resolved on normalized name. The probe
> reports `ambiguous` as its own bucket and never picks a candidate. Zero ambiguous rows across
> 1,427 is encouraging, not a guarantee; a production loader must keep that bucket and keep refusing
> to guess.

**A known parser defect is directly causing unmatched rows.** The most frequent unmatched name is
`Pope, Kentavious` — Kentavious Caldwell-Pope, whose hyphenated surname is line-wrapped in the PDF
text so `Caldwell-` is lost, and all three occurrences are among the 7 rows the truncation heuristic
above flags. This is not a data problem: fixing hyphen rejoining should recover several of the 24
unmatched rows. The remainder (e.g. `Garcia, David`) read as two-way/G-League names genuinely absent
from `players`. Note that the 98.3 % player-match rate is computed over the rows as parsed — a
truncated-but-valid row that happens to still match some *other* player in `players` would be
silently miscounted as `matched` rather than `unmatched`; the identity-match numbers inherit the
same unknown-and-lower caveat as the parse-fidelity rate above.

### Caveats on these numbers

- `source_last_modified_utc` is only ever populated on a **live** fetch — a cache hit re-reads bytes
  with no HTTP headers attached, so it is `None` on every cache hit. `edition_token_utc` is
  available on any retrieved edition regardless of cache vs. live (it's derived from the filename,
  not the response) though `None` on failed/absent outcomes, and `report_effective_utc` is
  available on a cache hit too, as long as the cached PDF's header parses (it's derived from the
  extracted text, not the HTTP response) — which is exactly why these are kept as separate fields
  rather than one falling back to the other (§Retrieval outcome semantics). A production loader must
  persist `Last-Modified` alongside the cached bytes if it wants `source_last_modified_utc` to
  survive a cache replay.
- Only three editions per date were probed in the modern era, but at least ten exist per day
  (§Edition enumeration strategy). Daily completeness is therefore **not** established, and this
  spike's edition list must not be mistaken for a production enumeration.
- Parsing is text reconstruction over a column-less PDF extraction. The ~0.9 % unparseable-line
  figure is counted and reported, not hidden — but it is not the whole error rate: a heuristic
  re-run against these same 12 editions finds 7 additional suspected-truncated names that parse as
  complete, valid-looking rows and are invisible to `unparseable_lines`. **True parse fidelity is
  unknown, and lower than ~99 %.**
- `absent_is_provisional` did not come into play in this run (0 absent editions), but the
  classification exists precisely because a future run could return mostly-`absent` for a reason
  other than "the archive stopped" — see §Source inventory.

## Recommendation

**Proceed with limitations.** The source is reachable and **retrievable at all five sampled dates**
from 2022-01-10 to 2026-04-08, provided the right filename convention is used per era — continuity
*between* those sampled dates is not established and would need a broader date sweep before this
becomes a production loading guarantee. The source resolves identity at 98.3 % with zero ambiguity,
and nothing observed blocks building an Availability Ledger. **Parse fidelity is not one of those
measured strengths**: the ~0.9 % unparseable-line figure is real but only counts outright failures,
and a heuristic re-run finds 7 additional silently-truncated names it misses — true parse fidelity is
unknown, and lower than ~99 %.

| Question | Verdict |
|---|---|
| Is the source retrievable? | **Yes** — 12/12 live editions returned real PDFs, 0 failures |
| Is the archive continuous to the present? | **Not established** — retrievable at all 5 sampled dates (2022-01-10, 2024-03-10, 2025-12-19, 2026-01-14, 2026-04-08) using the right filename convention per era; continuity *between* sampled dates needs a broader date sweep |
| Does it parse reliably? | **Unknown, and lower than it looks** — ~0.9 % unparseable lines is measured, but silent truncation (7 rows found on re-run) is a distinct, uncounted corruption class |
| Can rows be tied to ScoutIQ identities? | **Largely, with the same caveat** — 98.3 % player / 97.1 % team, 0 ambiguous, by name only; a truncated name that coincidentally matches a different real player would be silently miscounted as matched |
| Does it support intraday event sourcing? | **Yes** — editions carry distinct effective timestamps and visibly evolve through the day |
| Does it support medical or risk inference? | **No** — and it must never be presented that way |

### Do before building the ledger

1. **Fix hyphenated-surname line rejoining** in the parser. It is a known, evidenced cause of
   unmatched rows (`Pope, Kentavious`) and of a distinct silent-truncation class the current
   `suspected_truncated_names` heuristic only samples (7 found, not guaranteed complete) — and it
   is cheap to fix.
2. **Characterise the full daily edition schedule before claiming per-day completeness**; at least
   ten editions per day exist in the modern era and only three were probed. §Edition enumeration
   strategy proposes a candidate-grid approach for production, and is explicit that even a full-grid
   probe cannot prove completeness against a source with no published index.
3. **Persist the `Last-Modified` header** with cached bytes so a cache replay still yields a real
   `source_last_modified_utc` instead of `None`, and keep it distinct from `report_effective_utc` and
   `edition_token_utc` (§Retrieval outcome semantics) — the measured 30–45 minute offset between
   `edition_token_utc` and the true time in the legacy era shows why.
4. **Keep the ambiguous bucket.** Zero ambiguous today is not licence to auto-resolve later;
   unmatched rows must be retained as unmatched rather than dropped.
5. **Treat the filename convention as source-owned and liable to change again.** It already changed
   once mid-season; a loader should fail loudly on an unexpected absence rather than infer a cutoff.
6. **Treat `absent` as provisional, always.** A 403 `AccessDenied` cannot distinguish "never
   published" from "access now denied" (§Source inventory); a sudden jump from mostly-`ok` to
   mostly-`absent` should trigger investigation, not be read as an archive fact.
7. **Adopt the two-table, revision-aware model** — `edition_revisions` keyed on
   `(report_date, edition, source_sha256)` (raw-PDF hash) with `revision_seq`, and `availability_events` keyed on
   `(edition_revision_id, matchup, player_name_raw, status_raw)` — from §Key/idempotency proposal, not
   a single table with a bare `(report_date, edition)` unique constraint, so a silently republished
   edition lands as a new revision instead of being rejected as a duplicate, and every player row
   within one edition is retained rather than colliding.

Per the *Required semantics* section, none of this licenses collapsing `listed on an injury report`,
`available status`, and `games played/missed` into one another, and no status or reason text may be
converted into a diagnosis, severity, or risk score.
