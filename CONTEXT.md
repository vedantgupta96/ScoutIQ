# ScoutIQ

Explainable NBA contract intelligence — a decision cockpit that tells a front office what a player's production is worth against what he's paid, with honest uncertainty.

## Language

**Valuation**:
The model's finished assessment of one player for one season — a value with an uncertainty interval, compared against actual pay, carrying a verdict.
_Avoid_: prediction, appraisal, estimate (a prediction is the raw model output; a valuation is the finished, pay-aware result)

**Valuation target**:
The (player, season) pair being valued. Which season to value is the asking surface's decision; everything after that is not.

**Percent of cap**:
The product's unit of money — salaries and valuations expressed as a share of that season's salary cap, so seasons are comparable.
_Avoid_: raw dollars (display-only)

**Value gap**:
Model value minus actual pay, in percent of cap. Positive means underpaid.
_Avoid_: delta, surplus

**Verdict**:
The categorical read of a value gap: significant bargain, bargain, fair value, slight overpay, overpaid — softened to a warning variant when caution flags fire.

**Caution flag**:
A production red flag (age, negative impact metrics, minimum-salary artifacts) that tempers a bargain verdict without changing the value gap.

**Verdict ladder**:
The single set of value-gap thresholds that produce a verdict. There is exactly one ladder, owned server-side; every surface renders it, none re-derives it.

**Cap tier**:
Where a payroll sits against the CBA's escalating thresholds: below-tax, taxpayer, first apron, second apron. Each tier costs roster-building tools.

**Apron proxy**:
Estimated apron thresholds for seasons before the 2023 CBA defined them, scaled from that season's tax line.

**Room**:
Signed distance from a payroll to a cap threshold; negative means over the line.
