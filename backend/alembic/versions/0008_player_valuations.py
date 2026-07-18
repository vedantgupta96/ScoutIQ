"""add player_valuations table (precomputed model outputs)

Revision ID: 0008_player_valuations
Revises: 0007_free_agent_rights
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_player_valuations"
down_revision: Union[str, None] = "0007_free_agent_rights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_valuations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("value_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("lo_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("hi_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("actual_usd", sa.BigInteger()),
        sa.Column("actual_pct", sa.Numeric(6, 2)),
        sa.Column("gap_pct", sa.Numeric(6, 2)),
        sa.Column("qualified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verdict_label", sa.String(length=48), nullable=False),
        sa.Column("verdict_tone", sa.String(length=12), nullable=False),
        sa.Column("caution_flags", JSONB),
        sa.Column("caveat", sa.String()),
        sa.Column("stats", JSONB),
        sa.Column("features", JSONB),
        sa.Column("model_version", sa.String(length=48), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("player_id", "season", name="uq_player_valuation_season"),
    )
    op.create_index("ix_player_valuations_player_id", "player_valuations", ["player_id"])
    op.create_index("ix_player_valuations_season", "player_valuations", ["season"])
    op.create_index("ix_player_valuations_season_gap", "player_valuations", ["season", "gap_pct"])
    op.create_index("ix_player_valuations_season_value", "player_valuations", ["season", "value_pct"])


def downgrade() -> None:
    op.drop_index("ix_player_valuations_season_value", table_name="player_valuations")
    op.drop_index("ix_player_valuations_season_gap", table_name="player_valuations")
    op.drop_index("ix_player_valuations_season", table_name="player_valuations")
    op.drop_index("ix_player_valuations_player_id", table_name="player_valuations")
    op.drop_table("player_valuations")
