"""add player_rationales table

Revision ID: 0006_player_rationales
Revises: 0005_scout_reports
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_player_rationales"
down_revision: Union[str, None] = "0005_scout_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_rationales",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("consensus_mode", sa.String(length=16), nullable=False),
        sa.Column("rationale_text", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("est_cost_usd", sa.Numeric(precision=10, scale=6)),
        sa.Column("model", sa.String(length=48)),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("player_id", "consensus_mode", name="uq_player_rationale_mode"),
    )
    op.create_index("ix_player_rationales_player_id", "player_rationales", ["player_id"])


def downgrade() -> None:
    op.drop_index("ix_player_rationales_player_id", table_name="player_rationales")
    op.drop_table("player_rationales")
