# ScoutIQ — Data-Source Spike

> **Purpose:** answer the questions that can *kill the project* before we build around assumptions.
> The flagship risk is not the ML — it's whether we can reliably get **contract + cap data**.
> Goal: spend ~3–5 focused days here and come out with a go / no-go on each source.
>
> **How to use this doc:** fill in the `→ FINDING:` lines as you investigate. Anything still blank
> after the spike is an unresolved risk. Don't start the schema (doc 02) until the contract-data row
> below is green.

---

## 0. Decision summary (fill this in last)

| Source | Need it for | Verdict (✅ go / ⚠️ workable / ❌ blocked) | Plan B |
|--------|-------------|-------------------------------------------|--------|
| nba_api (basic stats) | player/season box stats | ✅ go — fast (~0.2s), clean star matches | — |
| nba.com advanced stats | USG/TS/PIE/ratings | ✅ go — `leaguedashplayerstats` (Advanced) returns all, 572 players/season in ~0.2s | — |
| BBRef advanced stats | BPM/VORP/WS/WS-48 | ✅ go — Advanced table (incl. `Pos`!) parses cleanly | — |
| Contracts — historical salary | backtest target (% of cap) | ✅ go — BBRef "Salaries" table parses cleanly | — |
| Contracts — forward structure | live simulator (guaranteed/options/future yrs) | ❌ NOT in BBRef salary table → need Spotrac | Plan B: AAV-only Phase-1 simulator |
| Scouting text | LLM features | ⏳ not yet probed (Sonar) | — |

→ **Overall go/no-go:** GO. Stats + historical salary are solid → the **valuation model + backtest is
unblocked today**. The one open risk is **forward contract structure** for the live simulator (Spotrac,
or fall back to AAV-only). Sonar still to probe.

---

## 1. Stats (the numbers backbone)

### Candidate: `nba_api` (Python wrapper over stats.nba.com)
Questions to answer:
- [ ] Which endpoints give per-season **advanced** stats (BPM, VORP, WS, PER, usage, on/off)? (`leaguedashplayerstats`, `playercareerstats`, etc.)
- [ ] Rate limits in practice — how fast before it blocks? What headers/delays are needed?
- [ ] How far back does coverage go cleanly? (We need ~2010+ for a valuation backtest.)
- [ ] Player IDs — stable? Do they join to a contract source by name, or do we need a crosswalk?

→ FINDING (2026-06-06 probe): `playercareerstats.PlayerCareerStats` returns **27 basic box columns only**
  (GP, MIN, FG/3P/FT, REB, AST, etc.) — **no advanced metrics** (PER/BPM/VORP/WS/USG/TS all absent).
  Fast (~0.1–0.2s/player), stable integer IDs, all 3 test stars matched 1:1.
  **Action:** get advanced stats from `leaguedashplayerstats` with `MeasureType='Advanced'`, OR derive
  TS%/USG from box scores, OR pull BPM/VORP from Basketball-Reference. Don't rely on the career endpoint.
  Caveat: only tested 3 easy stars — journeymen / slug collisions are the real name-match test (do next).

### Backup / supplement: Basketball Reference
- [ ] Does it have the advanced stats nba_api lacks?
- [ ] Scraping limits — Sports-Reference rate-limits hard (~20 req/min) and bans. Acceptable?
- [ ] ToS check.

→ FINDING:

### Shortcut worth checking: Kaggle datasets
- [ ] Is there a pre-built historical stats+salary dataset good enough to **bootstrap the backtest**
      without scraping anything? (Lets you prove the ML before solving live ETL.)

→ FINDING:

---

## 2. Contracts & cap — **the make-or-break row**

> If this is a nightmare, we want to know in week 1. Be ruthless here.

### What we actually need
- Per-player, per-season **cap hit** and **guaranteed** amount
- Contract **structure**: total value, length, signed date, player/team options, incentives
- Per-season league **cap constants**: salary cap, tax line, first/second apron, max tiers
- Ideally: dead money / waived cap treatment (Phase 3)

