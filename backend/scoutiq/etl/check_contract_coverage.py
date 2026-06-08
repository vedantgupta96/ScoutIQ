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
from scoutiq.models import Contract, Player, PlayerSalary, PlayerSeason, Team


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


def audit(season: str, min_gp: int, min_minutes: int) -> list[CoverageRow]:
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
            has_contract = session.scalars(
                select(Contract.player_id).where(Contract.player_id == player.player_id)
            ).first() is not None
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
                    )
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=settings.CURRENT_SEASON)
    parser.add_argument("--min-gp", type=int, default=20)
    parser.add_argument("--min-minutes", type=int, default=600)
    parser.add_argument("--fail", action="store_true", help="exit non-zero when gaps exist")
    args = parser.parse_args()

    rows = audit(args.season, args.min_gp, args.min_minutes)
    missing_salary = [row for row in rows if not row.has_salary]
    missing_contract = [row for row in rows if not row.has_contract]

    print(
        f"contract coverage {args.season}: "
        f"missing_salary={len(missing_salary)} missing_contract={len(missing_contract)}"
    )
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
            f"missing={','.join(gaps)}"
        )

    if args.fail and rows:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
