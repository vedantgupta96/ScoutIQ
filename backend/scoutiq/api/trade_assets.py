"""Trade-asset math: draft-pick value, pick legality, and remaining-contract surplus.

The Trade lab's asset layer. Everything here is deterministic, stated arithmetic —
no hidden weights. Three pieces:

- Pick value: a published-research-shaped surplus curve (anchors below), expressed in
  % of one season's cap so picks share a currency with player valuations. Approximate
  by design; the response caveat says so.
- Pick legality: the CBA's seven-year window (structural — only that window is
  materialized) and the Stepien rule (no consecutive future drafts without a
  first-rounder), returned as a deterministic verdict + reasons like `salary_match`.
- Contract surplus: Σ over a player's remaining contract years of
  (model value − cap hit), the ScoutIQ-native version of a "trade value" number.

Team state (contending / neutral / rebuilding) is an explicit per-side time-discount
rate applied to future pick value and future surplus years.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from scoutiq.api.cap import SeasonCapData
from scoutiq.api.deps import DB
from scoutiq.config import settings
from scoutiq.models import Contract, ContractYear, DraftPick


def upcoming_draft_year(db: DB) -> int:
    """First draft of the tradable window: whatever the pick table starts at.

    The ownership ETL keeps draft_picks aligned with reality (it deletes drafts already
    held), so min(draft_year) is authoritative; the season-derived fallback only serves
    an empty table (fresh DB, fake test sessions)."""
    earliest = db.scalars(select(func.min(DraftPick.draft_year))).first()
    return earliest or int(settings.CURRENT_SEASON[:4]) + 1

# ---- Team-state time discounts (Phase C) -----------------------------------

TEAM_STATES = ("contending", "neutral", "rebuilding")
# Annual discount applied to future-year value: contenders devalue the future most.
TEAM_STATE_DISCOUNT = {"contending": 0.15, "neutral": 0.08, "rebuilding": 0.04}


def discount_factor(team_state: str, years_out: int) -> float:
    rate = TEAM_STATE_DISCOUNT.get(team_state, TEAM_STATE_DISCOUNT["neutral"])
    return (1 - rate) ** max(0, years_out)


# ---- Pick value curve (Phase A) --------------------------------------------

# Normalized surplus anchors (pick number -> relative units), linearly interpolated.
# Shape follows published rookie-deal surplus curves (steep at the top, long flat
# second-round tail; see docs/06). Scale: pick #1 ≈ PICK1_SURPLUS_PCT_OF_CAP of one
# season's cap in total surplus across the rookie deal.
PICK_VALUE_ANCHORS: list[tuple[int, float]] = [
    (1, 100.0), (2, 88.0), (3, 80.0), (4, 73.0), (5, 67.0), (7, 57.0), (10, 46.0),
    (14, 37.0), (18, 30.0), (22, 24.0), (26, 19.0), (30, 15.0), (35, 11.0),
    (40, 8.0), (45, 6.0), (50, 4.0), (55, 3.0), (60, 2.0),
]
PICK1_SURPLUS_PCT_OF_CAP = 20.0

# v0 pick-number assumptions when the user hasn't set one: mid-round.
DEFAULT_EXPECTED_PICK = {1: 15, 2: 45}

PICK_VALUE_CAVEAT = (
    "Pick values use an approximate rookie-deal surplus curve (% of cap) with a stated "
    "expected-pick assumption — not a lottery simulation. Ownership rows marked "
    "'default-ownership' assume teams own their own picks until a verified override says otherwise."
)


def _curve_units(pick: int) -> float:
    pick = max(1, min(60, pick))
    anchors = PICK_VALUE_ANCHORS
    for (p0, v0), (p1, v1) in zip(anchors, anchors[1:]):
        if p0 <= pick <= p1:
            if p0 == p1:
                return v0
            return v0 + (v1 - v0) * (pick - p0) / (p1 - p0)
    return anchors[-1][1]


def pick_surplus_pct(pick: int) -> float:
    """Total rookie-deal surplus for a pick number, in % of one season's cap."""
    return round(_curve_units(pick) / 100.0 * PICK1_SURPLUS_PCT_OF_CAP, 2)


