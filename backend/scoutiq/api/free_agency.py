"""Free-agency logic — pure, DB-free helpers (unit-testable, mirrors cap_simulator.py).

Free-agency status is *derived* from existing contract data rather than persisted: the
Spotrac scrape discards explicit UFA/RFA rows, so we infer when a player reaches the market
from their last contract season plus that year's option flags. The DB orchestration
(pool assembly, valuation, projected team room) lives in routers/free_agency.py — this module
holds only the season math and the value-vs-cost verdict logic so it can be tested without a
database or the model artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scoutiq.api.season import is_valid_season, next_season

# How a player reaches free agency in the summer after their final contract year.
FA_EXPIRING = "expiring"            # contract simply ends → UFA/RFA
FA_PLAYER_OPTION = "player-option"  # final year is a player option → player may opt out
FA_TEAM_OPTION = "team-option"      # final year is a team option → team may decline
FA_TYPES = (FA_EXPIRING, FA_PLAYER_OPTION, FA_TEAM_OPTION)

# RFA heuristic: players with fewer than four completed NBA seasons are typically
# restricted free agents (subject to a qualifying offer). Flagged as an estimate because
# service time is inferred from loaded stat seasons, not tracked contractually.
RFA_MAX_SEASONS = 4

# A value-vs-cost gap (in % of cap) beyond which a decision is a clear call rather than a
# toss-up. Matches the bargain/overpay threshold used by the team cap sheet.
DECISION_THRESHOLD_PCT = 1.0

VerdictTone = Literal["positive", "negative", "neutral"]


def expiry_season(season_start: str, years: int) -> str | None:
    """Last season of a contract: `season_start` advanced `years - 1` times.

    Prefer deriving expiry from the actual max contract-year season when rows are available;
    this is the fallback when only the summary (season_start + years) is known.
    """
    if not is_valid_season(season_start) or years < 1:
        return None
    season = season_start
    for _ in range(years - 1):
        season = next_season(season)
        if season is None:
            return None
    return season


def entering_season(last_contract_season: str) -> str | None:
    """The season a player would be on a new deal after their final contract year."""
    return next_season(last_contract_season)


def free_agent_type(is_player_option: bool, is_team_option: bool) -> str:
    """Classify how a player reaches the market based on their final contract year's flags."""
    if is_player_option:
        return FA_PLAYER_OPTION
    if is_team_option:
        return FA_TEAM_OPTION
    return FA_EXPIRING


def rfa_estimate(seasons_played: int) -> bool:
    """Heuristic RFA-eligibility: fewer than RFA_MAX_SEASONS completed seasons ⇒ restricted."""
    return seasons_played < RFA_MAX_SEASONS


@dataclass
class OptionVerdict:
    """A pick-up / decline / opt-out recommendation for one option year.

    `verdict` is phrased from the deciding party's perspective; `tone` is always from the
    value lens (positive = bargain relative to the option salary) so the UI can colour it
    consistently regardless of who holds the option.
    """
    fa_type: str
    deciding_party: str          # "player" | "team"
    option_cap_pct: float        # what the option pays, as % of cap
    value_pct: float | None      # model production-implied value, as % of cap
    gap_pct: float | None        # value_pct - option_cap_pct (positive = worth more than it pays)
    verdict: str
    tone: VerdictTone
    rationale: str


def option_decision(
    value_pct: float | None,
    option_cap_pct: float,
    fa_type: str,
    *,
    threshold: float = DECISION_THRESHOLD_PCT,
) -> OptionVerdict:
    """Compare model value to the option salary and recommend a decision.

    Player option (player decides): worth more than the option ⇒ decline and test the market;
    worth less ⇒ opt in and bank the guaranteed money.
    Team option (team decides): worth more than the option ⇒ exercise (bargain); worth less ⇒
    decline. The `value_pct` and `option_cap_pct` are both % of cap, so they compare directly.
    """
    deciding_party = "player" if fa_type == FA_PLAYER_OPTION else "team"

    if value_pct is None:
        return OptionVerdict(
            fa_type=fa_type,
            deciding_party=deciding_party,
            option_cap_pct=option_cap_pct,
            value_pct=None,
            gap_pct=None,
            verdict="No model value",
            tone="neutral",
            rationale="No loaded stats season to value this player; decision cannot be modeled.",
        )

    gap = round(value_pct - option_cap_pct, 2)

    if fa_type == FA_PLAYER_OPTION:
        if gap >= threshold:
            verdict, tone = "Decline (opt out)", "positive"
            rationale = (
                f"Model value ({value_pct:.1f}% of cap) exceeds the option salary "
                f"({option_cap_pct:.1f}%); worth testing the open market."
            )
        elif gap <= -threshold:
            verdict, tone = "Opt in", "negative"
            rationale = (
                f"Option salary ({option_cap_pct:.1f}%) exceeds model value ({value_pct:.1f}%); "
                "exercising banks above-market guaranteed money."
            )
        else:
            verdict, tone = "Toss-up (lean opt in)", "neutral"
            rationale = "Model value and option salary are within a cap-point; the guarantee tips it."
    else:  # team option
        if gap >= threshold:
            verdict, tone = "Exercise", "positive"
            rationale = (
                f"Bargain: model value ({value_pct:.1f}% of cap) exceeds the option salary "
                f"({option_cap_pct:.1f}%)."
            )
        elif gap <= -threshold:
            verdict, tone = "Decline", "negative"
            rationale = (
                f"Option salary ({option_cap_pct:.1f}%) exceeds model value ({value_pct:.1f}%); "
                "let it lapse or renegotiate."
            )
        else:
            verdict, tone = "Toss-up (lean exercise)", "neutral"
            rationale = "Model value and option salary are within a cap-point; low downside to holding."

    return OptionVerdict(
        fa_type=fa_type,
        deciding_party=deciding_party,
        option_cap_pct=round(option_cap_pct, 2),
        value_pct=round(value_pct, 2),
        gap_pct=gap,
        verdict=verdict,
        tone=tone,
        rationale=rationale,
    )
