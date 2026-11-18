"""contracts.source_ref, contracts.remaining_guaranteed_usd, nullable contract_years.is_guaranteed

Adds snapshot ownership (contracts.source_ref), the source-reported remaining guaranteed total
(contracts.remaining_guaranteed_usd), and lets contract_years.is_guaranteed be NULL (guarantee unknown;
false stays reserved for confirmed non-guaranteed pay).

Revision ID: 0013_contract_source_ref
Revises: 0012_team_salaries_attribution
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_contract_source_ref"
down_revision: Union[str, None] = "0012_team_salaries_attribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contracts", sa.Column("source_ref", sa.String(length=128), nullable=True))
    op.add_column("contracts", sa.Column("remaining_guaranteed_usd", sa.BigInteger(), nullable=True))
    op.alter_column(
        "contract_years",
        "is_guaranteed",
        existing_type=sa.Boolean(),
        nullable=True,
        existing_server_default=sa.text("true"),
    )


def downgrade() -> None:
    unknown = op.get_bind().execute(sa.text("SELECT count(*) FROM contract_years WHERE is_guaranteed IS NULL")).scalar()
    if unknown:
        raise RuntimeError(
            f"{unknown} contract_years rows have NULL is_guaranteed; roll back the sportsref apply first"
        )
    op.alter_column(
        "contract_years",
        "is_guaranteed",
        existing_type=sa.Boolean(),
        nullable=False,
        existing_server_default=sa.text("true"),
    )
    op.drop_column("contracts", "remaining_guaranteed_usd")
    op.drop_column("contracts", "source_ref")
