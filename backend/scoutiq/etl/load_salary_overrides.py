"""Apply tracked salary overrides for source-confirmed edge cases.

This is intentionally small and auditable. It handles current-season players
whose primary contract sources have a contract row but no usable season amount.
Overrides update the matching contract_years.aav row and upsert player_salaries
so valuation coverage stays complete and reproducible.

Usage:
    python -m scoutiq.etl.load_salary_overrides
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.models import Contract, ContractYear, Player, PlayerSalary

DEFAULT_PATH = settings.DATA_DIR / "current_salary_overrides.csv"


def _read_rows(path: Path, season: str) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [row for row in rows if row["season"] == season]


def apply_overrides(path: Path = DEFAULT_PATH, season: str = settings.CURRENT_SEASON) -> tuple[int, int]:
    rows = _read_rows(path, season)
    updated_contract_years = 0
    upserted_salaries = 0
    with get_session() as session:
        for row in rows:
            player_id = int(row["player_id"])
            salary = int(row["salary"])
            expected_name = row["full_name"]
            actual_name = session.scalar(select(Player.full_name).where(Player.player_id == player_id))
            if actual_name != expected_name:
                raise RuntimeError(f"override name mismatch for {player_id}: expected {expected_name}, got {actual_name}")

            contract_year_ids = session.scalars(
                select(ContractYear.id)
                .join(Contract, Contract.id == ContractYear.contract_id)
                .where(Contract.player_id == player_id)
                .where(ContractYear.season == season)
            ).all()
            if not contract_year_ids:
                raise RuntimeError(f"no contract year for override {player_id} {expected_name} {season}")

            result = session.execute(
                update(ContractYear)
                .where(ContractYear.id.in_(contract_year_ids))
                .where(ContractYear.aav.is_(None))
                .values(aav=salary)
            )
            updated_contract_years += result.rowcount or 0

            stmt = insert(PlayerSalary).values(
                player_id=player_id,
                season=season,
                salary=salary,
                source=f"override_{row['source']}",
            )
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_player_salary_season",
                    set_={"salary": stmt.excluded["salary"], "source": stmt.excluded["source"]},
                    where=(PlayerSalary.source != "bbref"),
                )
            )
            upserted_salaries += 1
    return updated_contract_years, upserted_salaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=settings.CURRENT_SEASON)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    contract_years, salaries = apply_overrides(path=args.path, season=args.season)
    print(
        f"salary overrides {args.season}: "
        f"updated_contract_years={contract_years} upserted_salaries={salaries}"
    )
