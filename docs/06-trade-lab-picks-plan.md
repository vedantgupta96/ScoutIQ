# 06 — Trade Lab: Draft Picks, Asset Value, Team-State Lens

_Plan from the 2026-07-19 research into how NBA 2K MyGM/MyNBA models franchise trading,
mapped onto ScoutIQ's Trade Lab. Research sources at bottom._

## What 2K does (and what we take from it)

2K26's MyNBA "Smarter" sims evaluate 5,000+ assets/variables per trade. The parts worth
borrowing, translated into ScoutIQ's explainable-arithmetic idiom:

| 2K mechanic | ScoutIQ translation |
|---|---|
| Per-asset numeric trade value (rating + age + contract) | **Remaining-contract surplus**: Σ over remaining guaranteed years of (model value − cap hit), from `contract_years` + `player_valuations` |
| Picks/swaps/protections as assets | `draft_picks` table + surplus-value curve in **% of cap** (same currency as everything else) |
| Team state (Contending/Rebuilding) changes perceived value | Explicit per-side **time-discount rate** the user selects; two honest ledgers, no hidden sliders |
| CBA legality layer (matching, aprons, Stepien, 7-year) | Salary matching already modeled; add **pick legality checks** in the `salary_match` style: deterministic verdict + reasons |
| CPU acceptance AI | **Not copied** — ScoutIQ is decision support, not an opponent |

## Real rules to model

- **Seven-year rule:** no trading picks more than seven drafts out (loader only
  materializes the tradable window, so this is structural).
- **Stepien rule:** cannot be without a first-rounder in consecutive *future* drafts.
  Protected outgoing picks make compliance conditional → `needs-review`, mirroring the
  second-apron aggregation posture.
- **Protections:** v0 models a protected pick as conveying at
  `max(expected_pick, protected_top + 1)` plus one extra year of deferral discount —
  transparent, stated, no lottery simulation.
- **Lottery/pick expectation:** we do not store team records, so v0 takes an
  `expected_pick` assumption per pick (user-adjustable), defaulting to mid-round
  (R1: 15, R2: 45). Honest label: assumption, not projection. Later: standings-driven
  seeds → flattened-lottery odds (14/14/14 → 0.5%).

## Pick value curve (v0)

Anchored, linearly interpolated, normalized curve scaled so pick #1 ≈ 20% of one
season's cap in total rookie-deal surplus — consistent with published surplus-value
research (Pelton-style curves; Massey-Thaler loser's-curse literature warns the top of
the curve is flatter than intuition). Approximate by design, stated in the response
caveat, and stored as data (`PICK_VALUE_ANCHORS`) so recalibration is a constant edit,
not a code change. Future years discount at the team-state rate.

## Phases

- **A — Picks as assets:** migration `0009_draft_picks`; `DraftPick` ORM (year, round,
  original/current owner, `protected_top`, swap rights, conversion note); seed loader
  (`etl/load_draft_picks.py`) generating default self-ownership for the 7-draft window
  + a **verified-overrides CSV** for real traded picks (empty at first — default
  ownership is honest; fabricated trade data is not); `api/picks.py` valuation +
  legality; picks in the trade request/response.
- **B — Contract surplus per player:** remaining-guaranteed-years surplus ledger per
  trade side (uses stored valuations; value held flat across years, aging not modeled —
  caveat says so). Expiring deals ≈ zero surplus + cap relief, rookie-scale stars ≈
  large positive.
- **C — Team-state lens:** request-level `team_state` per side
  (contending 15% / neutral 8% / rebuilding 4% discount) applied to future pick value
  and future-year surplus. Same trade, two ledgers.
- **Later (not this pass):** real pick-ownership scrape (RealGM/Tankathon, polite +
  cached), standings-driven pick expectation, swaps math, 3-team trades, TPE inventory.

## Data honesty

Default ownership ("every team owns its own picks") is clearly labeled
`default-ownership`; real traded picks enter only through the overrides CSV with a
source URL per row. The UI/response caveat states pick data completeness. No invented
trades, no invented protections.

## Research sources

- [NBA 2K26 MyNBA Courtside Report](https://nba.2k.com/2k26/courtside-report/mynba/)
- [DiamondLobby — trade sliders](https://diamondlobby.com/nba-2k24/best-realistic-trade-sliders-nba-2k24/)
- [Hoops Rumors — Stepien rule](https://www.hoopsrumors.com/2024/05/hoops-rumors-glossary-ted-stepien-rule-5.html) · [protecting far-off picks](https://www.hoopsrumors.com/2022/08/the-complications-of-protecting-far-off-traded-picks.html)
- [CBA Guide — trade rules](https://cbaguide.com/transactions/trades/traderules/)
- [NBA.com — lottery odds explainer](https://www.nba.com/news/nba-draft-lottery-explainer) · [Tankathon pick odds](https://www.tankathon.com/pick-odds)
- [Wharton — NBA draft value curves](https://wsb.wharton.upenn.edu/wp-content/uploads/2024/12/NBA_draft_curves-6.pdf) · [Loser's curse paper](https://arxiv.org/pdf/2411.10400) · [Valuing picks programmatically](https://travispchen.com/picks-in-python/)
