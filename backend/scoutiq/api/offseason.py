"""Pure multi-season payroll planning helpers.

The router owns database and model access. This module only applies proposed contracts
and option removals to a season-by-season baseline so the cap math is deterministic and
unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from scoutiq.api.cap_simulator import ContractYear, SeasonCapData, TIER_ORDER, classify_tier


@dataclass(frozen=True)
class PlannedContract:
    player_id: int
    years: list[ContractYear]


@dataclass(frozen=True)
class PlannedSeason:
    season: str
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int
    is_projected_cap: bool
    baseline_payroll_usd: int
    payroll_after_usd: int
    payroll_delta_usd: int
    baseline_roster_count: int
    roster_count_after: int
    tier_before: str
    tier_after: str
    crosses_a_line: bool
    room_to_cap_after: int
    room_to_tax_after: int
    room_to_first_apron_after: int
    room_to_second_apron_after: int


def apply_plan(
    season_caps: list[SeasonCapData],
    baseline_hits_by_season: dict[str, dict[int, int]],
    contracts: list[PlannedContract],
    removed_player_ids: set[int],
) -> list[PlannedSeason]:
    """Apply proposed deals and option removals to a team's payroll baseline.

    A proposed deal replaces any baseline figure for that player from the plan's first
    season onward. This handles re-signings and option renegotiations without double-counting.
    """
    if not season_caps:
        return []

    plan_seasons = {row.season for row in season_caps}
    proposed_by_season: dict[str, dict[int, int]] = {season: {} for season in plan_seasons}
    proposed_player_ids = {contract.player_id for contract in contracts}

    for contract in contracts:
        for year in contract.years:
            if year.season in proposed_by_season:
                proposed_by_season[year.season][contract.player_id] = year.cap_hit_usd

    results: list[PlannedSeason] = []
    for cap in season_caps:
        baseline = dict(baseline_hits_by_season.get(cap.season, {}))
        after = dict(baseline)

        for player_id in removed_player_ids | proposed_player_ids:
            after.pop(player_id, None)
        after.update(proposed_by_season[cap.season])

        baseline_payroll = sum(baseline.values())
        payroll_after = sum(after.values())
        tier_before = classify_tier(
            baseline_payroll, cap.tax_line, cap.first_apron, cap.second_apron
        )
        tier_after = classify_tier(
            payroll_after, cap.tax_line, cap.first_apron, cap.second_apron
        )

        results.append(
            PlannedSeason(
                season=cap.season,
                salary_cap=cap.salary_cap,
                tax_line=cap.tax_line,
                first_apron=cap.first_apron,
                second_apron=cap.second_apron,
                is_projected_cap=cap.is_projected,
                baseline_payroll_usd=baseline_payroll,
                payroll_after_usd=payroll_after,
                payroll_delta_usd=payroll_after - baseline_payroll,
                baseline_roster_count=len(baseline),
                roster_count_after=len(after),
                tier_before=tier_before,
                tier_after=tier_after,
                crosses_a_line=TIER_ORDER.index(tier_before) != TIER_ORDER.index(tier_after),
                room_to_cap_after=cap.salary_cap - payroll_after,
                room_to_tax_after=cap.tax_line - payroll_after,
                room_to_first_apron_after=cap.first_apron - payroll_after,
                room_to_second_apron_after=cap.second_apron - payroll_after,
            )
        )

    return results
