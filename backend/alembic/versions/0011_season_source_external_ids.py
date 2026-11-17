"""add player_seasons.source/source_fetched_at and player_external_ids

Revision ID: 0011_season_source_external_ids
Revises: 0010_player_two_way
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_season_source_external_ids"
down_revision: Union[str, None] = "0010_player_two_way"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("player_seasons", sa.Column("source", sa.String(length=32), nullable=True))
    op.add_column(
        "player_seasons",
        sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "player_external_ids",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("match_basis", sa.String(length=96), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_player_external_id_source_external"),
        sa.UniqueConstraint("source", "player_id", name="uq_player_external_id_source_player"),
    )
    op.create_index(op.f("ix_player_external_ids_player_id"), "player_external_ids", ["player_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_player_external_ids_player_id"), table_name="player_external_ids")
    op.drop_table("player_external_ids")
    op.drop_column("player_seasons", "source_fetched_at")
    op.drop_column("player_seasons", "source")