@dataclass(frozen=True)
class PickValue:
    expected_pick: int
    conveyed_pick: int          # after protection shift
    years_out: int
    deferral_years: int         # extra discount years from protection roll risk
    raw_pct: float              # curve value at conveyed pick
    discounted_pct: float       # after team-state time discount
    value_usd: int | None


def value_pick(
    pick: DraftPick,
    *,
    upcoming_draft_year: int,
    team_state: str,
    salary_cap: int | None,
    expected_pick: int | None = None,
) -> PickValue:
    """Deterministic v0 pick valuation.

    Protection model: you never receive a pick inside its protected range, so a
    protected pick is valued at max(expected, protected_top + 1) with one extra year
    of discount for roll risk. Transparent and stated; no lottery odds in v0.
    """
    expected = expected_pick or DEFAULT_EXPECTED_PICK.get(pick.round, 45)
    conveyed = expected
    deferral = 0
    if pick.protected_top and pick.round == 1 and expected <= pick.protected_top:
        conveyed = pick.protected_top + 1
        deferral = 1
    years_out = max(0, pick.draft_year - upcoming_draft_year)
    raw = pick_surplus_pct(conveyed if pick.round == 1 else max(conveyed, 31))
    discounted = round(raw * discount_factor(team_state, years_out + deferral), 2)
    value_usd = int(round(discounted / 100 * salary_cap)) if salary_cap else None
    return PickValue(
        expected_pick=expected,
        conveyed_pick=conveyed,
        years_out=years_out,
        deferral_years=deferral,
        raw_pct=raw,
        discounted_pct=discounted,
        value_usd=value_usd,
    )


# ---- Pick legality (Phase A) -----------------------------------------------


@dataclass(frozen=True)
class PickLegality:
    status: str                 # pass | fail | needs-review | not-applicable
    reasons: list[str]


def stepien_check(
    *,
    owned_first_years_after: set[int],
    outgoing_first_years: set[int],
    outgoing_any_protected: bool,
    window_years: list[int],
) -> PickLegality:
    """The Stepien rule over the future-draft window after the proposed trade.

    A team may not be left without a first-round pick in consecutive future drafts.
    Protections on outgoing firsts make compliance conditional (the pick may roll),
    which mirrors real front-office 'needs review' territory rather than a clean pass.
    """
    if not outgoing_first_years:
        return PickLegality("not-applicable", ["No first-round picks leave this team."])

    gaps = [
        (y0, y1)
        for y0, y1 in zip(window_years, window_years[1:])
        if y0 not in owned_first_years_after and y1 not in owned_first_years_after
    ]
    if gaps:
        y0, y1 = gaps[0]
        return PickLegality("fail", [
            f"Trade leaves no first-round pick in consecutive future drafts {y0} and {y1} (Stepien rule)."
        ])
    if outgoing_any_protected:
        return PickLegality("needs-review", [
            "An outgoing first is protected; if it rolls forward it could create a future "
            "consecutive-year gap. Conditional Stepien compliance is not fully modeled."
        ])
    return PickLegality("pass", ["A first-round pick remains in every other future draft."])


