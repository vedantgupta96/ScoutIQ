"""add contracts and contract_years tables

Revision ID: 0002_contracts
Revises: 0001_initial
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_contracts"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("team_id", sa.BigInteger(), sa.ForeignKey("teams.team_id")),
        sa.Column("season_start", sa.String(length=7), nullable=False),
        sa.Column("years", sa.Integer(), nullable=False),
        sa.Column("total_value", sa.BigInteger()),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="spotrac"),
        sa.Column("scraped_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("player_id", "season_start", name="uq_contract_player_start"),
    )
    op.create_index("ix_contracts_player_id", "contracts", ["player_id"])

    op.create_table(
        "contract_years",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("aav", sa.BigInteger()),
        sa.Column("cap_pct", sa.Numeric(precision=6, scale=4)),
        sa.Column("is_guaranteed", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_player_option", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_team_option", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("contract_id", "season", name="uq_contract_year"),
    )
    op.create_index("ix_contract_years_contract_id", "contract_years", ["contract_id"])
    op.create_index("ix_contract_years_season", "contract_years", ["season"])


def downgrade() -> None:
    op.drop_index("ix_contract_years_season", table_name="contract_years")
    op.drop_index("ix_contract_years_contract_id", table_name="contract_years")
    op.drop_table("contract_years")
    op.drop_index("ix_contracts_player_id", table_name="contracts")
    op.drop_table("contracts")