### Candidate sources
| Source | Has | Catch |
|--------|-----|-------|
| **Spotrac** | most detailed cap/dead-money | scraping, ToS-gray, layout changes |
| **Basketball Reference (Contracts)** | salary tables per team/player | future years only, less structure |
| **HoopsHype** | salaries | less detail on structure |
| **Kaggle** | historical salary snapshots | may be stale / incomplete structure |

Questions:
- [ ] Can you get a clean **historical** contract table (signed 2010–2025) for the backtest? From where?
- [ ] Can you get **current** contracts for the live simulator?
- [ ] How is the data structured — one row per contract, or per player-season? How much cleaning?
- [ ] Player options / team options / non-guaranteed years — are these captured anywhere parseable?
- [ ] Name → player-ID join: how bad is the matching problem? (nicknames, Jr./Sr., accents)
- [ ] ToS / scraping posture for the source you pick. Note it honestly in the README.

→ FINDING (2026-06-06 probe): BBRef player pages return **status 200**, slugs resolved for all 3 stars,
  and a clean **"Salaries" table** parses: columns `[Season, Team, Lg, Salary]`, e.g. LeBron 2003-04 =
  `$4,018,920`. This is **realized historical salary per past season** — perfect for the backtest target
  (join to that season's cap → % of cap). **BUT it is NOT forward contract structure** — no guaranteed
  amounts, no player/team options, no future committed years. (Gotcha confirmed: tables were buried in
  HTML comments; we had to strip `<!-- -->` before `read_html` saw them — 26–27 tables per page.)
  **Action:** historical salary ✅ done via BBRef. For the **live simulator** we still need forward
  structure → probe **Spotrac** next, else invoke Plan B below.

→ **Plan B if structured contracts are unavailable:** model on **AAV (total/years)** only and drop
   year-by-year structure from the Phase-1 simulator. (Less rich, but unblocks everything — and the
   valuation backtest doesn't need it at all.)

---

## 3. Cap rules — how much of the CBA to model

> The 2023 CBA is complex (Bird rights, exceptions, two aprons, repeater tax). We model a
> **simplified-but-correct subset** and state assumptions in the UI.

Decide the Phase-1 subset (check what you'll model):
- [ ] Per-year cap hit roll-up + team total
- [ ] Luxury-tax line + progressive tax brackets (with repeater? probably skip in P1)
- [ ] First apron / second apron flags
- [ ] Max-salary tiers by experience (25% / 30% / 35% of cap) + max raises (8% Bird / 5% non-Bird)
- [ ] Rookie-scale (probably **out of scope** P1)

Explicitly **NOT** modeling in Phase 1 (write these down — they become UI disclaimers):
- Bird-rights eligibility nuance, mid-level / bi-annual exceptions, sign-and-trade restrictions,
  trade-matching rules, stretch provision, etc.

→ Cap constants change yearly → store them in a **`cap_constants` table**, never hard-code. Confirm you
  can source the per-season numbers (cap, tax, aprons, max tiers).

→ FINDING:

---

## 4. Scouting / qualitative text (LLM layer)

- [ ] Sources for scouting narratives / news / draft writeups (articles, Reddit, draft sites)?
- [ ] **Perplexity Sonar** spike: does a query like *"recent scouting analysis and injury news on
      {player}, {season}"* return useful text **with citations**? Capture a sample response.
- [ ] Cost per call + latency (we'll cache in Redis by `query+date`, but confirm the unit economics).
- [ ] Can we build a small **gold set** (20–50 notes hand-labeled with ratings) for the eval harness?

→ FINDING:

---

## 5. Exit criteria (the spike is "done" when…)
- [ ] You can produce a CSV of ~200 historical contracts joined to player stats → enough to train v0 valuation.
- [ ] You can fetch current stats + contract for any active player on demand.
- [ ] You have one captured Sonar response with citations.
- [ ] The decision table in §0 is fully filled, with a clear overall go/no-go.
