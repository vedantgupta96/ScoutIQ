"""add players.is_two_way (two-way contract flag for roster-count legality)

Revision ID: 0010_player_two_way
Revises: 0009_draft_picks
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_player_two_way"
down_revision: Union[str, None] = "0009_draft_picks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("is_two_way", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("players", "is_two_way")
