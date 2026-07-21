"""add draft_picks table (tradable pick window for the Trade lab)

Revision ID: 0009_draft_picks
Revises: 0008_player_valuations
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_draft_picks"
down_revision: Union[str, None] = "0008_player_valuations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_picks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("draft_year", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("original_team_id", sa.BigInteger(), sa.ForeignKey("teams.team_id"), nullable=False),
        sa.Column("current_team_id", sa.BigInteger(), sa.ForeignKey("teams.team_id"), nullable=False),
        sa.Column("protected_top", sa.Integer()),
        sa.Column("swap_rights_team_id", sa.BigInteger(), sa.ForeignKey("teams.team_id")),
        sa.Column("converts_to", sa.String(length=128)),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="default-ownership"),
        sa.Column("source_url", sa.String(length=512)),
        sa.Column("notes", sa.String(length=256)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("draft_year", "round", "original_team_id", name="uq_draft_pick_identity"),
    )
    op.create_index("ix_draft_picks_current_team_id", "draft_picks", ["current_team_id"])
    op.create_index("ix_draft_picks_owner_year", "draft_picks", ["current_team_id", "draft_year"])


def downgrade() -> None:
    op.drop_index("ix_draft_picks_owner_year", table_name="draft_picks")
    op.drop_index("ix_draft_picks_current_team_id", table_name="draft_picks")
    op.drop_table("draft_picks")
