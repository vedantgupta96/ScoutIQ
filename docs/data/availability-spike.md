# Availability Ledger source spike (issue #95)

**Status:** spike complete — code, offline tests, and a bounded live validation across both edition-naming eras (2022-01-10 → 2026-04-08)
**Scope:** the official NBA injury-report PDF archive as a source for an Availability Ledger event stream

## Source inventory & retrieval method

- **URL pattern:** `https://ak-static.cms.nba.com/referee/injury/Injury-Report_{YYYY-MM-DD}_{EDITION}.pdf`
- **Editions — two naming eras.** Up to **2025-12-21** the token is a whole hour (`05PM`, `08PM`). From **2025-12-22** it carries minutes with an underscore (`12_45PM`, `05_30PM`, `08_30PM`), and many more editions are published per day (on 2026-02-11, all of `11_30AM, 12_45PM, 01_30PM, 02_30PM, 04_30PM, 05_30PM, 06_30PM, 07_30PM, 08_30PM, 09_30PM` returned 200). `default_editions_for(date)` selects the right set. Editions correspond to the day-before/game-day publication schedule described on the [NBA's official injury-report page](https://official.nba.com/nba-injury-report-2025-26-season/).
- **Successful response:** HTTP 200, `Content-Type: application/pdf`, PDF v1.4, roughly 10 pages and 31–95 KB for a typical slate. `Last-Modified` reflects the edition's actual publish time (e.g. `2025-12-20_05PM` → `Sat, 20 Dec 2025 22:45:09 GMT`).
- **Absent-edition response:** HTTP 403 with an XML body `<Error><Code>AccessDenied</Code>...<RequestId>...`. This is S3's standard response for a nonexistent object when bucket listing is denied — it means the edition was never published (or the archive no longer serves it), **not** that the request was blocked. `nba_injury_reports.fetch_edition` classifies this as `status="absent"`, separate from `status="failed"` (timeouts, connection errors, non-403 error statuses). `absent` is a finding to report, not an error to raise.
- **Host reachability:** this CDN host (`ak-static.cms.nba.com`) is reachable from this environment. This is unlike `stats.nba.com`, which is blocked here — the two should not be conflated when reasoning about NBA-source risk.
- **No archive cutoff.** An earlier pass of this spike concluded the archive stopped at 2025-12-21, because every 2026 date returned 403. That conclusion was **wrong**: it probed only the legacy `05PM`-style token. Using the modern `05_30PM`-style token, 2026 dates return 200 normally. The archive is **continuous from at least 2022-01-10 to the current season**; the filename convention changed on 2025-12-22. See §Live validation results. A 403 here means *this edition token was not published*, and must never be generalised into an archive boundary without trying the other convention.

## Retrieval outcome semantics (adapter contract)

`scoutiq/sources/nba_injury_reports.py` returns a structured `EditionOutcome` per (date, edition) with:

- `status`: `ok` | `absent` | `failed`
- `http_status`, `attempts`, `elapsed_s`, `source` (`cache` | `live`)
- **both** `report_effective_utc` (from the response's `Last-Modified` header, falling back to the date/edition encoded in the filename when the header is unavailable — e.g. a stale local cache write) **and** `fetched_at_utc` (this run's ingestion time)

Keeping both timestamps distinct matters: `report_effective_utc` is when the league published the snapshot; `fetched_at_utc` is when ScoutIQ observed it. They will diverge whenever ingestion runs later than publication (backfills, reruns, or a lagging cron), and collapsing them would misrepresent freshness.

## Candidate event schema

Each edition is an **immutable snapshot** — a status printed in one edition must never overwrite an earlier edition's row. The ledger is append-only:

```
availability_events
  id                    surrogate key
  report_date           DATE          -- the date encoded in the filename
  edition               TEXT          -- '05PM', '08PM', ...
  report_effective_utc  TIMESTAMPTZ   -- from Last-Modified, or filename fallback
  fetched_at_utc         TIMESTAMPTZ  -- ingestion time
  source_url            TEXT
  game_date             TEXT          -- verbatim from the PDF row
  game_time             TEXT          -- verbatim from the PDF row
  matchup               TEXT          -- e.g. 'HOU@DEN'
  team_raw              TEXT          -- verbatim team name as printed
  team_id               BIGINT NULL   -- resolved FK, NULL if unmatched
  player_name_raw       TEXT          -- verbatim 'Last, First' as printed
  player_id             BIGINT NULL   -- resolved FK, NULL if unmatched or ambiguous
  identity_match_status TEXT          -- 'matched' | 'unmatched' | 'ambiguous'
  status_raw            TEXT          -- verbatim: Out / Doubtful / Questionable / Probable / Available
  reason_raw            TEXT          -- verbatim reason text
```

A later edition that lists the same player with a changed status inserts a **new row**, not an update — the ledger's value is in the sequence of snapshots, not a single current-state table.

## Key / idempotency proposal

- **Edition key:** `(report_date, edition, source_url)` — re-fetching the same edition (e.g. a cache-warm rerun) must be a no-op against the ledger, not a duplicate insert. A unique constraint on `(report_date, edition)` at the edition level, with a content hash of the parsed row set, lets a reprocessing job detect "this edition was already ingested with identical content" versus "the archive silently republished a corrected edition" (the latter should still be captured as a distinct fact, not silently merged).
- **Row key:** `(report_date, edition, matchup, player_name_raw, status_raw)` as a natural key within one edition — this is what "row" means inside a single snapshot. It is intentionally *not* a global player-availability key, because the whole point of the ledger is that the same player can appear in a later edition with the same or a different status, and both must be retained.
- Identity resolution (`player_id`, `team_id`) is a derived/enrichment step applied after ingestion, not a precondition for storing the raw event — an unmatched or ambiguous name is still stored (with `identity_match_status` recorded honestly), never dropped or silently guessed.

## Refresh cadence & attribution

- Cadence should mirror the league's own publication schedule (day-before and game-day editions, updated through the day) — polling faster than editions are published wastes requests without adding data; polling less often than the edition cadence loses the finer-grained event history the ledger exists to capture.
- Every surface built on this data must show: source (NBA official injury report), the edition's `report_effective_utc`, and `fetched_at_utc`. Per the [NBA.com Terms of Use](https://www.nba.com/termsofuse), any public display must attribute NBA.com and stay within permitted use.

## Required semantics — do not blur these

1. **Listed on an injury report** is not the same as **available status**. A report entry records what a team submitted for that edition at that moment; it can change edition to edition for the same game.
2. **Available status** (Out / Doubtful / Questionable / Probable / Available) is not the same as **games played or missed**. The report is a pre-game participation forecast, not a record of what actually happened on the court.
3. Nothing in this ledger — the PDF text, the parsed rows, or the identity-matched joins — supports a medical inference, a severity score, or an injury-risk prediction. `status_raw` and `reason_raw` are stored and displayed verbatim, exactly as submitted, and are never mapped to a diagnosis, a severity tier, or a risk value anywhere in this codebase.

## Parsing caveats observed against a real edition

- The PDF's extracted text layout is one token per line with no reliable columnar structure; the parser reconstructs rows using known anchors (date/time/matchup regexes and a bundled list of official team full names) rather than positional columns.
- PDF line-wrapping occasionally breaks a hyphenated last name across two extraction lines (e.g. `Finney-Smith` renders as `Finney-` / `Smith`). The current parser attributes the trailing segment (`Smith, Dorian`) to the row and loses the prefix — a known lossy artifact of text-extraction order that shows up in `ParseSummary.unparseable_lines`, not a silent data error.
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
look like an archive cutoff. It is not: the archive is **continuous**, the filename token simply
gained minutes (`05PM` → `05_30PM`). The modern era also publishes far more editions per day; on
2026-02-11 all of `11_30AM, 12_45PM, 01_30PM, 02_30PM, 04_30PM, 05_30PM, 06_30PM, 07_30PM,
08_30PM, 09_30PM` returned 200.

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

| Date | Editions | Effective timestamps (`Last-Modified`) |
|---|---|---|
| 2026-04-08 | 12_45PM, 05_30PM, 08_30PM | 16:45:05Z, 21:30:05Z, 00:30:08Z (+1d) |
| 2026-01-14 | 12_45PM, 05_30PM, 08_30PM | 17:45:04Z, 22:30:04Z, 01:30:07Z (+1d) |
| 2025-12-19 | 05PM, 08PM | 22:45:07Z, 01:45:07Z (+1d) |
| 2024-03-10 | 05PM, 08PM | 21:30:03Z, 00:30:03Z (+1d) |
| 2022-01-10 | 05PM, 08PM | 22:30:02Z, 01:30:03Z (+1d) |

Every edition carried a distinct real `Last-Modified`, captured as `report_effective_utc` separately
from the `fetched_at_utc` ingestion time — the dual-timestamp requirement, satisfied end to end.

**Intraday progression is visible and is exactly the event behaviour the ledger needs.** On
2026-04-08 the same day's editions grew 40 → 137 → 145 rows as statuses were filed through the day.
A snapshot model would have destroyed that; the event model preserves it.

**Parsed rows — 1,427 total, 13 unparseable lines (~0.9 %)**

| Edition | Rows | Unparseable |
|---|---|---|
| 2026-04-08 12_45PM / 05_30PM / 08_30PM | 40 / 137 / 145 | 1 / 2 / 2 |
| 2026-01-14 12_45PM / 05_30PM / 08_30PM | 67 / 117 / 157 | 0 / 0 / 0 |
| 2025-12-19 05PM / 08PM | 111 / 159 | 2 / 3 |
| 2024-03-10 05PM / 08PM | 122 / 150 | 1 / 2 |
| 2022-01-10 05PM / 08PM | 99 / 123 | 0 / 0 |

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
text so `Caldwell-` is lost. This is the caveat recorded under *Parsing caveats*, and it is not a
data problem: fixing hyphen rejoining should recover several of the 24 unmatched rows. The
remainder (e.g. `Garcia, David`) read as two-way/G-League names genuinely absent from `players`.

### Caveats on these numbers

- `report_effective_utc` is the true `Last-Modified` only on a **live** fetch; on a cache hit the
  adapter falls back to the filename's date/edition token. A production loader must persist
  `Last-Modified` alongside the cached bytes.
- Only three editions per date were probed in the modern era, but at least ten exist per day. Daily
  completeness is therefore **not** established.
- Parsing is text reconstruction over a column-less PDF extraction; the ~0.9 % unparseable lines are
  counted and reported, not hidden.

## Recommendation

**Proceed with limitations.** The source is reachable, continuous from at least 2022-01-10 to the
current season, parses at ~99 %, and resolves identity at 98.3 % with zero ambiguity. Nothing here
blocks building an Availability Ledger.

| Question | Verdict |
|---|---|
| Is the source retrievable? | **Yes** — 12/12 live editions returned real PDFs, 0 failures |
| Is the archive continuous to the present? | **Yes** — once both filename conventions are used |
| Does it parse reliably? | **Yes** — ~0.9 % unparseable lines, measured and reported |
| Can rows be tied to ScoutIQ identities? | **Largely** — 98.3 % player / 97.1 % team, 0 ambiguous, by name only |
| Does it support intraday event sourcing? | **Yes** — editions carry distinct effective timestamps and visibly evolve through the day |
| Does it support medical or risk inference? | **No** — and it must never be presented that way |

### Do before building the ledger

1. **Fix hyphenated-surname line rejoining** in the parser. It is a known, evidenced cause of
   unmatched rows (`Pope, Kentavious`), and it is cheap to fix.
2. **Characterise the full daily edition schedule** before claiming per-day completeness; at least
   ten editions per day exist in the modern era and only three were probed.
3. **Persist `Last-Modified`** with cached bytes so replays keep true effective timestamps.
4. **Keep the ambiguous bucket.** Zero ambiguous today is not licence to auto-resolve later;
   unmatched rows must be retained as unmatched rather than dropped.
5. **Treat the filename convention as source-owned and liable to change again.** It already changed
   once mid-season; a loader should fail loudly on an unexpected absence rather than infer a cutoff.

Per the *Required semantics* section, none of this licenses collapsing `listed on an injury report`,
`available status`, and `games played/missed` into one another, and no status or reason text may be
converted into a diagnosis, severity, or risk score.