def evaluate_pick_legality(
    db: DB,
    team_id: int,
    outgoing_pick_ids: list[int],
    incoming_pick_ids: list[int],
    *,
    upcoming_year: int,
    window: int = 7,
) -> PickLegality:
    window_years = list(range(upcoming_year, upcoming_year + window))
    owned = db.scalars(
        select(DraftPick).where(DraftPick.current_team_id == team_id, DraftPick.round == 1)
    ).all()
    owned_years = {p.draft_year for p in owned if p.id not in set(outgoing_pick_ids)}

    all_moving = db.scalars(
        select(DraftPick).where(DraftPick.id.in_(set(outgoing_pick_ids) | set(incoming_pick_ids)))
    ).all() if (outgoing_pick_ids or incoming_pick_ids) else []
    moving_by_id = {p.id: p for p in all_moving}
    incoming_first_years = {
        p.draft_year for pid in incoming_pick_ids
        if (p := moving_by_id.get(pid)) and p.round == 1
    }
    outgoing_first_years = {
        p.draft_year for pid in outgoing_pick_ids
        if (p := moving_by_id.get(pid)) and p.round == 1
    }
    outgoing_any_protected = any(
        p.protected_top for pid in outgoing_pick_ids
        if (p := moving_by_id.get(pid)) and p.round == 1
    )
    return stepien_check(
        owned_first_years_after=owned_years | incoming_first_years,
        outgoing_first_years=outgoing_first_years,
        outgoing_any_protected=outgoing_any_protected,
        window_years=window_years,
    )


# ---- Roster-count legality (Phase D2) --------------------------------------

# CBA standard-roster bounds. Two-way players (up to 3) don't count against these.
ROSTER_STANDARD_MAX = 15
ROSTER_STANDARD_MIN = 14

ROSTER_COUNT_CAVEAT = (
    "Roster counts standard contracts only (two-way players excluded). The absolute count "
    "is approximate — waived-player dead money can inflate it and incomplete contract data "
    "can deflate it — so limits surface as review flags, not hard failures. The net change "
    "in players is exact."
)


@dataclass(frozen=True)
class RosterLegality:
    status: str                 # pass | needs-review
    standard_before: int
    standard_after: int
    net_change: int             # incoming − outgoing standard players (exact)
    two_way_count: int
    reasons: list[str]


def roster_count_legality(
    *,
    standard_before: int,
    standard_outgoing: int,
    standard_incoming: int,
    two_way_count: int,
) -> RosterLegality:
    """Warn (never hard-block) when a trade pushes the standard roster out of [14, 15].

    Absolute counts are approximate (see ROSTER_COUNT_CAVEAT), so over/under conditions
    are `needs-review` with the fix stated; the net player change is always exact.
    """
    net = standard_incoming - standard_outgoing
    after = standard_before + net
    reasons: list[str] = []
    status = "pass"
    if after > ROSTER_STANDARD_MAX:
        status = "needs-review"
        reasons.append(
            f"Roster would hold ~{after} standard-salaried players (+{net}), above the "
            f"{ROSTER_STANDARD_MAX}-man limit — a waiver or additional outgoing player is required. "
            "Count is approximate."
        )
    elif after < ROSTER_STANDARD_MIN:
        status = "needs-review"
        reasons.append(
            f"Roster would hold ~{after} standard-salaried players ({net:+d}), below the "
            f"{ROSTER_STANDARD_MIN}-man minimum — a signing would be required. Count is approximate."
        )
    else:
        reasons.append(f"Roster stays within limits at ~{after} standard players ({net:+d}).")
    return RosterLegality(status, standard_before, after, net, two_way_count, reasons)


# ---- Remaining-contract surplus (Phase B) ----------------------------------

SURPLUS_CAVEAT = (
    "Contract surplus holds the player's latest model value flat across remaining years "
    "(aging not modeled) and prices each year against actual or projected cap constants."
)


@dataclass(frozen=True)
class SurplusYear:
    season: str
    cap_hit_usd: int
    cap_hit_pct: float
    value_pct: float | None
    surplus_pct: float | None
    discounted_surplus_usd: int | None


@dataclass(frozen=True)
class ContractSurplus:
    player_id: int
    years: list[SurplusYear]
    total_surplus_usd: int
    expiring: bool              # one guaranteed year or fewer remaining


