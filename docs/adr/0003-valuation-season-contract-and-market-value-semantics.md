# Valuation season contract and market-value semantics

Status: Proposed — 2026-07-26 (awaiting maintainer approval).
Revised: 2026-11-14. Part of SCO-17; resolves SCO-19.
Documentation-only: no production prediction, schema, or UI behavior changes in this
decision.

## Context

ScoutIQ's valuation time contract is inconsistent between how the model is trained and
how its output is published, and the product meaning of a "value" has never been pinned
per surface.

Training maps one season's production to the *next* season's pay. The dataset builds one
row per `(player, season t)`: every feature is drawn from season `t` or earlier, and the
supervised target `pct_cap_next` is the player's pay in season `t+1` as a percent of the
`t+1` cap ([`dataset.py`](../../backend/scoutiq/model/dataset.py),
[`features.py`](../../backend/scoutiq/model/features.py)).

Publishing then presents that output as *current-season* worth. For a stored season `S`,
`build_season_rows` feeds season-`S` production to the model and writes `value_pct`
(a signal supervised on `S+1` pay) into a row filed under season `S`, alongside
`actual_pct` = season-`S` salary ÷ season-`S` cap, with
`gap_pct = value_pct − actual_pct` ([`publish_valuations.py:111-126`](../../backend/scoutiq/model/publish_valuations.py#L111)).

### Concrete `t-1 → t → t+1` trace

Take a player on a rookie-scale deal, `t = 2023-24`:

| Quantity | Season it is about | Source |
| --- | --- | --- |
| Feature production (+ lag from `t-1` = 2022-23, age, role) | `t` (2023-24) | `build_features_from_season` |
| `prior_pct_cap` (a **feature**, not the target) | `t` salary ÷ `t` cap | `dataset.py` |
| **Training target** `pct_cap_next` | pay in `t+1` (2024-25) ÷ `t+1` cap | `dataset.py`, `features.py` |
| `decision_point` | is `t+1` a contract-start season | `dataset.py` |
| Published `value_pct` | model output — supervised on `t+1` pay | `publish_valuations.py` |
| Published `actual_pct`, `gap_pct` | `t` (2023-24) pay ÷ `t` cap | `publish_valuations.py` |
| Row stored under `season` | `t` (2023-24) | `publish_valuations.py` |

The player's 2023-24 card reads "value X% vs pay Y%." Both numbers are stored under
2023-24, so the arithmetic is *not* a literal cross-season subtraction. The defect is
that **X was supervised on 2024-25 pay and is published as 2023-24 worth without
validating that reinterpretation** — a semantic and calibration mismatch between the
*training label season* (`t+1`) and the *claimed valuation season* (`t`).

## Decision

We keep **two** distinct valuation concepts. Each has its own domain name, season
contract, API field, and user-facing label. No single number changes meaning by surface.

### 1. Production-implied worth — primary, every player-season

- **Season contract:** `performance season = valuation season = pay season = t`. All
  three coincide.
- **Meaning:** the fair-market value (as % of cap) that season-`t` production implies,
  shown against the player's *actual season-`t`* pay to form the value gap.
- **Product invariant — the value gap is same-season, always.** A value gap must never
  subtract pay from one season from a value about another.

The economic concept is anchored to season `t`. The **label used to *estimate* it is a
separate choice** and is deliberately *not* season-`t` realized salary: season-`t` salary
is usually set before season-`t` play and is dominated by incumbent-contract stickiness,
so training against it would relearn existing contracts rather than market worth.

Production-implied worth is a **latent** quantity: there is no direct observable label for
"what season-`t` production was worth." It is therefore an explicit **proxy**, validated
not against an impossible worth label but against observable **market-reset outcomes** —
the pay realized at genuine signings (concept 2's decision points). Today's v1 model uses
`pct_cap_next` (label season `t+1`) as its supervised proxy; the ADR names this proxy and
schedules validation of its season-`t` interpretation against those market-reset outcomes
(see Migration).

### 2. Next-contract market value — decision concept, at genuine market resets

- **Estimand:** the market pay a player should command at his *next genuine signing*.
  Unlike production-implied worth, this concept has an **observable label** — the pay the
  market actually sets at the signing.
- **Initial target measure (the SCO-24 experiment uses):** for standard free-agent
  signings, the attributed **first-year salary**, expressed as a **percent of the first
  paid season's cap known at signing**. It gives the first experiment a materially larger
  usable population than exact terms: SCO-20 found 1,350 usable standard signings and 743
  with no constraint identified (733 offseason), an upper bound rather than confirmed
  open-market deals. This measure is not a claim about total contract value: first-year
  salary remains exposed to deal structuring and cap-hold artifacts.
- **Exact-terms robustness check:** exact terms cover 418 usable standard signings across
  the full usable population, not necessarily the 743-row no-constraint-identified
  headline population. Where both values are available, compare the result with **AAV as
  a percent of that same cap** and report the overlapping matched-subset size. AAV smooths
  intra-contract backloading but does not itself resolve guarantees, option years,
  incentives, or contract length; none may be folded silently into either measure. The two
  measures remain distinct and are never substituted for one another. This is a practical
  coverage choice from the SCO-20 audit, not a settled validation of either label. SCO-36
  still validates the latent production-implied-worth proxy.
- **Distinct from ADR-0002 "projected market."** Projected market carries *today's* worth
  forward at the CBA cap escalator and is explicitly *not* a forward forecast.
  Next-contract market value *is* the forward market estimate ADR-0002 deferred as "a
  separate, much larger modeling effort"; it does not rebrand projected market.

**Season contract.** The valuation is keyed to the **decision event**, not a season, and
the event's anchors can span several seasons:

| Anchor | Free-agent signing | Extension that starts a year later |
| --- | --- | --- |
| performance season(s) | production through the last completed season as of the signing | same |
| signing / decision date | reset offseason — e.g. Jul 2025 | mid-incumbent-contract — e.g. Oct 2024 |
| as-of date | the signing date; features use only production known by then (through 2024-25) | the signing date; **through 2023-24 only** — 2024-25 is not complete at signing |
| contract-start season | 2025-26 | 2026-27 |
| pay / target season | 2025-26 | 2026-27 |
| cap denominator | 2025-26 cap — official as of the July signing | 2026-27 cap *as projected at the Oct-2024 signing* (official cap not yet set) |
| target value | attributed first-year salary as % of the 2025-26 cap; exact AAV % only where both values are available, with the overlap reported | separate future extension design; exact AAV % of the 2026-27 cap is a secondary candidate, pending cap-projection history |
| valuation / storage key | the signing event's stable identity (player + this decision) — never `(player, contract-start season)` | the extension event's identity, keyed to the Oct-2024 decision, not the 2026-27 start |

The **cap denominator is fixed at the first-paid-season cap as known at signing** — the
official cap if already set (the FA case), otherwise the contemporaneous projection (the
extension case). A later realized cap must not retroactively redefine what the market set.

The extension example is exactly why a decision point cannot be "the season a new contract
begins": its market-setting event (Oct 2024) precedes its contract-start season (2026-27)
by two seasons, and the as-of date must respect the *signing*, or the label leaks
2024-25/2025-26 production the team never had at the decision. Today's `decision_point`
column ([`dataset.py:88`](../../backend/scoutiq/model/dataset.py#L88)) is only a
**contract-start-season proxy** (`next_season ∈ contract.season_start`); SCO-20 audits the
true market events and their coverage, and SCO-24 moves the target onto the signing/as-of
anchors.

### Audit evidence and scope boundary

The [SCO-20 audit](https://github.com/vedantgupta96/ScoutIQ/pull/140) is pending merge and
does not change this ADR's status. It found 174 extension events, of which 120 are usable,
but treats them as their own `extension_rules` tier and excludes them from the initial
training experiment until as-of cap-projection history exists. It also excludes 479
signings with multi-team salaries (459 player-seasons). Of 211 otherwise-usable excluded signings, only two trade-only
cases are plausible row-sum recoveries; the other 209 require unmeasured attribution of the
signing team's salary row. A further 710 signings share a league year with a two-way, 10-day,
Exhibit or substitution deal and are excluded because the stored season salary combines the
deals; 128 of them pass every other condition. Those gaps are not silently included in either target.

### Fair-value vs decision comparisons

The same-season invariant governs the **fair-value surfaces** (player card, watchlist,
team surplus). The **decision surfaces** compare a player's *current* worth to a *future*
contractual figure. Until SCO-24 ships next-contract market value, the worth side of those
comparisons is **concept-1 production-implied worth** (or ADR-0002's projected-market
carry-forward) — *not* next-contract market value. These comparisons are legitimate but
are **not value gaps**; each gets its own name:

- **extend-vs-final-year comparison** — worth vs the final guaranteed year's cap hit (extension).
- **option comparison** — worth vs the option-year cap hit (option decision).
- **expiring / free-agency comparison** — worth vs expiring salary (free-agency board and targets).
- **projected-market carry-forward** — ADR-0002; worth carried forward at the cap escalator.

None of these is the same-season value gap, and none is next-contract market value today.
When SCO-24 lands, concept 2 may supply the worth side of the decision comparisons, but only
as a named forecast — never silently relabelled.

## Does a value gap compare different seasons?

**No, for the fair-value value gap.** Production-implied worth and the pay it is compared
against share one season (`t`). The current publishing path violates this only in
*meaning*, not arithmetic — it publishes a `t+1`-label-trained signal as season-`t` worth
without validation — and that is the defect the migration corrects (validate and
recalibrate the season-`t` interpretation; do not silently reinterpret).

**Yes, deliberately and by name, for decision comparisons.** The decision surfaces use the
four named comparisons above (extend-vs-final-year, option, expiring/FA, projected-market
carry-forward). Each is a distinct quantity from the value gap and — until SCO-24 — is built
from concept-1 worth or ADR-0002, not from next-contract market value.

## Alternatives considered

The ticket named three candidate meanings. Evaluated on decision usefulness, leakage
risk, label availability, and migration cost:

- **Current-season production-implied worth (chosen — primary).** Most useful for the
  cockpit's fair-value read; low leakage (as-of the end of `t`); the estimand is **latent**
  (no direct worth label), so it is validated against observed market-reset pay and its
  supervised proxy is a design choice decoupled from sticky same-season salary; moderate
  migration (validate and recalibrate the season-`t` interpretation, audit copy).
- **Next-season market value (retired to an internal training-proxy detail).** Matches
  the status-quo target, so migration cost is nil, but as a *product concept* it
  overclaims: most `t+1` pay is the same incumbent contract as `t`, reflecting contract
  stickiness rather than a market reset. Kept only as v1's supervised proxy, not surfaced.
- **Next-contract market value (chosen — decision concept, future target).** Highest
  decision usefulness for the extend/sign question; has an observable label (realized
  signing pay) but higher leakage risk (the as-of date must precede the signing, and
  extensions sign before the contract starts); limited audited coverage (only genuine
  signings — SCO-20 supplies the current evidence); highest migration cost (new target,
  event labels, coverage). The initial standard-free-agent experiment is owned by SCO-24.

## Consistency with prior ADRs

- **ADR-0001** (valuation surfaces degrade without the model): intact. Nothing here
  changes the degrade contract or adds a model dependency to contract-only surfaces.
- **ADR-0002** (extension projected market is a carry-forward, not a forecast): intact.
  Projected market is *not* rebranded. Next-contract market value is a separate,
  explicitly forward concept; if SCO-24 lands a backtested forward estimate it may later
  replace the carry-forward on the extension surface, but only as a named forecast with
  its own uncertainty story — never silently.

## Surfaces whose label or calculation would change on migration

Nothing changes in this ticket. The migration will touch each surface below. "Fair-value"
= same-season value gap; "Decision" = one of the four named decision comparisons;
"Reference/copy" = displays pay or describes worth and must not mislabel it.

| Surface | Files / route | Class | Disposition |
| --- | --- | --- | --- |
| Training / backtest | [`dataset.py`](../../backend/scoutiq/model/dataset.py), `model/train.py`, `model/experiments/` | — | Name `pct_cap_next` as the v1 market proxy and `decision_point` as a market-event proxy. Target move → follow-up ticket; SCO-24 uses attributed first-year salary % cap for standard free-agent signings and compares exact AAV only on its reported overlapping subset; SCO-20 audits the event; SCO-23 tests 3-yr feature history against the **frozen** v1 target (relative claims only) |
| Publishing + fallback | [`publish_valuations.py`](../../backend/scoutiq/model/publish_valuations.py), [`valuation.py`](../../backend/scoutiq/api/valuation.py) | — | Validate and recalibrate the season-`t` interpretation of the published signal |
| Player card / watchlist | `app/players` | Fair-value | Same-season invariant; copy → "production-implied worth" |
| Home movers | home dashboard (`app/page.tsx`), `app/league` | Fair-value | Ranks by value gap / worth change; must rank the *same-season* gap; label worth, not "market value" |
| Player comparison | `app/compare`, `frontend/lib/playerComparisonApi.ts` | Fair-value | Cross-player worth/pay/gap must all be same-season; comps sub-panel is a market anchor (below) |
| Team surplus | `app/teams` | Fair-value | Σ worth − Σ payroll; same-season consistency |
| Contract simulator | [`cap_simulator.py`](../../backend/scoutiq/api/cap_simulator.py), `app/simulator` | Fair-value + Decision | Current-row gap is same-season; simulated future contract years are decision comparisons — label the two apart |
| Similarity / contract comps | [`similarity.py`](../../backend/scoutiq/model/similarity.py) (market band, suggested target) | Reference/copy | Market band = comps' *realized* pay (% of cap, spans seasons); suggested target clamps concept-1 worth into the band — a **market anchor**, not a value gap; worth input stays same-season |
| Contract-year history | `app/players/[id]`, [`routers/players.py`](../../backend/scoutiq/api/routers/players.py) (`value_by_season`), `ContractYear` | Fair-value | Player profile renders `value_pct` and `value_gap_pct` **per contract year** (each a season); every row must hold the same-season invariant — the worth shown for a contract-year season is that season's production-implied worth vs that season's cap hit, never one current worth spread across future contract years |
| Extension | [`extension.py`](../../backend/scoutiq/api/extension.py) | Decision | *extend-vs-final-year comparison*; projected market unchanged (ADR-0002) |
| Free-agency board / targets | [`free_agency.py`](../../backend/scoutiq/api/free_agency.py) | Decision | *expiring / free-agency comparison* (worth vs expiring salary) |
| Option decision | [`free_agency.py`](../../backend/scoutiq/api/free_agency.py) | Decision | *option comparison* (worth vs option-year cap hit) — distinct from the FA comparison |
| Offseason planner | [`offseason.py`](../../backend/scoutiq/api/offseason.py), `app/offseason` | Decision | Uses projected caps (`is_projected_cap`) and expiring money; forward comparisons named; projected market per ADR-0002 |
| Decision queue | [`decision_queue.py`](../../backend/scoutiq/api/decision_queue.py) | Decision | Routes players to the named decision comparisons above; emits no same-season value gap |
| Generated player rationale | player-rationale endpoint (`player_rationales` cache) | Reference/copy | Generated text must describe worth with the concept vocabulary (production-implied worth, same-season gap) and never conflate it with next-contract value or imply a forecast |
| Model / backtest presentation | `app/model`, `model/train.py` report, [`model/experiments/report.py`](../../backend/scoutiq/model/experiments/report.py) | Reference/copy | Present the target as the v1 market proxy (training label season `t+1`) and decision-point segments per the anchors; no user-facing value gap; aligns with SCO-21 |
| Strategy backtest | `app/strategy`, backtest engine | Fair-value + Decision | Adopt the same-season invariant; name any forward comparison |
| Trade Lab | `trade_assets.py`, trade backend, `app/trade-lab` | — | **Out of scope** — inventoried as a semantic dependency only; not modified (per SCO-19) |

## Migration checklist

All items are *future* work; SCO-19 ships none of them.

1. **Model target & label.** The **target-label-validation ticket** (SCO-36; drafted below;
   distinct from SCO-23 and SCO-24) owns validation of the latent production-implied-worth
   proxy. SCO-24 uses attributed first-year salary percent of first-paid-season cap for
   its initial standard-free-agent experiment, with exact AAV percent of that cap only as
   a robustness check on a separately reported overlap; SCO-20 audits the market event and its
   coverage; evolve `decision_point` from a contract-start-season proxy toward the signing
   date + as-of date.
2. **Stored rows** (`player_valuations`). Recalibrate and re-publish once the target is
   validated; consider self-describing season-contract metadata (valuation season, pay
   season, training label season) so a stored row cannot be misread. Regenerate
   deterministically — no retrain surprises.
3. **API contracts.** Document each field's valuation-season contract; name the
   decision-surface comparisons. No schema change until the target is validated.
4. **Historical artifacts.** Regenerate backtest reports and metrics deterministically
   under the validated target.
5. **UI copy.** Audit labels across every surface in the inventory; keep "projected
   market" per ADR-0002 and the four decision-comparison names distinct from the value gap.
6. **SCO-23 (feature history) — conditional go.** SCO-23 may proceed now against the current
   v1 target held **frozen**, reporting the three-year-feature-history effect as a
   *relative* improvement only; it must not read its absolute error as validated season-`t`
   worth. Reconcile its candidate/target definitions with this ADR and the merged SCO-21
   harness, then relabel `ready-for-agent` on that basis. Moving the target is out of
   SCO-23's scope (see the follow-up ticket).

### Follow-up ticket (filed as SCO-36)

> **Title:** Validate and set the supervised label for production-implied worth
>
> **Gated on:** ADR-0003 acceptance.
>
> **Why:** ADR-0003 makes production-implied worth a same-season concept but treats it as
> a *latent proxy* and keeps v1's supervised label at `t+1` pay (`pct_cap_next`). Because
> season-`t` worth has no direct label, we must validate the proxy against observable
> outcomes before any target or feature experiment leans on its absolute meaning.
>
> **Operational ground truth:** realized **market-reset pay** — the pay set at genuine
> signings (decision points, per the concept-2 contract), with **each outcome matched to
> the most recent completed production available as of signing**. Season-`t` worth itself
> is never observed and is not treated as a label.
>
> **Scope:** Quantify how much `t+1` pay reflects a genuine market reset vs incumbent
> stickiness (segment by `decision_point`). Measure the season-`t` signal's predictive
> validity, rank-ordering, and calibration against realized decision-point pay. Decide
> whether the supervised label should move onto the market-setting event (feeding SCO-24's
> first-year-salary-percent-of-cap experiment and its exact-AAV robustness check) and how
> stored rows recalibrate. Owns the **target** migration so SCO-23 can hold the target
> fixed and SCO-24 can set the contract
> target without confounding.
>
> **Out of scope:** feature-history changes (SCO-23), the contract-decision target
> experiment (SCO-24), any production/schema/UI change.
>
> **Depends on:** ADR-0003 (acceptance), SCO-20 (genuine-signing coverage), merged SCO-21 harness.
> **Blocks:** interpreting the **existing v1 signal as absolute production-implied worth**,
> and the target migration — **not** SCO-24's own first-year salary or exact-AAV error interpretation, and **not** SCO-23's
> relative feature-history comparison, which may proceed against the frozen target.

## Scope guardrails

No production prediction, schema, or UI behavior changes in SCO-19. Trade Lab and trade
backend files are not modified.
