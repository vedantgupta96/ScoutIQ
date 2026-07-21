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

**Cap hit**:
What a player costs a team's payroll for a season. Precedence: the contract year covering that season (later contracts win), else realized salary.
_Avoid_: salary (realized pay is one input to a cap hit, not the same thing)

**Latest season**:
The most recent completed season with full loaded stats — the default season every surface values against, advanced once each offseason.

**Extension decision**:
The extend-now-vs-wait read for a rostered player still under contract: model value against the final guaranteed year's cap hit, with the market projected to the season he would otherwise reach free agency. Reuses the verdict ladder vocabulary (extend now / fair / don't extend). Distinct from an option decision (that decides an existing option year) and from the free-agency board (impending free agents, not extension-eligible).

**Projected market**:
A player's current percent-of-cap value carried forward to a future season at the CBA cap escalator and expressed in that season's dollars. It is deliberately **not** a forward stat forecast — trajectory enters only through the current season's lag features. See ADR-0002.
_Avoid_: forecast, projection (of production)

**Contract comps**:
A player's comparable contracts under the similarity model's contract lens — same-role players and what they are actually paid.

**Market band**:
The 25th–75th percentile of what a player's contract comps actually earn (min–max when fewer than four comps), in percent of cap and dollars. The real-market counterpart to the model's value.

**Suggested target**:
A negotiation anchor — the model value clamped into the comp market band (the band median when there is no model value). A player worth more than any comparable contract clamps to the band ceiling rather than inventing an above-market number.

**Surplus**:
Team-level total model value minus total payroll. The roster aggregate of value versus pay; distinct from a single player's value gap.
_Avoid_: value gap (that is per-player; surplus is the team total)

**Expiring money**:
Team payroll with no contract-year in the following season — salary coming off the books, and the raw material of future cap flexibility.
