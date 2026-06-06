"""initial schema: extension + core data-layer tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector enabled now so Phase-2 embedding columns need no extra migration ceremony.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "teams",
        sa.Column("team_id", sa.BigInteger(), primary_key=True),
        sa.Column("abbreviation", sa.String(length=8)),
        sa.Column("name", sa.String(length=64)),
        sa.Column("conference", sa.String(length=16)),
        sa.Column("division", sa.String(length=32)),
    )

    op.create_table(
        "players",
        sa.Column("player_id", sa.BigInteger(), primary_key=True),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("position", sa.String(length=16)),
    )
    op.create_index("ix_players_full_name", "players", ["full_name"])

    op.create_table(
        "player_xref",
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), primary_key=True),
        sa.Column("bbref_slug", sa.String(length=16)),
        sa.Column("verified_name", sa.String(length=128)),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unverified"),
    )
    op.create_index("ix_player_xref_bbref_slug", "player_xref", ["bbref_slug"])

    op.create_table(
        "player_seasons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("team_id", sa.BigInteger(), sa.ForeignKey("teams.team_id")),
        sa.Column("age", sa.Integer()),
        sa.Column("gp", sa.Integer()),
        sa.Column("minutes", sa.Numeric()),
        sa.Column("box", postgresql.JSONB()),
        sa.Column("advanced", postgresql.JSONB()),
        sa.UniqueConstraint("player_id", "season", name="uq_player_season"),
    )
    op.create_index("ix_player_seasons_player_id", "player_seasons", ["player_id"])
    op.create_index("ix_player_seasons_season", "player_seasons", ["season"])

    op.create_table(
        "player_salaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.player_id"), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("salary", sa.BigInteger()),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="bbref"),
        sa.UniqueConstraint("player_id", "season", name="uq_player_salary_season"),
    )
    op.create_index("ix_player_salaries_player_id", "player_salaries", ["player_id"])
    op.create_index("ix_player_salaries_season", "player_salaries", ["season"])

    op.create_table(
        "cap_constants",
        sa.Column("season", sa.String(length=7), primary_key=True),
        sa.Column("salary_cap", sa.BigInteger()),
        sa.Column("tax_line", sa.BigInteger()),
        sa.Column("first_apron", sa.BigInteger()),
        sa.Column("second_apron", sa.BigInteger()),
        sa.Column("max_25", sa.BigInteger()),
        sa.Column("max_30", sa.BigInteger()),
        sa.Column("max_35", sa.BigInteger()),
    )


def downgrade() -> None:
    op.drop_table("cap_constants")
    op.drop_table("player_salaries")
    op.drop_table("player_seasons")
    op.drop_table("player_xref")
    op.drop_index("ix_players_full_name", table_name="players")
    op.drop_table("players")
    op.drop_table("teams")
