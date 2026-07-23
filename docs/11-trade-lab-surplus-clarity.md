# 11 — Trade Lab: contract-surplus clarity + contract-year inclusion policy

_Design + implementation notes for issue #117. Make Trade Lab verdicts understandable
and defensible by clearly separating **salary matching**, **remaining-contract surplus**,
and **manual-review legality**, and by refusing to silently value uncertain contract years
at 100% commitment._

---

## 1. The problem the issue exposed

For a 2026-27 Miami/New Orleans trade the exchange UI shows Bam at `-$49.4M value` and
Zion at `-$8.6M value`, a `+$40.7M modeled value` headline, `A/F` grades, and a separate
`Manual review required`. Every number is arithmetically consistent with the current
implementation, but the UI never exposes enough of that implementation to reconcile it:

1. `Value` reads like total player/market value, but it is **discounted remaining-contract
   surplus** (Σ over remaining years of `model value % − cap-hit %`, times the cap, times a
   team-state discount).
2. The year-by-year inputs and the discount are hidden.
3. Salary compliance, roster/pick review, and asset value are three independent axes but
   the verdict presentation conflates them.
4. **All** remaining years contribute — including Bam's 2028-29 **player option** — so
   uncertain money is treated exactly like committed money.
5. Holding the latest value % flat across future years is a material assumption, invisible
   near the result.
6. The projected cap constants that scale every % and $ are not surfaced.

## 2. Contract-year inclusion policy (the core modeling decision)

We do **not** have reliable exercise/guarantee probabilities, so we do not blend them.
Instead every remaining contract year is classified from the data we do have
(`ContractYear.is_guaranteed`, `is_player_option`, `is_team_option`) into exactly one
status, and surplus is reported under **two transparent scenarios**:

| Status | Meaning | Counts in **Committed** | Counts in **All years** |
|---|---|:---:|:---:|
| `guaranteed` | Fully guaranteed, not an option | ✅ | ✅ |
| `player_option` | Player decides whether to play | ❌ | ✅ |
| `team_option` | Team decides whether to keep | ❌ | ✅ |
| `non_guaranteed` | Not guaranteed (may be waived) | ❌ | ✅ |

- **Committed** (default): only `guaranteed` years. This is the honest floor — money both
  sides are certain to be on the hook for. Bam's option year is excluded here.
- **All years**: every listed year, clearly labelled as an upside/downside scenario that
  assumes every option/non-guaranteed year is exercised.

`status == "guaranteed"` is the single source of truth for "committed"; a year that is a
player/team option or explicitly non-guaranteed is never committed even if its
`is_guaranteed` flag is set (options can carry guaranteed money *if exercised*).

The **flat-value assumption** (latest model value % held across all remaining years, aging
not modeled) is preserved — the issue's non-goal is Valuation v2 — but it is now stated in
the API caveat and shown in the UI breakdown.

## 3. API changes (`/trades/analyze`)

- Request gains `surplus_scenario: "committed" | "all"` (default `"committed"`).
- Each `SurplusYear` returns everything needed to reproduce the total: `season`,
  `cap_hit_usd`, `cap_hit_pct`, `value_pct`, `surplus_pct`, `discount_factor`,
  `discounted_surplus_usd`, `status`, `committed`.
- Each player detail returns `total_surplus_usd` (selected scenario),
  `total_surplus_committed_usd`, `total_surplus_all_usd`, `has_uncertain_years`.
- Top-level `review_reasons`: the **actual** triggering reason(s) for a `needs-review`
  verdict (e.g. "New Orleans would hold ~17 standard contracts"), team-prefixed — not a
  generic list of possibilities.
- Top-level `cap_reference`: `{ season, salary_cap_usd, is_projected }` — the cap season
  and value every percentage is priced against, with the projected flag as freshness.

The balance meter, per-side grades, and `total_surplus_usd` all follow the **selected
scenario**, so the Bam-for-Zion headline reconciles to the visible breakdown under whatever
scenario is chosen.

## 4. UI changes (`/trade-lab`)

- Row label `value` → **contract surplus**, with plain-language copy: positive = the model
  values the player above the salary owed; negative = the salary owed exceeds modeled value.
- Expandable per-player breakdown: one row per contract season with cap hit ($ and % of
  cap), modeled value %, raw surplus %, discount factor, discounted surplus, and a status
  chip. The rows sum to the displayed total under the selected scenario.
- A **scenario toggle** (Committed years / All listed years) with an uncertain-year flag on
  players who have option/non-guaranteed years.
- Salary matching, asset balance, and roster/pick legality stay in separate labelled
  sections; the verdict spells out the exact `needs-review` reason.
- The cap season/value and each team's state discount are visible near the result.

## 5. Non-goals (unchanged from the issue)

Rebuilding the valuation model / Valuation v2; claiming contract surplus is a real-world
trade recommendation; changing draft-pick valuation beyond keeping its contribution
separately identifiable.
