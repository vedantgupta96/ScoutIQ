"""Extension-decision logic — should a team sign a player to a new deal now?

Compares model value against the pay the player would enter their next contract at,
and against the guaranteed pay remaining on the current deal, to recommend a stance.
Deep module: no router imports, DB orchestration only (contract load, valuation,
cap projection) so it stays unit-testable without a live DB or model artifact.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, select

from scoutiq.api.cap import cap_for, load_season_caps
from scoutiq.api.free_agency import DECISION_THRESHOLD_PCT
from scoutiq.api.season import LATEST_SEASON, next_season
from scoutiq.api.valuation import value_player_detail
from scoutiq.models import Contract, ContractYear, Player


@dataclass
class ExtensionDecision:
    player_id: int
    eligible: bool
    ineligible_reason: str | None
    value_season: str
    value_pct: float | None
    value_lo_pct: float | None
    value_hi_pct: float | None
    current_pay_pct: float | None
    final_contract_season: str | None
    entering_season: str | None
    projected_aav_usd: int | None
    projected_aav_lo_usd: int | None
    projected_aav_hi_usd: int | None
    projected_cap_usd: int | None
    gap_pct: float | None
    verdict: str
    tone: str
    rationale: str
    trajectory_note: str | None
    caveat: str


CAVEAT = (
    "Projected market carries today's modeled value forward at the CBA cap escalator; it is "
    "not a forward stat projection. Trajectory enters only through current-season lag features."
)


def _trajectory_note(attribution: list[dict] | None) -> str | None:
    if not attribution:
        return None
    entry = next((a for a in attribution if a.get("label") == "Trajectory"), None)
    if entry is None:
        return None
    delta = entry.get("delta_pct")
    if delta is None:
        return None
    if delta >= 1.0:
        return "Trajectory is rising — waiting likely raises the market price."
    if delta <= -1.0:
        return "Trajectory is declining — an extension carries downside risk."
    return None


def decide_extension(db, player_id: int) -> ExtensionDecision:
    """Load the player's current contract and recommend an extend/wait/decline stance."""
    player = db.get(Player, player_id)
    if not player:
        raise LookupError(f"Player {player_id} not found.")

    contract = db.scalars(
        select(Contract)
        .where(Contract.player_id == player_id)
        .order_by(desc(Contract.season_start), desc(Contract.scraped_at))
        .limit(1)
    ).first()
    if contract is None:
        raise LookupError(f"No contract found for player_id={player_id}.")

    year_rows = db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id == contract.id)
        .order_by(ContractYear.season)
    ).all()

    all_seasons = [row.season for row in year_rows]
    final_contract_season = max(all_seasons) if all_seasons else None
    entering = next_season(final_contract_season) if final_contract_season else None

    remaining = [row for row in year_rows if row.season > LATEST_SEASON]

    try:
        valuation, features, attribution = value_player_detail(db, player_id, LATEST_SEASON)
        value_pct, value_lo_pct, value_hi_pct = valuation.value_pct, valuation.lo_pct, valuation.hi_pct
    except LookupError:
        value_pct = value_lo_pct = value_hi_pct = None
        attribution = None

    current_pay_pct = None
    guaranteed_remaining = [row for row in remaining if not (row.is_player_option or row.is_team_option)]
    if guaranteed_remaining:
        last_guaranteed = guaranteed_remaining[-1]
        if last_guaranteed.cap_pct is not None:
            # cap_pct is a SQLAlchemy Numeric → Decimal on live rows; coerce so it can be
            # arithmetic-combined with the float value_pct below (documented Decimal gotcha).
            current_pay_pct = round(float(last_guaranteed.cap_pct) * 100, 2)

    trajectory_note = _trajectory_note(attribution)

    if not remaining:
        return ExtensionDecision(
            player_id=player_id,
            eligible=False,
            ineligible_reason=(
                "No contract years remain after the current season (impending free agent — "
                "see the Free Agency board)."
            ),
            value_season=LATEST_SEASON,
            value_pct=value_pct,
            value_lo_pct=value_lo_pct,
            value_hi_pct=value_hi_pct,
            current_pay_pct=current_pay_pct,
            final_contract_season=final_contract_season,
            entering_season=entering,
            projected_aav_usd=None,
            projected_aav_lo_usd=None,
            projected_aav_hi_usd=None,
            projected_cap_usd=None,
            gap_pct=None,
            verdict="Not extension-eligible",
            tone="neutral",
            rationale="Not extension-eligible.",
            trajectory_note=trajectory_note,
            caveat=CAVEAT,
        )

    if not guaranteed_remaining:
        return ExtensionDecision(
            player_id=player_id,
            eligible=False,
            ineligible_reason=(
                "Only option years remain; handled as an option decision, not an extension."
            ),
            value_season=LATEST_SEASON,
            value_pct=value_pct,
            value_lo_pct=value_lo_pct,
            value_hi_pct=value_hi_pct,
            current_pay_pct=current_pay_pct,
            final_contract_season=final_contract_season,
            entering_season=entering,
            projected_aav_usd=None,
            projected_aav_lo_usd=None,
            projected_aav_hi_usd=None,
            projected_cap_usd=None,
            gap_pct=None,
            verdict="Not extension-eligible",
            tone="neutral",
            rationale="Not extension-eligible.",
            trajectory_note=trajectory_note,
            caveat=CAVEAT,
        )

    projected_cap_usd = None
    projected_aav_usd = projected_aav_lo_usd = projected_aav_hi_usd = None
    if entering is not None:
        caps = load_season_caps(db)
        cap_data = cap_for(entering, caps)
        if cap_data is not None:
            projected_cap_usd = cap_data.salary_cap
            if value_pct is not None:
                projected_aav_usd = int(round(value_pct / 100 * projected_cap_usd))
            if value_lo_pct is not None:
                projected_aav_lo_usd = int(round(value_lo_pct / 100 * projected_cap_usd))
            if value_hi_pct is not None:
                projected_aav_hi_usd = int(round(value_hi_pct / 100 * projected_cap_usd))

    if value_pct is None:
        return ExtensionDecision(
            player_id=player_id,
            eligible=True,
            ineligible_reason=None,
            value_season=LATEST_SEASON,
            value_pct=None,
            value_lo_pct=None,
            value_hi_pct=None,
            current_pay_pct=current_pay_pct,
            final_contract_season=final_contract_season,
            entering_season=entering,
            projected_aav_usd=None,
            projected_aav_lo_usd=None,
            projected_aav_hi_usd=None,
            projected_cap_usd=projected_cap_usd,
            gap_pct=None,
            verdict="No model value",
            tone="neutral",
            rationale="No loaded stats season to value this player; decision cannot be modeled.",
            trajectory_note=trajectory_note,
            caveat=CAVEAT,
        )

    gap_pct = round(value_pct - current_pay_pct, 2) if current_pay_pct is not None else None

    if current_pay_pct is None:
        verdict, tone = "Extend at market", "neutral"
        rationale = "No comparable guaranteed salary remaining to gap the model value against."
    elif gap_pct >= DECISION_THRESHOLD_PCT:
        verdict, tone = "Extend now", "positive"
        rationale = (
            f"Model value ({value_pct:.1f}% of cap) exceeds current pay ({current_pay_pct:.1f}%); "
            "extending now locks in below-market cost."
        )
    elif gap_pct <= -DECISION_THRESHOLD_PCT:
        verdict, tone = "Don't extend", "negative"
        rationale = (
            f"Current pay ({current_pay_pct:.1f}%) already exceeds model value ({value_pct:.1f}%); "
            "extending now would compound the overpay."
        )
    else:
        verdict, tone = "Fair — extend at market or wait", "neutral"
        rationale = "Model value and current pay are within a cap-point; either path is defensible."

    return ExtensionDecision(
        player_id=player_id,
        eligible=True,
        ineligible_reason=None,
        value_season=LATEST_SEASON,
        value_pct=round(value_pct, 2),
        value_lo_pct=round(value_lo_pct, 2) if value_lo_pct is not None else None,
        value_hi_pct=round(value_hi_pct, 2) if value_hi_pct is not None else None,
        current_pay_pct=current_pay_pct,
        final_contract_season=final_contract_season,
        entering_season=entering,
        projected_aav_usd=projected_aav_usd,
        projected_aav_lo_usd=projected_aav_lo_usd,
        projected_aav_hi_usd=projected_aav_hi_usd,
        projected_cap_usd=projected_cap_usd,
        gap_pct=gap_pct,
        verdict=verdict,
        tone=tone,
        rationale=rationale,
        trajectory_note=trajectory_note,
        caveat=CAVEAT,
    )