def remaining_contract_surplus(
    db: DB,
    player_ids: list[int],
    value_pct_by_player: dict[int, float],
    season_caps: dict[str, SeasonCapData],
    *,
    from_season: str,
    team_state: str = "neutral",
) -> dict[int, ContractSurplus]:
    """Per player: Σ over remaining contract seasons of (model value − cap hit).

    Value is the player's latest production-implied value, held flat (stated caveat);
    future seasons are discounted at the team-state rate. Players without a loaded
    contract are absent from the result — callers degrade like they do for valuations.
    """
    if not player_ids:
        return {}
    rows = db.execute(
        select(ContractYear, Contract.player_id)
        .join(Contract, Contract.id == ContractYear.contract_id)
        .where(Contract.player_id.in_(player_ids))
        .where(ContractYear.season >= from_season)
        .order_by(Contract.player_id, ContractYear.season)
    ).all()

    by_player: dict[int, list[ContractYear]] = {}
    for year_row, player_id in rows:
        by_player.setdefault(player_id, []).append(year_row)

    results: dict[int, ContractSurplus] = {}
    for player_id, year_rows in by_player.items():
        value_pct = value_pct_by_player.get(player_id)
        years: list[SurplusYear] = []
        total = 0
        guaranteed_remaining = 0
        for offset, year_row in enumerate(year_rows):
            cap = season_caps.get(year_row.season)
            salary_cap = cap.salary_cap if cap else None
            if year_row.aav and salary_cap:
                hit_usd, hit_pct = year_row.aav, round(year_row.aav / salary_cap * 100, 2)
            elif year_row.cap_pct is not None and salary_cap:
                hit_pct = round(float(year_row.cap_pct) * 100, 2)
                hit_usd = int(round(hit_pct / 100 * salary_cap))
            else:
                continue
            if year_row.is_guaranteed:
                guaranteed_remaining += 1
            surplus_pct = round(value_pct - hit_pct, 2) if value_pct is not None else None
            discounted_usd = (
                int(round(surplus_pct / 100 * salary_cap * discount_factor(team_state, offset)))
                if (surplus_pct is not None and salary_cap)
                else None
            )
            if discounted_usd is not None:
                total += discounted_usd
            years.append(SurplusYear(
                season=year_row.season,
                cap_hit_usd=hit_usd,
                cap_hit_pct=hit_pct,
                value_pct=value_pct,
                surplus_pct=surplus_pct,
                discounted_surplus_usd=discounted_usd,
            ))
        if years:
            results[player_id] = ContractSurplus(
                player_id=player_id,
                years=years,
                total_surplus_usd=total,
                expiring=guaranteed_remaining <= 1,
            )
    return results


# ---- Trade balance: fairness meter + per-side grade (Phase 08.1) ------------
#
# A structured, analytical read of "who wins" — NOT a recommendation. It aggregates
# the same asset-ledger numbers the response already carries (player remaining-contract
# surplus + discounted pick value, each in that team's own team-state lens) into one
# A-relative differential, a needle position, a fairness tier, and a per-side letter
# grade. All thresholds are documented, cap-relative constants so they scale with the
# league's economics and stay tunable.

BALANCE_CAVEAT = (
    "Balance weighs modeled remaining-contract surplus and discounted draft-pick value "
    "from each team's own team-state lens. It is a value read, not a recommendation, and "
    "is approximate where player values are missing (see confidence)."
)

# Fairness bands as a percentage of one season's salary cap. Below EVEN the deal reads
# as balanced; beyond LOPSIDED it reads as a blowout. The needle maps linearly to LOPSIDED.
FAIRNESS_EVEN_PCT_OF_CAP = 2.0
FAIRNESS_LOPSIDED_PCT_OF_CAP = 8.0
# When model coverage of the involved players is thin, widen the "even" band so a
# half-valued package can't masquerade as a confident blowout, and flag low confidence.
LOW_COVERAGE_EVEN_MULTIPLIER = 2.0
LOW_COVERAGE_RATIO = 0.6
# Per-side letter grade from that team's own net asset value as a % of the cap.
GRADE_CUTOFFS_PCT = (("A", 6.0), ("B", 2.0), ("C", -2.0), ("D", -6.0))

