# Contract-decision data coverage audit (SCO-20)

**Status:** spike complete. Measured on 2026-11-13 against the live database (read-only) and the local page caches. Revised after five rounds of code review: multi-team salary seasons are excluded, and none turns out to be recoverable by summing salary rows; a signing that shares its league year with a two-way, 10-day, Exhibit or substitution deal is excluded because the season salary combines the deals, whether the other deal is a separate transaction or described in the same entry; per-team recovery counts a salary row once; the unconstrained population is described as "no constraint identified", not market-set; extensions sit in their own rule-constrained tier.
**Recommendation: proceed with limits.** Standard free-agent signings from 2013-14 to 2025-26 can be turned into a temporally honest decision dataset today. Exact AAV, guarantees, constraint status and extensions cannot be covered historically without a new source.

Part of the Valuation v2 roadmap (SCO-17). Feeds SCO-24 and SCO-36. ADR-0003 (proposed in PR #146, not yet on `main`) defines the two valuation concepts this audit serves. Migrated from GitHub #109.

## Summary

| Question from the ticket | Answer |
| --- | --- |
| Can we identify real signing decisions, not mid-contract salary observations? | Yes for standard signings: 3,370 dated events in the window. Extensions are only reliable from 2020-21. |
| Can we recover signing date, team, prior team and transaction type? | Yes: 100%, 99.9%, 92.9% and 100% of standard signings. |
| Can we recover years, total value, AAV and guarantees? | Only for 25% of standard signings, concentrated in recent seasons and in players still active in 2026. |
| Can we separate market-set from constrained outcomes? | Only partly. Rookie-scale, two-way and short-form deals are identified reliably. Restricted free agency and cap exceptions are unknown for about three quarters of signings. |
| Can outcomes be expressed in percent of cap without leakage? | Yes for standard signings (the first-season cap is set before signing). Not for extensions: the cap for the start season is unknown at signing and no cap-projection history is stored. |
| How many usable rows remain? | 1,340 usable standard signings. 743 of them have no constraint identified (about 57 per season). 120 usable extensions, almost all from 2020-21 on. |

The stored `contracts` table cannot support this work on its own. It holds one current deal per player, so every standard signing through 2019-20 is missing from it.

**What "no constraint identified" means.** A usable signing lands in this group when it is not a rookie-scale deal, not at or below 2.5% of cap, and not at a stored maximum. That is the absence of a detected constraint, not evidence of an open market. Where Spotrac data lets us check (260 of the 743), 94 were signed with a capped exception. Read 743 as an upper bound on market-set decisions.

## How to reproduce

```bash
cd backend
.venv/bin/python -m scoutiq.etl.check_contract_decision_coverage            # full report (needs DB)
.venv/bin/python -m scoutiq.etl.check_contract_decision_coverage --json     # machine-readable
.venv/bin/python -m scoutiq.etl.check_contract_decision_coverage --cache-only   # no DB
.venv/bin/pytest tests/test_contract_decision_coverage.py -q               # offline, synthetic fixtures
```

The probe reads local cache files and runs SELECTs inside a `READ ONLY` transaction. It makes no network requests and no writes. Two consecutive live runs produced identical JSON.

Parsers live in [`scoutiq/sources/contract_events.py`](../../backend/scoutiq/sources/contract_events.py); the probe is [`scoutiq/etl/check_contract_decision_coverage.py`](../../backend/scoutiq/etl/check_contract_decision_coverage.py). The probe is one 1,300-line module covering cache reading, SQL, event building, linking, classification and rendering. That is acceptable for a spike; it must be split before any of it becomes durable ETL.

## Current table and field inventory

| Table | Rows | What it holds | Gap for decision data |
| --- | --- | --- | --- |
| `contracts` | 580 | One row per player: the current deal. 541 from Spotrac, 39 from the Basketball-Reference fallback. Starts span 2020-21 to 2026-27. | No signing date, contract type, signing team (`team_id` is null on all 580) or guarantee amount. The loader deletes a player's earlier contracts on every scrape, so history is never kept. |
| `contract_years` | 1,730 | Per-season cap hit, cap % and option flags for the stored deals. | Only covers the 580 current deals. `is_guaranteed` is set by the loader as "not an option year"; it is not a guarantee measure. |
| `player_salaries` | 6,818 | Realized salary per player-season, 2012-13 to 2024-25 from Basketball-Reference; 2025-26 bridged from `contract_years`. | One value per player-season. Says nothing about when or how the pay was set. Wrong for multi-team seasons (below). |
| `cap_constants` | 14 | Cap, tax line, aprons and the three maximums, 2012-13 to 2025-26. | No minimum-salary scale, no exception amounts, no 2026-27 row, no history of cap projections. |
| `free_agent_rights` | 205 | UFA/RFA status and Bird rights for the 2026-27 offseason only. | No history. |
| `player_seasons` | 7,411 | Production, age, games and minutes per season. | Complete enough for as-of features. |
| `player_xref` | 1,776 | Player id to Basketball-Reference slug: 1,645 verified, 111 not found, 20 mismatched. | 171 cached pages have no verified link; they carry 323 signing events that the audit drops. |

**Multi-team salary defect (pre-existing, not introduced here).** For the 459 player-seasons where a player was paid by two or more teams, `player_salaries` stores one team's row, never the season total. In all 428 cases with a stored value it equals the largest single row. The loader keeps the first row per season on the assumption that it is a combined row; salary tables have no combined row. This affects the current v1 training target as well as any decision label. The audit treats these seasons as unusable (see "Why rows drop out").

## Where decision events come from

Neither source is in the database. Both are local page caches that the existing loaders already wrote.

| Source | Cache | What it adds | Limits |
| --- | --- | --- | --- |
| Basketball-Reference transaction log | 1,812 player pages, fetched 2026-06-06 to 2026-06-07 | Dated transactions with team: 6,546 signing transactions across eight kinds. Also draft round and pick, and per-team salary rows. | No money terms. 11 pages have no log. 3 signings have unparseable dates. Extension entries are missing for 2016-17 to 2019-20 (see below). |
| Spotrac contract blocks | 541 player pages, fetched 2026-06-06 to 2026-07-09 | 1,875 contracts with a start season and type label; 1,598 with years, total value and AAV; 1,380 with guarantee at signing; 1,536 with the exception used; 1,575 with the free-agent year and status that follows the deal. | Only players on a roster in mid-2026. 413 of 541 pages hit the paywall, which hides older deals. 98 contracts carry no type label. |

Signing transactions by kind, all pages: standard 3,785; 10-day 919; two-way 821; Exhibit 486; rest-of-season 203; extension 174; two-way conversion 144; substitution 14.

## The four dates

| Date | Available? | Source and rule |
| --- | --- | --- |
| Signed date | Yes | The Basketball-Reference transaction date. |
| Announced date | No | Neither source records when a deal was reported. Free-agent agreements are typically reported days before signing, so the signed date is the later, safer as-of anchor. |
| Contract start | Standard signings: yes. Extensions: only via Spotrac. | A standard signing starts in the league year it is signed. An extension starts after the existing deal ends: 1 season later in 129 resolved cases, 2 in 18, 3 in 2. |
| First cap-hit season | Same as contract start | No case in either source separates the two. |

Two calendar rules matter and are encoded in the probe:

- **League year.** It rolls over on July 1, except 2020 (October 12) and 2021 (July 21), the day after each delayed Finals. Without this, July 2020 bubble signings land in the wrong season.
- **Offseason versus in-season.** A signing is in-season if dated on or after that season's opening night. In-season pay is prorated, so the first-year salary understates the deal.

## Season-by-season coverage

Raw to joined, for the whole cache:

| Stage | Count |
| --- | --- |
| Signing transactions on all 1,812 pages | 6,546 |
| On pages with a verified player link, with a parseable date | 6,223 |
| After collapsing duplicates | 6,219 |
| In the window (first paid season 2013-14 to 2025-26) | 5,668 |
| of which standard-form signings | 3,370 |
| of which two-way | 816 |
| of which 10-day, Exhibit or substitution | 1,308 |
| of which extensions (by signing season) | 174 |

Standard-form signings (standard, rest-of-season, two-way conversion) by first paid season. Each join column is counted independently over `Events`. `Usable` requires all of: one standard signing in that player-season, no deal of another form (two-way, 10-day, Exhibit, substitution) by the player in that league year, whether logged as its own transaction or inside the same entry, a stored first-year salary from a single-team season, a cap, and prior-season BPM.

| Season | Events | One signing that season | No other-form signing that season | Has salary | Salary from a single-team season | Has prior BPM | Usable | No constraint identified | of which offseason | Usable with exact terms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2013-14 | 184 | 163 | 158 | 128 | 122 | 119 | 81 | 49 | 46 | 1 |
| 2014-15 | 292 | 226 | 235 | 255 | 225 | 171 | 106 | 63 | 63 | 5 |
| 2015-16 | 286 | 250 | 247 | 256 | 209 | 182 | 120 | 75 | 75 | 12 |
| 2016-17 | 340 | 269 | 287 | 308 | 247 | 201 | 136 | 91 | 88 | 16 |
| 2017-18 | 292 | 247 | 228 | 258 | 218 | 166 | 107 | 65 | 64 | 12 |
| 2018-19 | 266 | 229 | 208 | 226 | 182 | 167 | 99 | 51 | 50 | 20 |
| 2019-20 | 281 | 253 | 238 | 259 | 225 | 187 | 128 | 79 | 78 | 29 |
| 2020-21 | 206 | 186 | 165 | 201 | 168 | 148 | 94 | 49 | 49 | 26 |
| 2021-22 | 335 | 292 | 205 | 303 | 244 | 211 | 116 | 62 | 61 | 35 |
| 2022-23 | 303 | 249 | 234 | 207 | 150 | 206 | 81 | 32 | 32 | 42 |
| 2023-24 | 199 | 182 | 156 | 197 | 160 | 140 | 91 | 43 | 43 | 58 |
| 2024-25 | 193 | 177 | 142 | 190 | 159 | 133 | 91 | 43 | 43 | 70 |
| 2025-26 | 193 | 177 | 145 | 181 | 181 | 144 | 90 | 41 | 41 | 83 |
| **Total** | **3,370** | **2,900** | **2,648** | **2,969** | **2,490** | **2,175** | **1,340** | **743** | **733** | **409** |

Join rates over the 3,370 events: 79% share their league year with no signing of another form, 88% have a first-year salary, 74% have one from a single-team season, 100% a cap, 65% a prior-season row with BPM, 40% are usable, 22% are usable with no constraint identified.

Usable standard signings by cohort (no constraint identified in brackets):

- **Age at the prior season:** 22 or younger 69 (29); 23-25 322 (167); 26-28 375 (240); 29-31 279 (173); 32 or older 295 (134).
- **Position:** C 338 (186); PF 267 (158); PG 256 (144); SF 194 (94); SG 285 (161).
- **Kind:** standard 1,327 (743); two-way conversion 4 (0); rest-of-season 9 (0).
- **Timing:** offseason 1,283 (733); in-season 57 (10).

Among the 743 rows with no constraint identified, first-year pay has a median of 7.6% of cap (10th percentile 3.3%, 90th 20.4%), and 52% re-signed with the team they were already on.

### Why rows drop out

| Missing or excluded | Events | Reason |
| --- | --- | --- |
| First-year salary | 401 | 321 were waived on or before opening night (training-camp deals); 16 have no salary table at all; 64 unexplained. |
| Prior-season production | 1,194 | 995 had no earlier NBA season (rookies and first-time signees); 199 had a gap before signing. |
| A single signing that season | 470 | Two or more standard signings by one player in one league year (228 player-seasons). |
| No deal of another form that season | 722 | The player also had a two-way, 10-day, Exhibit or substitution deal in that league year, so the one stored season salary combines the deals even when a single team paid it. 589 have the other deal as a separate transaction only. 133 combine forms within one entry: 131 in-season two-way conversions and 2 entries of the form "signed two 10-day contracts, then signed a contract for the rest of the season"; 12 of the 133 have no separate transaction for the other deal. 290 of the 722 are also multi-signing seasons and 256 are multi-team seasons; 386 are in-season signings. |
| Salary from a single-team season | 479 | The first paid season has two or more per-team salary rows, so the stored value is one team's row. 241 of these are also multi-signing seasons; 278 are in-season signings. |

Of the 722 events, 138 pass every other condition, and the first two versions of this audit counted them as usable: 133 near-minimum, 4 with no constraint identified and 1 rookie scale; 62 are two-way conversions, where the season salary mixes two-way and standard pay. A conversion made in the offseason stays usable, because no two-way pay falls in the new season.

Of the 479 multi-team events, 211 pass every condition except the single-team salary; this count predates the other-form rule and still includes 70 events with another signing that season, shown in the first row below. Storing a season total would not make them usable, because the total usually mixes more than one contract. By what else happened to the player in that league year:

| Cause of the extra salary rows | Otherwise-usable events | Is the row sum a valid label? |
| --- | --- | --- |
| Another signing of any form that season (two-way, 10-day, Exhibit, extension), as its own transaction or within the same entry | 70 | No: the total combines separate deals. |
| A waiver, release or waiver claim that season | 120 | No: the total can include pay from a terminated deal. |
| Trades only | 2 | Only if every salary row belongs to the signing team or a team the player was traded to afterwards. Neither event passes: each has a row from an earlier team. |
| Unexplained (no signing, waiver or trade logged that season) | 19 | Unknown. Possibly pay still owed by an earlier team. |

No event is recoverable by summing rows. The 2 trade-only events were reported as recoverable in earlier versions of this audit, but in both the season's salary rows include a team that neither signed the player nor received him in the trade (signed with Houston and traded to Denver, rows from Sacramento and Houston; signed with the Clippers and traded to Houston, rows from Detroit and Houston). That row is pay still owed from an earlier contract, so the sum mixes two deals. For all 211, the candidate fix is to attribute the signing team's own salary row to the decision, which needs per-team rows stored and is not measured here.

Training-camp deals are not separately labelled before 2017-18, when Exhibit contracts start appearing in the log. The probe flags 630 standard signings as suspected camp deals; 40 of them are usable.

## Missingness by required field

Counts are fields **present**.

| Field | Standard signings (n = 3,370) | Extensions (n = 174) |
| --- | --- | --- |
| Signing date | 3,370 | 174 |
| Transaction type | 3,370 | 174 |
| Signing team | 3,368 | 174 |
| Prior team | 3,132 | 174 |
| First paid season | 3,370 | 149 |
| First-year salary | 2,969 | 122 |
| Cap denominator | 3,370 | 122 |
| Years, total value, AAV | 844 | 149 |
| AAV as % of cap | 844 | 122 |
| Guarantee at signing | 825 | 149 |
| Exception used | 843 | 145 |
| Free-agent status entering the signing | 441 known, 147 of them restricted | 0 |
| Age and prior production | 2,176 | 171 |
| Position | 3,368 | 174 |

Options and guarantees, measured separately because they come from different places:

| Measure | Standard signings | Extensions | Source |
| --- | --- | --- | --- |
| Option years stored | 289 | 79 | The signing matches a stored Spotrac contract that has year rows. Current deals only. |
| of which with a player option | 42 | 25 | `contract_years.is_player_option` |
| of which with a team option | 135 | 5 | `contract_years.is_team_option` |
| of which with any non-guaranteed year | 175 | 30 | Option years only; see the `is_guaranteed` note above. |
| Guarantee split known | 825 | 149 | Linked Spotrac contract with guarantee at signing and total value. |
| of which fully guaranteed at signing | 346 | 126 | Guarantee equals total value. |
| of which partially guaranteed at signing | 479 | 23 | Guarantee below total value. |

Per-year partial guarantees are not available anywhere: the database does not store them, and the audit measures them only at contract level.

## Constrained-market breakdown

Each in-window event gets exactly one structure.

| Tier | Structure | Events | Usable standard signings | How it is identified |
| --- | --- | --- | --- | --- |
| Mechanical | Two-way | 816 | - | Transaction text. |
| Mechanical | 10-day | 817 | - | Transaction text. |
| Mechanical | Exhibit | 477 | - | Transaction text (2017-18 onward). |
| Mechanical | Substitution | 14 | - | Transaction text. |
| Mechanical | Rookie scale | 356 | 10 | First-round pick's first standard signing within three years of the draft. |
| Censored | Near minimum | 1,673 | 562 | First-year pay at or below 2.5% of cap. A proxy: no minimum scale is stored. |
| Censored | Maximum | 31 | 25 | First-year pay within 1.5% of a stored maximum, or above the 35% maximum. |
| No constraint identified | Standard signing | 913 | 743 | No rule above fired. |
| Extension rules | Rookie extension | 67 | - | First-round pick, extension signed three league years after the draft. Negotiated, but bounded by extension eligibility, length, raise and maximum rules. |
| Extension rules | Veteran extension | 107 | - | Any other extension. Bounded by the same kinds of rule. |
| Unclassified | No salary | 397 | - | Standard signing with no first-year salary. |

How well the rules agree with Spotrac, on standard signings where both exist:

| Rule | Precision | Recall | Reading |
| --- | --- | --- | --- |
| Rookie scale | 226 / 227 | 226 / 226 | Reliable. |
| Near minimum (2.5% of cap) | 193 / 320 (60%) | 193 / 201 (96%) | Catches almost every minimum deal but over-flags small non-minimum deals. A stored minimum scale by experience would fix this. |
| Maximum | 17 / 19 (89%) | 17 / 32 (53%) | Misses about half of deals Spotrac labels maximum. Treat the stored-maximum test as a lower bound. |

### What the "no constraint identified" group contains

Of the 743 usable rows, 260 link to a Spotrac contract that records how the deal was signed.

| Signed using | Rows | Reading |
| --- | --- | --- |
| Bird rights | 116 | Open: the team may pay up to the maximum. |
| Cap space | 48 | Open. |
| Sign-and-trade | 2 | Open. |
| Non-taxpayer mid-level | 33 | Capped by the exception amount. |
| Early Bird rights | 25 | Capped by formula. |
| Non-Bird rights | 10 | Capped by formula. |
| Taxpayer mid-level | 10 | Capped. |
| Room mid-level | 8 | Capped. |
| Bi-annual | 6 | Capped. |
| Qualifying offer | 2 | Set by rule. |

- **166 of 260 (64%) used an open mechanism; 94 (36%) used a capped exception** that the audit's rules cannot detect.
- **Restricted free agency:** entering free-agent status is known for 227 of the 743, and 65 of those (29%) were restricted.
- **The evidence is skewed to recent seasons.** No row in 2013-14 can be checked; in 2025-26, 40 of 41 can, and 21 of those 40 were capped.
- **For the other 483 rows there is no evidence either way.**

If the checked rows are representative, roughly a third of the 743 were constrained in ways not visible historically. SCO-24 should carry the exception and restricted status as categories where known and report results on the open-mechanism subset as a sensitivity check.

## Duplicates, amendments and extensions

- **Duplicates.** 4 key collisions, all the same decision recorded twice: 3 with identical text and 1 where the same signing, team and date appears under two phrasings. They collapse to one and are counted separately by type.
- **Several signings in one league year.** 470 standard signings fall in 228 player-seasons with two or more. The database holds one salary per player-season, so pay cannot be attributed to one decision and all 470 are excluded from `Usable`. Per-team salary rows on the cached page would resolve 125 of them: the signing team has exactly one salary row that season and the player signed no other deal of any form with that team that season. An earlier version of this report said 313; it counted two signings with the same team against one shared salary row.
- **Extensions are separate decisions.** An extension is keyed to its own signing date and never counted as a new signing in the season it starts. Its first paid season comes only from a linked Spotrac extension block.
- **Extension coverage is uneven.** 149 of 174 extension events resolve a start season; 120 are usable. By signing season the log holds 6, 9, 1, 0, 0, 1 events for 2014-15 to 2019-20, then 15 to 35 per season. Rookie-scale extensions were signed every autumn in those years, so the log is incomplete before 2020-21, not the market quiet.
- **Amendments.** Neither source records renegotiations, buyouts or option decisions as dated amendments to a contract. Realized salary reflects them silently. First-year pay is the least exposed figure.
- **Spotrac linkage.** For non-extension deals, 1,148 player-season-form groups link one event to one contract; 86 are ambiguous; 77 have only an event; 169 only a contract. For extensions, 149 link, 58 Spotrac extension blocks find no event, and 2 events find no block.

## Candidate label and key

**Key.** `player_id : signing_date : kind : team`. It is stable across re-scrapes and independent of the contract's start season, which is what ADR-0003 requires. Including the team means two same-day signings with different teams stay separate decisions instead of collapsing. 6,223 raw events give 6,219 distinct keys.

**Label.** The first draft of ADR-0003 named AAV as a percent of the first paid season's cap. The data supports that exactly for only 409 usable standard signings (260 with no constraint identified), and coverage is skewed: 0 of 49 unconstrained rows in 2013-14 have exact terms, against 40 of 41 in 2025-26. Those rows are also survivors, since Spotrac pages exist only for players still in the league.

First-year salary as a percent of the first paid season's cap is available for 2,969 signings, 2,490 of them from a single-team season. Where both labels exist, they agree closely:

| Population | Median gap | Within 1 point of cap |
| --- | --- | --- |
| All usable with exact terms (409) | 0.24 points | 80% |
| No constraint identified (260, all offseason) | 0.33 points | 75% |

For comparison, v1's reported decision-point error is about 3.1 points of cap.

**Proposed data contract for SCO-24:** first-year salary as a percent of cap is the primary label for offseason standard signings in single-team seasons with no deal of another form that league year; exact AAV percent of cap is a robustness check on the rows that have it, with the overlap size reported; in-season signings are flagged because their first-year pay is prorated. ADR-0003 as now proposed in PR #146 adopts the same split: attributed first-year salary as the initial target measure and exact AAV as the robustness check. The ADR is still a proposal, so the choice is settled only when it is accepted.

## Percent of cap and leakage

- **Standard signings.** The first paid season is the league year of signing, and its cap is set before free agency opens. Features use the last completed season as of the signing date. No future information is needed.
- **In-season signings.** The current season is partly played at signing. The probe uses the prior completed season only, which is safe but stale.
- **Extensions.** The start-season cap is not known at signing; ADR-0003 calls for the projection as known at the time. No projection history is stored, so today an extension label would use the realized cap, which is a leak of the kind the ADR rules out.
- **2025-26 and later.** 22 extensions signed in 2025-26 start in 2026-27 or later, where there is neither a salary nor a cap row.

## What the existing `decision_point` flag sees

`dataset.py` marks a row as a decision point when the next season starts a stored contract. Checked against the event log:

| Stored contracts (580) | Count |
| --- | --- |
| A standard signing in that same season | 299 |
| Explained by an extension signed one to three seasons earlier | 85 |
| A two-way or short-form deal that season | 65 |
| No event found | 79 (62 start in 2026-27, after the cache was fetched) |
| No Basketball-Reference page | 52 |

So about half the flagged starts are genuine same-season signings, and 85 are extensions whose real decision date is one to three seasons earlier than the flag implies. In the other direction, the flag misses every standard signing through 2019-20 and most through 2022-23; by 2025-26 it misses 32 of 193.

## Minimum sample sizes

| Use | Recommended minimum | What the data supports |
| --- | --- | --- |
| Training a point model on unconstrained signings | 400 rows before the first evaluated fold | Cumulative rows reach 394 after 2018-19 and 473 after 2019-20, so rolling-origin evaluation can start at 2020-21 and gives six test seasons. |
| Calibrating an 80% interval | 200 decisions, 400 preferred | At 200 the 95% band on measured coverage is about ±5.5 points; at 400, ±3.9. The current 51 gives ±11. The 743 rows allow cross-fitted calibration above this. |
| Reporting error for a subgroup | 50 rows | Every position and age band clears this except 22-and-under (29), which should be merged with 23-25. |
| Reporting coverage for a subgroup | 100 rows | Small forwards (94) fall just short. Single test seasons (32 to 91 rows) are too small; pool at least two seasons. |
| Open-mechanism sensitivity check | Report, do not train | 166 rows with confirmed open mechanisms, 118 of them not known to be restricted. Enough for an error estimate, not for a model. |
| Extensions as their own model | Not yet | 120 usable rows, 116 of them signed in 2020-21 to 2024-25. Enough to evaluate as a segment, not to train separately. |

## Source, attribution, freshness and backfill risks

- **Freshness.** The Basketball-Reference cache is from early June 2026 and predates the 2026 offseason; 62 stored contracts starting in 2026-27 have no event. The 2025-26 season and earlier are unaffected.
- **Persistence.** Decision events exist only in a gitignored cache. If the cache is cleared, the history is gone until every page is re-fetched. Nothing in the database preserves it.
- **Attribution.** Both sources are third-party pages read from local copies. Their terms should be reviewed before any bulk backfill or redistribution; the probe itself fetches nothing.
- **Paywall.** Older Spotrac contracts are behind a paid tier. Backfilling exact AAV, guarantees and exception status for pre-2022 signings is a sourcing decision, not an engineering one.
- **Identity.** 171 cached pages lack a verified player link, dropping 323 signing events (5%).
- **Survivorship.** Exact terms and constraint evidence cover players still active in 2026. Any analysis restricted to those rows over-represents players with long careers.
- **Log completeness.** The transaction log under-records extensions before 2020-21 and does not label camp deals before 2017-18.

## Recommendation

**Proceed with limits.**

Proceed now:

1. Build SCO-24's decision dataset from standard free-agent signings, 2013-14 to 2025-26, keyed by `player_id : signing_date : kind : team`, with features as of the last completed season.
2. Use the 743 usable rows with no constraint identified (733 offseason) as the evaluation population, with rookie-scale, near-minimum and maximum deals kept as labelled categories, never mixed in silently.
3. Use this population for SCO-36's label validation; it is roughly 15 times the 51 contract starts available today.

Limits to carry into those tickets:

1. **Constraint status.** The 743 are not affirmatively market-set. About a third of the rows that can be checked used a capped exception, and restricted status is unknown for most. Report the open-mechanism subset alongside the headline.
2. **Label.** Exact AAV covers a quarter of signings. ADR-0003 as proposed in PR #146 takes first-year percent of cap as the initial target measure with exact AAV as a robustness check. Sourcing historical contract terms first is the alternative, and stays open until the ADR is accepted.
3. **Multi-team seasons.** 479 signings are excluded because the stored salary is one team's row. 211 of them are otherwise usable, and none can be recovered by summing rows; they need the signing team's own row attributed to the decision. Separately, 722 signings share a league year with a two-way, 10-day, Exhibit or substitution deal and are excluded because the season salary combines the deals; 138 of them pass every other condition.
4. **Extensions.** Evaluate as a segment from 2020-21 only, and only once a cap-projection history exists; do not train on them.
5. **Proxies.** The near-minimum and maximum rules are approximations. Treat their counts as approximate until a minimum-salary scale is stored.
6. **Persistence.** Before SCO-24 trains on it, store decision events in a table so the dataset does not depend on a cache.

Proposed follow-up tickets (not yet filed):

- Fix the multi-team salary row in `player_salaries`: store per-team rows as well as the season total, and measure the effect on the v1 target.
- Add a `contract_decision_events` table and loader that persists the parsed events, splitting the probe module as part of that work.
- Add reference tables: minimum-salary scale by experience, exception amounts, and cap projections as published each season.
- Verify the 171 unlinked Basketball-Reference pages.
- Decide whether to source historical contract terms, exception status and restricted status for pre-2022 signings.

## Per-team salary rows and decision attribution (SCO-44)

Added after the spike. Measured on 2026-11-17 with a read-only dry run against the live database and the same page cache; two consecutive runs produced identical JSON. Nothing has been written to production: the two tables below do not exist there yet.

```bash
cd backend
.venv/bin/alembic upgrade head                                  # creates the two tables (0012)
.venv/bin/python -m scoutiq.etl.load_team_salaries              # read-only dry run
.venv/bin/python -m scoutiq.etl.load_team_salaries --apply      # one transaction; refuses on any conflict
.venv/bin/pytest tests/test_salary_attribution.py tests/test_load_team_salaries.py -q
```

**Storage.** `player_team_salaries` keeps every salary row from a player's Basketball-Reference page as it appears: team name and abbreviation, amount, the page it came from and the date the page was cached. Rows are insert-only. A stored row whose amount differs from the source is reported as a conflict and never overwritten, and a row that disappears from the source is kept. `player_salaries` is unchanged, so the v1 label is unchanged.

| Source rows | Count |
| --- | --- |
| Salary rows on all 1,812 cached pages | 9,554 |
| On pages with a verified player link (planned for load) | 9,112 |
| On the 171 unverified pages (skipped) | 442 |
| Rows whose team abbreviation has no current team id (relocated or renamed franchises; name and abbreviation are still stored) | 138 |
| Rows with an empty team name | 1 |

A player can have two or three rows for the same team in one season (53 player-season-team groups in the cache), so each row carries its position among them.

Event building, cache reading and the attribution call live in `scoutiq/etl/contract_decision_events.py`, shared by the probe and the loader; the loader does not import the probe.

**Attribution rule (v1).** `salary_decision_attributions` holds one record per in-window standard-form signing, keyed by the event key above. A signing is attributed to a salary row only when all of these hold; otherwise it is stored as unresolved with the first reason that applies:

| Reason a signing stays unresolved | Events |
| --- | --- |
| Signing team not parsed | 2 |
| No salary rows for the first paid season | 582 |
| No row for the signing team that season | 342 |
| Two or more rows for the signing team that season | 47 |
| More than one signing of any form with that team that season | 389 |
| The entry combines contract forms | 10 |
| The signing team waived the player earlier in that league year | 17 |
| The player was traded away from, traded to, or claimed by the signing team earlier in that league year | 48 |
| A release with no team named, earlier in that league year | 3 |
| **Unresolved** | **1,440** |
| **Attributed** | **1,930** |

Row sums are never used. The loader attributes from the cached rows together with any stored row the cache no longer shows, so a row that drops out of the cache cannot turn an ambiguous signing into an attributed one; the probe's figures here use the cache alone, and the two agree while the tables are empty. Of the 582 with no salary rows, 193 are 2025-26 signings: the cache predates that season's salary tables, and the stored 2025-26 pay is bridged from current contracts. Of the 342 with no row for the signing team, 222 were traded and 115 waived, released or claimed in the same league year, so the page files the pay under another team.

**Effect on the decision cohorts.**

| Population | Events | Attributed |
| --- | --- | --- |
| Several standard signings in one league year | 470 | 121 (this report earlier estimated 125; the earlier-termination, earlier-service and release rules account for the difference) |
| Multi-team salary season | 479 | 259 |
| of which otherwise usable | 211 | 146 |
| Shares a league year with a deal of another form | 722 | 83 |

- 1,314 signings are attributed and also have a cap and prior-season BPM. 250 of them are not usable under the rules above.
- 276 signings that are usable today are not attributed: 90 are 2025-26 signings with no page rows, 167 have their one salary row filed under a different team, 15 follow a waiver by the signing team, 2 follow earlier service with the signing team, and 2 fall under the other reasons. For the other 1,064, the attributed amount equals the stored first-year salary in every case.
- 215 attributed signings are in-season, so the amount is prorated pay.
- Attribution therefore does not replace the `Usable` definition yet. Whether a single row filed under a trade destination should count is left to the shared eligibility logic in SCO-45; SCO-24's constraint classes have not been recomputed for the 250.

**Effect on the v1 label.** 428 stored player-seasons have two or more team rows, and in all 428 the stored salary differs from the row sum. The gap has a median of 0.33 points of cap and a 90th percentile of 2.14; 93 exceed 1 point. The row sum is shown only to size the gap: it is not a valid season label where rows mix contracts, so no stored value was changed.

## Scope kept

No production database writes, schema migration, UI change or model artifact change. No Trade Lab file was read or modified. Tests use synthetic fixtures and make no network requests.
