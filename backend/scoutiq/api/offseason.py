"""Pure multi-season payroll planning helpers.

The router owns database and model access. This module only applies proposed contracts
and option removals to a season-by-season baseline so the cap math is deterministic and
unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from scoutiq.api.cap import SeasonCapData, TIER_ORDER, classify_tier, room_to_lines
from scoutiq.api.cap_simulator import ContractYear


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
    baseline_contract_payroll_usd: int
    contract_payroll_after_usd: int
    baseline_cap_holds_usd: int
    cap_holds_after_usd: int
    baseline_incomplete_roster_charges_usd: int
    incomplete_roster_charges_after_usd: int
    baseline_team_salary_player_count: int
    team_salary_player_count_after: int


ZERO_YEAR_MINIMUM_2024_25 = 1_157_153
SALARY_CAP_2024_25 = 140_588_000


def zero_year_minimum(salary_cap: int) -> int:
    """Scale the official 2024-25 zero-YOS minimum with the salary cap."""
    return round(ZERO_YEAR_MINIMUM_2024_25 * salary_cap / SALARY_CAP_2024_25)


def incomplete_roster_charge(salary_cap: int, team_salary_player_count: int) -> tuple[int, int]:
    spots = max(0, 12 - team_salary_player_count)
    return spots * zero_year_minimum(salary_cap), spots


def apply_plan(
    season_caps: list[SeasonCapData],
    baseline_hits_by_season: dict[str, dict[int, int]],
    contracts: list[PlannedContract],
    removed_player_ids: set[int],
    holds_by_season: dict[str, dict[int, int]] | None = None,
    renounced_player_ids: set[int] | None = None,
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

    holds_by_season = holds_by_season or {}
    renounced_player_ids = renounced_player_ids or set()
    results: list[PlannedSeason] = []
    for cap in season_caps:
        baseline = dict(baseline_hits_by_season.get(cap.season, {}))
        after = dict(baseline)

        for player_id in removed_player_ids | proposed_player_ids:
            after.pop(player_id, None)
        after.update(proposed_by_season[cap.season])

        baseline_holds = {pid: amount for pid, amount in holds_by_season.get(cap.season, {}).items() if pid not in baseline}
        after_holds = {pid: amount for pid, amount in baseline_holds.items() if pid not in renounced_player_ids and pid not in proposed_player_ids}
        baseline_contract_payroll = sum(baseline.values())
        contract_payroll_after = sum(after.values())
        baseline_hold_total = sum(baseline_holds.values())
        after_hold_total = sum(after_holds.values())
        baseline_count = len(baseline) + len(baseline_holds)
        after_count = len(after) + len(after_holds)
        baseline_incomplete, _ = incomplete_roster_charge(cap.salary_cap, baseline_count)
        after_incomplete, _ = incomplete_roster_charge(cap.salary_cap, after_count)
        baseline_payroll = baseline_contract_payroll + baseline_hold_total + baseline_incomplete
        payroll_after = contract_payroll_after + after_hold_total + after_incomplete
        tier_before = classify_tier(
            baseline_payroll, cap.tax_line, cap.first_apron, cap.second_apron
        )
        tier_after = classify_tier(
            payroll_after, cap.tax_line, cap.first_apron, cap.second_apron
        )
        rooms = room_to_lines(
            payroll_after,
            salary_cap=cap.salary_cap,
            tax_line=cap.tax_line,
            first_apron=cap.first_apron,
            second_apron=cap.second_apron,
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
                room_to_cap_after=rooms.room_to_cap,
                room_to_tax_after=rooms.room_to_tax,
                room_to_first_apron_after=rooms.room_to_first_apron,
                room_to_second_apron_after=rooms.room_to_second_apron,
                baseline_contract_payroll_usd=baseline_contract_payroll,
                contract_payroll_after_usd=contract_payroll_after,
                baseline_cap_holds_usd=baseline_hold_total,
                cap_holds_after_usd=after_hold_total,
                baseline_incomplete_roster_charges_usd=baseline_incomplete,
                incomplete_roster_charges_after_usd=after_incomplete,
                baseline_team_salary_player_count=baseline_count,
                team_salary_player_count_after=after_count,
            )
        )

    return results