_FAIRNESS_LABEL = {
    "even": "Even value exchange",
    "favors-a": "Favors Team A",
    "favors-b": "Favors Team B",
    "lopsided-a": "Lopsided toward Team A",
    "lopsided-b": "Lopsided toward Team B",
}


@dataclass(frozen=True)
class TradeBalance:
    net_usd: int                # A-relative: + favors Team A, − favors Team B
    fairness_pct: float         # needle 0..100 (50 = even)
    fairness_tier: str          # even | favors-a | favors-b | lopsided-a | lopsided-b
    fairness_label: str
    team_a_grade: str           # A..F from Team A's own net asset value
    team_b_grade: str
    team_a_value_in_usd: int
    team_a_value_out_usd: int
    team_b_value_in_usd: int
    team_b_value_out_usd: int
    low_confidence: bool        # thin model coverage of the involved players
    coverage: dict              # a_valued, a_selected, b_valued, b_selected
    reasons: list[str]


def _letter_grade(net_pct: float) -> str:
    for letter, cutoff in GRADE_CUTOFFS_PCT:
        if net_pct >= cutoff:
            return letter
    return "F"


def trade_balance(
    *,
    a_value_in_usd: int,
    a_value_out_usd: int,
    b_value_in_usd: int,
    b_value_out_usd: int,
    salary_cap: int | None,
    a_valued: int,
    a_selected: int,
    b_valued: int,
    b_selected: int,
) -> TradeBalance:
    """Fairness meter + per-side grade from each team's own-lens net asset value.

    ``*_value_in/out`` are that team's incoming/outgoing modeled asset value
    (player surplus + pick value) from its asset ledger. The headline ``net_usd``
    is Team A's own-lens net (positive favours A); grades are each side's own net.
    """
    a_net = a_value_in_usd - a_value_out_usd
    b_net = b_value_in_usd - b_value_out_usd
    cap = salary_cap or 0
    net_pct = (a_net / cap * 100) if cap else 0.0

    total_selected = a_selected + b_selected
    total_valued = a_valued + b_valued
    coverage_ratio = (total_valued / total_selected) if total_selected else 0.0
    low_confidence = total_selected == 0 or coverage_ratio < LOW_COVERAGE_RATIO

    even = FAIRNESS_EVEN_PCT_OF_CAP * (LOW_COVERAGE_EVEN_MULTIPLIER if low_confidence else 1.0)
    lopsided = FAIRNESS_LOPSIDED_PCT_OF_CAP

    if abs(net_pct) <= even:
        tier = "even"
    elif net_pct > 0:
        tier = "lopsided-a" if net_pct > lopsided else "favors-a"
    else:
        tier = "lopsided-b" if net_pct < -lopsided else "favors-b"

    fairness_pct = round(max(0.0, min(100.0, 50.0 + (net_pct / lopsided) * 50.0)), 1)

    reasons: list[str] = []
    if tier == "even":
        reasons.append("Neither side gains a decisive value edge under the model.")
    else:
        favored = "Team A" if net_pct > 0 else "Team B"
        reasons.append(f"{favored} nets the greater modeled asset value in this exchange.")
    if low_confidence:
        reasons.append(
            "Model valued only part of the players involved, so the balance is shown with "
            "low confidence and a widened even band."
        )

    return TradeBalance(
        net_usd=a_net,
        fairness_pct=fairness_pct,
        fairness_tier=tier,
        fairness_label=_FAIRNESS_LABEL[tier],
        team_a_grade=_letter_grade((a_net / cap * 100) if cap else 0.0),
        team_b_grade=_letter_grade((b_net / cap * 100) if cap else 0.0),
        team_a_value_in_usd=a_value_in_usd,
        team_a_value_out_usd=a_value_out_usd,
        team_b_value_in_usd=b_value_in_usd,
        team_b_value_out_usd=b_value_out_usd,
        low_confidence=low_confidence,
        coverage={
            "a_valued": a_valued, "a_selected": a_selected,
            "b_valued": b_valued, "b_selected": b_selected,
        },
        reasons=reasons,
    )
