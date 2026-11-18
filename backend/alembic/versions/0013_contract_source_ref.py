"""add contracts.source_ref

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


def downgrade() -> None:
    op.drop_column("contracts", "source_ref")
