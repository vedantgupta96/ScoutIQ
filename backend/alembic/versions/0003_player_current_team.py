"""add current-team fields to players

Revision ID: 0003_player_current_team
Revises: 0002_contracts
Create Date: 2026-06-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_player_current_team"
down_revision: Union[str, None] = "0002_contracts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("players", sa.Column("current_team_id", sa.BigInteger(), nullable=True))
    op.add_column("players", sa.Column("current_team_source", sa.String(length=64), nullable=True))
    op.add_column("players", sa.Column("current_team_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_players_current_team_id_teams",
        "players",
        "teams",
        ["current_team_id"],
        ["team_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_players_current_team_id_teams", "players", type_="foreignkey")
    op.drop_column("players", "current_team_updated_at")
    op.drop_column("players", "current_team_source")
    op.drop_column("players", "current_team_id")
