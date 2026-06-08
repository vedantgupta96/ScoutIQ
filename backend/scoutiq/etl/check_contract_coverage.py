"""Audit forward contract/salary coverage for a model season.

This is the contract-side counterpart to `check_coverage`: it finds players who
have enough loaded production for the valuation UI but lack the pay data needed
to compute value-vs-pay gaps.

Usage:
    python -m scoutiq.etl.check_contract_coverage
    python -m scoutiq.etl.check_contract_coverage --season 2025-26 --min-gp 20 --min-minutes 600
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import select

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import Contract, ContractYear, Player, PlayerSalary, PlayerSeason, Team

DEFAULT_FLOOR = 1_100_000


@dataclass(frozen=True)
class CoverageRow:
    player_id: int
    full_name: str
    team: str | None
    position: str | None
    gp: int | None
    minutes: float | None
    has_salary: bool
    has_contract: bool
    reason: str
    target_aav: int | None
    contract_id: int | None


def _coverage_reason(session, player_id: int, season: str, floor: int) -> tuple[str, bool, int | None, int | None]:
    contracts = session.scalars(
        select(Contract).where(Contract.player_id == player_id).order_by(Contract.season_start.desc())
    ).all()
    if not contracts:
        return "no_contract", False, None, None

    year_rows = session.execute(
        select(ContractYear, Contract)
        .join(Contract, Contract.id == ContractYear.contract_id)
        .where(Contract.player_id == player_id)
        .where(ContractYear.season == season)
        .order_by(Contract.season_start.desc(), Contract.scraped_at.desc().nulls_last())
    ).all()
    if not year_rows:
        return "no_contract_year_for_season", True, None, contracts[0].id

    year, contract = year_rows[0]
    if year.aav is None:
        return "contract_missing_aav", True, None, contract.id
    if year.aav < floor:
        return "contract_below_floor", True, int(year.aav), contract.id
    return "bridge_missed", True, int(year.aav), contract.id


def audit(season: str, min_gp: int, min_minutes: int, floor: int = DEFAULT_FLOOR) -> list[CoverageRow]:
    rows: list[CoverageRow] = []
    with get_session() as session:
        player_rows = session.execute(
            select(Player, PlayerSeason, Team)
            .join(PlayerSeason, PlayerSeason.player_id == Player.player_id)
            .outerjoin(Team, Team.team_id == Player.current_team_id)
            .where(PlayerSeason.season == season)
            .where(PlayerSeason.gp >= min_gp)
            .where(PlayerSeason.minutes >= min_minutes)
            .order_by(Player.full_name)
        ).all()

        for player, player_season, team in player_rows:
            has_salary = session.scalars(
                select(PlayerSalary.player_id).where(
                    PlayerSalary.player_id == player.player_id,
                    PlayerSalary.season == season,
                )
            ).first() is not None
            reason, has_contract, target_aav, contract_id = _coverage_reason(
                session,
                player.player_id,
                season,
                floor,
            )
            if not has_salary or not has_contract:
                rows.append(
                    CoverageRow(
                        player_id=player.player_id,
                        full_name=player.full_name,
                        team=team.abbreviation if team else None,
                        position=player.position,
                        gp=player_season.gp,
                        minutes=float(player_season.minutes) if player_season.minutes is not None else None,
                        has_salary=has_salary,
                        has_contract=has_contract,
                        reason=reason if not has_salary else "no_contract",
                        target_aav=target_aav,
                        contract_id=contract_id,
                    )
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=settings.CURRENT_SEASON)
    parser.add_argument("--min-gp", type=int, default=20)
    parser.add_argument("--min-minutes", type=int, default=600)
    parser.add_argument("--floor", type=int, default=DEFAULT_FLOOR)
    parser.add_argument("--fail", action="store_true", help="exit non-zero when gaps exist")
    args = parser.parse_args()

    rows = audit(args.season, args.min_gp, args.min_minutes, args.floor)
    missing_salary = [row for row in rows if not row.has_salary]
    missing_contract = [row for row in rows if not row.has_contract]
    reason_counts = {
        reason: sum(1 for row in rows if row.reason == reason)
        for reason in sorted({row.reason for row in rows})
    }

    print(
        f"contract coverage {args.season}: "
        f"missing_salary={len(missing_salary)} missing_contract={len(missing_contract)}"
    )
    print("reasons: " + " ".join(f"{reason}={count}" for reason, count in reason_counts.items()))
    for row in rows[:100]:
        gaps = []
        if not row.has_salary:
            gaps.append("salary")
        if not row.has_contract:
            gaps.append("contract")
        minutes = f"{row.minutes:.0f}" if row.minutes is not None else "-"
        print(
            f"{row.player_id}\t{row.full_name}\t{row.team or '-'}\t{row.position or '-'}\t"
            f"gp={row.gp}\tmin={minutes}\t"
            f"missing={','.join(gaps)}\treason={row.reason}\t"
            f"aav={row.target_aav if row.target_aav is not None else '-'}\tcontract={row.contract_id or '-'}"
        )

    if args.fail and rows:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
