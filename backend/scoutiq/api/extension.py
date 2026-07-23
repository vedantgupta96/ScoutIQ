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
from scoutiq.api.valuation import value_player_detail, value_players
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


def extension_verdict(value_pct: float, current_pay_pct: float | None) -> tuple[str, str, str, float | None]:
    """(verdict, tone, rationale, gap_pct) comparing model value to current pay. value_pct must be non-None."""
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

    return verdict, tone, rationale, gap_pct


def _extension_eligibility(
    year_rows: list[ContractYear],
) -> tuple[bool, str | None, float | None, str | None]:
    """(eligible, ineligible_reason, current_pay_pct, final_contract_season) from a contract's
    year rows. Eligible requires a guaranteed (non-option) year after LATEST_SEASON;
    current_pay_pct is that year's cap_pct (Decimal-coerced). Shared by decide_extension and
    batch_extension_summaries so the two rules cannot diverge."""
    all_seasons = [row.season for row in year_rows]
    final_contract_season = max(all_seasons) if all_seasons else None
    remaining = [row for row in year_rows if row.season > LATEST_SEASON]
    guaranteed_remaining = [row for row in remaining if not (row.is_player_option or row.is_team_option)]

    if not remaining:
        return False, (
            "No contract years remain after the current season (impending free agent — "
            "see the Free Agency board)."
        ), None, final_contract_season

    if not guaranteed_remaining:
        return False, (
            "Only option years remain; handled as an option decision, not an extension."
        ), None, final_contract_season

    last_guaranteed = guaranteed_remaining[-1]
    current_pay_pct = None
    if last_guaranteed.cap_pct is not None:
        # cap_pct is a SQLAlchemy Numeric → Decimal on live rows; coerce so it can be
        # arithmetic-combined with the float value_pct below (documented Decimal gotcha).
        current_pay_pct = round(float(last_guaranteed.cap_pct) * 100, 2)
    return True, None, current_pay_pct, final_contract_season


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

    eligible, ineligible_reason, current_pay_pct, final_contract_season = _extension_eligibility(year_rows)
    entering = next_season(final_contract_season) if final_contract_season else None

    try:
        valuation, features, attribution = value_player_detail(db, player_id, LATEST_SEASON)
        value_pct, value_lo_pct, value_hi_pct = valuation.value_pct, valuation.lo_pct, valuation.hi_pct
    except LookupError:
        value_pct = value_lo_pct = value_hi_pct = None
        attribution = None

    trajectory_note = _trajectory_note(attribution)

    if not eligible:
        return ExtensionDecision(
            player_id=player_id,
            eligible=False,
            ineligible_reason=ineligible_reason,
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

    verdict, tone, rationale, gap_pct = extension_verdict(value_pct, current_pay_pct)

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


@dataclass
class ExtensionCandidate:
    player_id: int
    value_pct: float
    current_pay_pct: float
    gap_pct: float
    verdict: str
    tone: str
    final_contract_season: str | None


def rank_extension_candidates(db, *, limit: int = 30) -> list[ExtensionCandidate]:
    """Rostered, extension-eligible players ranked by extend-now value gap (descending)."""
    contracts = db.scalars(
        select(Contract)
        .distinct(Contract.player_id)
        .order_by(Contract.player_id, desc(Contract.season_start), desc(Contract.scraped_at))
    ).all()
    by_contract_id = {c.id: c for c in contracts}
    if not by_contract_id:
        return []
    player_id_by_contract = {c.id: c.player_id for c in contracts}

    rostered = set(
        db.scalars(select(Player.player_id).where(Player.current_team_id.isnot(None))).all()
    )
    by_contract_id = {
        cid: c for cid, c in by_contract_id.items() if player_id_by_contract[cid] in rostered
    }
    if not by_contract_id:
        return []

    years_by_contract: dict[int, list[ContractYear]] = {}
    for cy in db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id.in_(by_contract_id.keys()))
        .order_by(ContractYear.contract_id, ContractYear.season)
    ).all():
        years_by_contract.setdefault(cy.contract_id, []).append(cy)

    eligible: dict[int, dict] = {}
    for cid, years in years_by_contract.items():
        remaining = [cy for cy in years if cy.season > LATEST_SEASON]
        guaranteed_remaining = [
            cy for cy in remaining if not (cy.is_player_option or cy.is_team_option)
        ]
        if not guaranteed_remaining:
            continue
        last_guaranteed = guaranteed_remaining[-1]
        if last_guaranteed.cap_pct is None:
            continue
        current_pay_pct = round(float(last_guaranteed.cap_pct) * 100, 2)
        player_id = player_id_by_contract[cid]
        final_contract_season = max(cy.season for cy in years)
        eligible[player_id] = {
            "current_pay_pct": current_pay_pct,
            "final_contract_season": final_contract_season,
        }

    if not eligible:
        return []

    valuations = value_players(db, [(pid, LATEST_SEASON) for pid in eligible])

    candidates: list[ExtensionCandidate] = []
    for player_id, info in eligible.items():
        val = valuations.get((player_id, LATEST_SEASON))
        if val is None:
            continue
        value_pct = val.value_pct
        current_pay_pct = info["current_pay_pct"]
        verdict, tone, _rationale, gap_pct = extension_verdict(value_pct, current_pay_pct)
        candidates.append(
            ExtensionCandidate(
                player_id=player_id,
                value_pct=value_pct,
                current_pay_pct=current_pay_pct,
                gap_pct=gap_pct,
                verdict=verdict,
                tone=tone,
                final_contract_season=info["final_contract_season"],
            )
        )

    candidates.sort(key=lambda c: c.gap_pct, reverse=True)
    return candidates[:limit]


