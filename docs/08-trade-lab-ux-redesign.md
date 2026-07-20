# 08 — Trade Lab UX Redesign (decision-first, structured gamification)

_Plan from the 2026-07-20 discussion. Goal: turn the Trade Lab from a dense
compliance read-out into a **decision cockpit** a GM/analyst can parse in one
glance — answering "does this work?" and "who wins?" before the data inventory,
per PRODUCT.md. Establish a reusable, analytical (not arcade) gamification
vocabulary that later extends across the product._

## Who this is for (PRODUCT.md)

NBA front-office decision makers — GMs, cap strategists, analysts, scouts — in
"high-context decision sessions where credibility, speed, uncertainty, and source
traceability matter." Design principles that the current Trade Lab violates:

1. **Make the decision state visible before the data inventory.** ← most violated.
2. Treat uncertainty as a premium feature, not a caveat.
3. Give contract math a physical shape (timelines, bands, pressure zones).
4. **Fuse scouting, value, and cap context into one read instead of siloed panels.** ← violated.
5. Use motion/color to clarify change, ranking, risk, confidence — not decorate.

Anti-references we must respect: **no sports-betting aesthetics, no gimmicky
gauges, no identical metric tiles.** Gamification here = precise instruments, not
an arcade accept-o-meter. (Tone decision confirmed 2026-07-20: "structured,
analytical.")

## Problem — what's confusing today

Current results = a verdict string + **two mirror-image panels**, each stacking
~5 metric blocks (cap pressure, payroll shift, salary matching, draft picks,
roster count) plus a collapsed value/fit drawer. ~40 numbers total. Concretely:

| Issue | Where | Why it hurts a GM |
|---|---|---|
| **No "who wins / is it fair" headline.** The net-value read (`assets.net_usd`) is buried inside the picks block and only renders when picks exist. | `Impact` picks block | The GM's *first* question — is this a good deal and for whom — is answered last, or not at all. Violates Principle 1. |
| **Compliance jargon is the headline.** "Modeled salary verdict", "allowed incoming", "rule margin", "aggregated-standard-tpe", "Stepien pass". | verdict header + `siq-trade-match` | CBA internals are shown as the primary read instead of a plain yes/no + one-line why. |
| **Two teams as siloed mirrors.** Identical panels force the user to diff them by eye. | `siq-trade-impacts` (`1fr 1fr`) | A trade is a *negotiation*; the interesting thing is the asymmetry (who overpays, who takes tax, whose roster breaks). Violates Principle 4. |
| **Uncertainty shown as a caveat.** "2/3 sent · 1/2 received valued" with no explanation. | value drawer | Principle 2 wants uncertainty as a premium, legible signal — coverage/confidence, not a cryptic fraction. |
| **Flat hierarchy.** Everything is either an always-on dense grid or hidden in `<details>`; no headline → support → deep-dive ladder. | whole `Impact` | Nothing guides the eye to what matters first. |
| **Stale cosmetic bug.** Header reads "Modeled **salary** verdict" even when the failure is pick legality or roster count. | `page.tsx:656` (docs/06 leftover) | Mislabels the verdict. |

## The redesign — a decision hierarchy

Reorganize results into four tiers, headline-first:

### Tier 0 — Verdict bar (the decision, in one strip)

Two **orthogonal** reads, side by side (the product genuinely has two axes that
2K fuses into one meter; we keep them honest and separate):

- **Legality stamp** — does the trade work under modeled rules? `Works` /
  `Needs review` / `Blocked`. Folds salary-match + pick legality + roster count
  (already computed by `_escalate_status`). One line of plain-language "why".
- **Balance meter** — who wins on value, by how much? A horizontal value scale
  with a centered needle: `Team A ◄——●——► Team B`, labeled **Even / Favors A /
  Lopsided**, with the dollar differential. Driven by the asset ledger
  (player remaining-contract surplus + discounted pick value). This is the
  gamification core: a **calibrated instrument**, not a gauge for its own sake.

### Tier 1 — The Exchange (fused, not two silos)

One central ledger showing what crosses each way as a **balance**, not two mirror
grids: players (name + value), picks (label + value), net salary, net asset
value per side. Serves Principle 4 directly. This replaces the "diff two panels
by eye" problem with a single legible exchange.

### Tier 2 — Per-team consequences (only what changed)

Per side, the consequences that matter — not the raw inventory:

- **Cap trajectory** — keep `CapBar` (the Principle-3 physical-shape win) + the
  tier transition line ("Crosses into first apron").
- **Roster fit change** — the top 1–2 need deltas, with confidence.
- **Roster-count flag** — the two-way-aware standard count warning (docs/07),
  shown only when it fires.

### Tier 3 — Mechanics on demand (`<details>`)

Salary-matching math (method, allowed incoming, margin), pick surplus detail,
assumptions & exclusions. Present for the analyst who wants the proof; never the
headline. Every jargon term here gets plain-language microcopy / tooltip
(allowed incoming, margin, % of cap, coverage).

## Gamification vocabulary (reusable, product-wide)

A small, structured set of decision signals — defined once here, reused later on
Watchlist / valuation surfaces so "gamification has a proper structure":

- **Legality stamp** — Works / Needs review / Blocked (green / amber / red +
  icon, never color-alone).
- **Balance meter** — a value needle on a centered scale; tiers Even (±small) /
  Favors X / Lopsided X, from a normalized fairness score.
- **Side grade** — a per-team letter (A…F) from value-received vs value-sent,
  shown as a calibrated chip. Analytical, not arcade — grade reflects modeled
  surplus differential, with a tooltip explaining the basis and coverage.
- **Confidence chip** — how much of the package the model actually valued
  (coverage), surfaced as a premium signal (Principle 2), not a raw fraction.

These four primitives are the whole "gamification" surface. No animated accept
meter, no arcade language.

## Backend — what the API must add (single source of truth)

The Balance meter and grades must be **computed server-side** (mirroring how
salary/pick verdicts already are), not derived ad hoc in React. Add a top-level
`balance` object to `/trades/analyze`:

```
balance: {
  team_a_value_in_usd, team_a_value_out_usd,   # surplus(players received/sent) + picks in/out
  team_b_value_in_usd, team_b_value_out_usd,
  net_usd,               # + favors A, − favors B (or pick a convention & document it)
  fairness_pct,          # normalized 0..100 needle position (50 = even)
  fairness_tier,         # even | favors-a | favors-b | lopsided-a | lopsided-b
  fairness_label,        # plain language
  team_a_grade, team_b_grade,   # A..F from received-vs-sent differential
  coverage: { a_valued, a_selected, b_valued, b_selected },  # confidence
  caveat,
}
```

All inputs already exist in `_asset_ledger` (player surplus + pick value per
side). This is an aggregation + normalization layer, not new modeling. Fairness
thresholds and grade cutoffs are defined as documented constants (tunable), and
degrade gracefully when coverage is low (low coverage ⇒ wider "even" band + a
confidence flag, never a false-confident grade).

## Phases

### Phase 1 — Backend `balance` summary (independent, testable) ✅ done 2026-07-20
1. `trade_assets.py`: `trade_balance(a_ledger_inputs, b_ledger_inputs, coverage)`
   → fairness score, tier, label, per-side grade, with documented thresholds.
2. `trades.py`: assemble `balance` from the two asset ledgers + value coverage;
   add to the analyze response. Add a `BALANCE_CAVEAT`.
3. Tests: even trade → even + ~equal grades; lopsided → correct side + tier;
   low-coverage → widened band + confidence flag; grade monotonicity.

Delivered: `TradeBalance` dataclass + `trade_balance()` in `trade_assets.py`
(documented `FAIRNESS_EVEN_PCT_OF_CAP=2.0`, `FAIRNESS_LOPSIDED_PCT_OF_CAP=8.0`,
grade cutoffs, `LOW_COVERAGE_EVEN_MULTIPLIER=2.0`). `trades.py` assembles
`balance` from both asset ledgers + value coverage and ships it on `/analyze`;
`BALANCE_CAVEAT` added to assumptions. 8 unit tests in `test_trade_balance.py`
(even, lopsided both sides, grade monotonicity, low-coverage widened band +
`low_confidence` flag, empty). Convention: `net_usd`/tiers are **A-relative**
(+ favors A). Full suite green.

### Phase 2 — Verdict bar: Legality stamp + Balance meter ✅ done 2026-07-20
1. `api.ts`: add the `balance` type to `TradeResponse`.
2. New `TradeVerdictBar` — Legality stamp (from `overall_status`) + Balance meter
   (needle component) + plain-language one-liners. Replaces the current header.
3. Fix the "Modeled salary verdict" label → decision-oriented ("Trade verdict").
4. Balance-meter component: centered scale, needle at `fairness_pct`, tier label,
   `net_usd` differential; reduced-motion + non-color states.

Delivered: `components/trade/BalanceMeter.tsx` (`BalanceMeter` needle instrument +
`GradeChip`, both reusable), `TradeVerdictBar` in `page.tsx`, header relabeled
"Trade verdict". **Needle convention corrected during verification:** the needle
leans toward the *winner* on a left(A)→right(B) axis — `fairness_pct = 50 −
(net_pct/lopsided)·50` (0 = fully A, 100 = fully B). Live-verified: Curry↔Tatum
reads "Lopsided toward BOS", needle pinned right, GSW **F** / BOS **A**.

### Phase 3 — The Exchange (fuse the two silos) ✅ done 2026-07-20
1. New `TradeExchange` — one central ledger: A-sends / B-sends columns with
   player+pick values and per-side net; a balance visual, not two mirror grids.
2. Retire the duplicated value/pick grids from `Impact`.

Delivered: `TradeExchange` + `ExchangeSide` render both outgoing packages
(players with salary + modeled surplus, picks with value, per-side salary/asset
footer) as two bordered cards with a center swap glyph; the old pick/value grids
are gone from `Impact`.

### Phase 4 — Per-team consequences + plain language + a11y ✅ done 2026-07-20
1. Slim `Impact` to Tier-2 consequences (CapBar + tier line, fit deltas,
   roster-count flag). Move salary-matching math + pick math into a Tier-3
   `<details>` "The math".
2. Microcopy + tooltips for every retained jargon term (allowed incoming,
   margin, % of cap, coverage, surplus).
3. Accessibility: WCAG AA contrast, keyboard, `prefers-reduced-motion`, and no
   color-only state (icons/text on every stamp/tier). Confidence chip for coverage.

Delivered: `Impact` now shows cap trajectory (CapBar) + `FlagChip` row (Salary
match / Stepien / Roster, each with a plain-language tooltip) + roster-fit shift,
with all CBA math in a "The math" drawer. Needle honours `prefers-reduced-motion`;
stamps/chips carry text + icon, never color alone.

### Phase 5 — Polish + verify ✅ done 2026-07-20
1. Live-verify a real trade (Curry↔Tatum) renders correctly across the new
   hierarchy — verdict bar, Exchange, slim consequence panels.
2. Frontend typecheck clean; backend suite 206 passing (8 new balance tests).
   Screenshotted the redesign + the corrected verdict bar.

Note: a Turbopack dev-HMR quirk skipped recompiling an appended CSS block until
the file was re-saved — a dev-only artifact, not a code issue.

## Sequencing note

This stacks on the same chain as docs/07 (`feat/two-way-roster-count`, on the
picks branch / PR #80) because Phase 4 touches the roster-count block and Phase 1
extends the analyze response that #80 reshaped. Keep it as the next branch in the
stack; rebase onto main once #80 merges.

## Out of scope (later)
- Extending the gamification vocabulary to Watchlist / valuation surfaces
  (defined here, applied product-wide later).
- Save / compare multiple trade scenarios.
- Three-team trades (already in NOT_MODELED).
</content>
</invoke>
