"""add scout_reports and player_ratings tables

Revision ID: 0005_scout_reports
Revises: 0004_hot_path_indexes
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_scout_reports"
down_revision: Union[str, None] = "0004_hot_path_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scout_reports",
        sa.Column("report_id", sa.String(length=64), primary_key=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("source_label", sa.String(length=64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_scout_reports_player_id", "scout_reports", ["player_id"])

    op.create_table(
        "player_ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(length=64), sa.ForeignKey("scout_reports.report_id"), nullable=False),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("trait", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=False),
        sa.UniqueConstraint("report_id", "trait", name="uq_player_rating_report_trait"),
    )
    op.create_index("ix_player_ratings_report_id", "player_ratings", ["report_id"])
    op.create_index("ix_player_ratings_player_id", "player_ratings", ["player_id"])


def downgrade() -> None:
    op.drop_index("ix_player_ratings_player_id", table_name="player_ratings")
    op.drop_index("ix_player_ratings_report_id", table_name="player_ratings")
    op.drop_table("player_ratings")
    op.drop_index("ix_scout_reports_player_id", table_name="scout_reports")
    op.drop_table("scout_reports")
