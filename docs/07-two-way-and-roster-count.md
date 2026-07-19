# 07 — Two-Way Contracts + Trade Lab Roster-Count Check

_Plan from the 2026-07-19 discussion. Goal: give the Trade Lab an authoritative
roster-count rule (NBA 2K refuses roster-illegal trades) by first sourcing real
two-way-contract data so "standard contract" counts are trustworthy._

## Problem this solves

The Trade Lab reports `roster_count_before → after` but enforces nothing. A proper
check needs the CBA roster limits — **max 15 standard contracts, min 14, plus up to 3
two-way players who do NOT count against the 15**. Our roster data could not support
this because **we store no two-way flag**, so every count conflates standard + two-way:

| Count in code | Basis | Real teams show |
|---|---|---|
| workspace `roster_count` | `Player.current_team_id` (all bodies) | 16–18 |
| analysis `roster_count_after` | positive cap hit (proxy for standard) | 14–17 (DEN=17, impossible) |

Denver's "17 standard" is almost certainly 15 standard + 2 two-way (two-ways carry
small cap hits, so they leak into the cap-hit count). A hard roster-limit block on this
noisy count would **false-fail legal trades** — unacceptable for a decision-support tool.
The fix is to source the two-way flag and count standard contracts only.

## Data source (verified 2026-07-19)

- **nba_api: no.** `commonteamroster` has no contract-type field (only `HOW_ACQUIRED`).
- **Spotrac: yes, explicitly.** `/nba/{team}/contracts/` — the page `load_contracts`
  ALREADY fetches and caches — tags each player's contract type; two-ways carry a
  literal `Two-Way` label, standard players show UFA/RFA + salary. No new source or
  scraper; just a parse addition to an existing polite fetch.
- **Open completeness risk:** a spot check showed only 1 two-way for BOS where 2–3 were
  expected. Either correct (rosters fluctuate) or some two-ways sit in a page section not
  yet parsed. Phase 1 must verify all current two-ways are captured before we trust the
  count; expected ~2–3 two-ways per team, ~60–90 league-wide.

## Design decisions

- **Enforcement = authoritative once data is clean.** With two-ways excluded, the
  standard count should land at ≤15. Roster-count then joins salary-matching and Stepien
  as a real verdict tier. Recommended: **over-15 / under-14 → `needs-review`** (a strong,
  explained flag with the exact net body change, which is always exact), reserving hard
  `fail` for the genuinely impossible (total bodies > 18). Revisit toward hard-block once
  Phase 1 confirms count reliability across all 30 teams.
- **Net body change is always exact** (incoming − outgoing), independent of data quality —
  surface it even when absolute counts are approximate.
- **Two-ways are non-tradable-as-standard** but CAN be traded; v0 keeps trade mechanics
  on standard players and simply reports two-way counts separately. Full two-way trade
  rules (they convert, have their own restrictions) stay out of scope.

## Phases

### Phase 1 — Two-way data foundation (independent; branches off `main`)
1. Schema: `Player.is_two_way` boolean (default false), migration `0010_player_two_way`.
2. ETL: extend `etl/load_contracts` to parse the `Two-Way` designation on the team
   contracts page and set the flag; **verify all ~60–90 league two-ways are captured**
   (the completeness risk above) before trusting it.
3. Tests: parser test on a saved Spotrac fixture (a two-way row vs a standard row).
4. Run against Neon (additive column; safe pre/post any merge). Re-dump local mirror.
   Acceptance: each team reports a plausible 0–3 two-ways and a standard count ≤ 15.

### Phase 1 validation (2026-07-20) — done, with a decisive finding

Migration `0010` applied; `load_two_way_status` flagged **54 matched two-ways** (21 more
seen on Spotrac aren't in our `players` table — two-ways who never logged NBA stats — so
they never inflated our counts). Standard count = `not is_two_way AND positive cap hit`:

- **24/30 teams now land at the correct 14–15** (e.g. DEN 17 → 15). Two-way flagging works.
- **6 teams still read 16–17** — diagnosed as **dead money**, not two-way leakage: e.g.
  BKN's over-count is three waived-player partial guarantees at $65K–$85K, far below the
  ~$1.27M minimum. Real roster spots, no.
- A **minimum-salary floor overcorrects**: at a $0.9–1.0M floor, 0 teams read >15 but
  **13 read <14**, because our contract data also has missing/understated cap hits for
  some genuine rostered players. So the count cannot be made exact from our data.

**Conclusion (locks the Phase 2 design):** the absolute standard count is ±1–2
approximate — dead money inflates, incomplete contracts deflate — so Phase 2 is a
**`needs-review` warning, never a hard block**. The exact signal is the net body change
(incoming − outgoing); the absolute count is shown as approximate. This is what the
Design decision above already recommended; the data confirms it. Hard-block is
reconsiderable only if contract cap-hit completeness is separately fixed.

### Phase 2 — Roster-count check in Trade Lab ✅ (implemented 2026-07-20)

Done as designed (warning, not block). `roster_count_legality` in `api/trade_assets.py`
returns pass / needs-review with the exact net change; `trades.py` computes standard-only
counts (excluding `is_two_way`), runs the check per side, and folds it into the overall
verdict via `_escalate_status` (needs-review, never downgrading a salary/pick `fail`).
Response carries `roster_legality` {status, standard_before, standard_after, net_change,
two_way_count, reasons} per team + a roster caveat; NOT_MODELED notes limits are flagged,
not enforced. Frontend shows a "Roster count (standard contracts)" block with a
Within-limits / Review-roster badge, before/after/net/two-way figures, and the reason.
Tests: 4 unit (`test_trade_assets.py`) + 1 endpoint escalation (`test_trade_scenarios.py`);
198 pass. Live-verified: BKN 1-for-3 → standard 17→19, needs-review.

**Original Phase 2 spec (for reference):**
1. `api/trade_assets.py`: `roster_count_legality(standard_before, incoming, outgoing)`
   → verdict + reasons, in the `salary_match` / `stepien_check` style.
2. Trades analysis: compute standard-only counts (exclude `is_two_way`), run the check,
   escalate the overall verdict (`needs-review`, never downgrade a `fail`); expose
   standard/two-way counts and net body change in the response.
3. Frontend: show the roster verdict badge + "15 standard → 16 (waiver required)" line;
   display two-way count separately so users see why a team at "17 bodies" is legal.
4. Tests: over-15, under-14, two-way-excluded-correctly, net-change-exact scenarios;
   add to `tests/test_trade_scenarios.py`. Update the docs/06 NOT_MODELED list.

### Later (not this pass)
- Two-way contract trade mechanics (conversion, restrictions).
- In-season <14 grace-period nuance (two-week / limited-days rule).
- Game-night 8-active minimum (not a trade concern).

## Sequencing note

Phase 1's *code* is independent of the picks work, but its **migration chains after
`0009_draft_picks`** (the unmerged picks branch, PR #80). A migration off `main` (head
`0008`) would create a second alembic head that needs a merge migration later. Cleaner to
**stack this whole feature on `feat/trade-lab-picks`** (`0008 → 0009_draft_picks →
0010_player_two_way`), which also matches the real merge order — #80 first, then this.
When #80 merges, rebase onto main. Phase 2's wiring lives in `trades.py` (heavily
modified on #80), so it needs the picks branch present regardless.