@dataclass
class ExtensionSummary:
    player_id: int
    eligible: bool
    has_model_value: bool
    value_pct: float | None
    current_pay_pct: float | None
    gap_pct: float | None
    verdict: str | None
    tone: str | None
    final_contract_season: str | None


def batch_extension_summaries(db, player_ids: list[int]) -> dict[int, ExtensionSummary]:
    """Batched extension eligibility + verdict for a whole roster: one contracts query, one
    contract-years query, and one value_players call for the eligible subset — no per-player
    round trips. Eligibility and current_pay_pct use _extension_eligibility, the same rule
    decide_extension applies, so the two cannot diverge. A missing model artifact degrades
    every player to has_model_value=False rather than raising (ADR-0001); eligibility and pay
    are contract facts and stay populated regardless."""
    if not player_ids:
        return {}

    contracts = db.scalars(
        select(Contract)
        .where(Contract.player_id.in_(player_ids))
        .distinct(Contract.player_id)
        .order_by(Contract.player_id, desc(Contract.season_start), desc(Contract.scraped_at))
    ).all()
    contract_by_player = {c.player_id: c for c in contracts}
    if not contract_by_player:
        return {}

    years_by_contract: dict[int, list[ContractYear]] = {}
    for cy in db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id.in_([c.id for c in contracts]))
        .order_by(ContractYear.contract_id, ContractYear.season)
    ).all():
        years_by_contract.setdefault(cy.contract_id, []).append(cy)

    eligibility_by_player = {
        player_id: _extension_eligibility(years_by_contract.get(contract.id, []))
        for player_id, contract in contract_by_player.items()
    }
    eligible_ids = [pid for pid, elig in eligibility_by_player.items() if elig[0]]

    try:
        valuations = value_players(db, [(pid, LATEST_SEASON) for pid in eligible_ids])
    except FileNotFoundError:
        valuations = {}

    summaries: dict[int, ExtensionSummary] = {}
    for player_id, (eligible, _reason, current_pay_pct, final_contract_season) in eligibility_by_player.items():
        val = valuations.get((player_id, LATEST_SEASON))
        has_model_value = val is not None
        verdict = tone = gap_pct = None
        if eligible and has_model_value:
            verdict, tone, _rationale, gap_pct = extension_verdict(val.value_pct, current_pay_pct)
        summaries[player_id] = ExtensionSummary(
            player_id=player_id,
            eligible=eligible,
            has_model_value=has_model_value,
            value_pct=round(val.value_pct, 2) if val is not None else None,
            current_pay_pct=current_pay_pct,
            gap_pct=gap_pct,
            verdict=verdict,
            tone=tone,
            final_contract_season=final_contract_season,
        )
    return summaries
