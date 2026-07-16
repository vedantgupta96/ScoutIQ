"""add free_agent_rights table

Revision ID: 0007_free_agent_rights
Revises: 0006_player_rationales
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_free_agent_rights"
down_revision: Union[str, None] = "0006_player_rationales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "free_agent_rights",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("entering_season", sa.String(length=7), nullable=False),
        sa.Column("rights_team_id", sa.BigInteger(), sa.ForeignKey("teams.team_id")),
        sa.Column("fa_status", sa.String(length=8)),
        sa.Column("bird_rights", sa.String(length=16)),
        sa.Column("qualifying_offer_usd", sa.BigInteger()),
        sa.Column("cap_hold_usd", sa.BigInteger()),
        sa.Column("previous_aav_usd", sa.BigInteger()),
        sa.Column("source_player_id", sa.String(length=32)),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="spotrac"),
        sa.Column("source_url", sa.String(length=512)),
        sa.Column("scraped_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("player_id", "entering_season", name="uq_free_agent_right_player_season"),
    )
    op.create_index("ix_free_agent_rights_player_id", "free_agent_rights", ["player_id"])
    op.create_index("ix_free_agent_rights_rights_team_id", "free_agent_rights", ["rights_team_id"])
    op.create_index("ix_free_agent_rights_season_team", "free_agent_rights", ["entering_season", "rights_team_id"])


def downgrade() -> None:
    op.drop_index("ix_free_agent_rights_season_team", table_name="free_agent_rights")
    op.drop_index("ix_free_agent_rights_rights_team_id", table_name="free_agent_rights")
    op.drop_index("ix_free_agent_rights_player_id", table_name="free_agent_rights")
    op.drop_table("free_agent_rights")
