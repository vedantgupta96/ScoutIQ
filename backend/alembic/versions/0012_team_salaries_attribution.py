"""add player_team_salaries and salary_decision_attributions

Revision ID: 0012_team_salaries_attribution
Revises: 0011_season_source_external_ids
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_team_salaries_attribution"
down_revision: Union[str, None] = "0011_season_source_external_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_team_salaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("team_name", sa.String(length=64), nullable=False),
        sa.Column("team_abbr", sa.String(length=8), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("row_ordinal", sa.Integer(), nullable=False),
        sa.Column("salary", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        sa.Column("source_fetched_on", sa.Date(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id", "season", "source", "team_name", "row_ordinal", name="uq_player_team_salary_row"
        ),
    )
    op.create_index(op.f("ix_player_team_salaries_player_id"), "player_team_salaries", ["player_id"], unique=False)
    op.create_index(op.f("ix_player_team_salaries_season"), "player_team_salaries", ["season"], unique=False)
    op.create_table(
        "salary_decision_attributions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("signing_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("team_name", sa.String(length=64), nullable=True),
        sa.Column("first_paid_season", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=True),
        sa.Column("team_salary_id", sa.Integer(), nullable=True),
        sa.Column("salary", sa.BigInteger(), nullable=True),
        sa.Column("rule_version", sa.String(length=16), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        sa.Column("source_fetched_on", sa.Date(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.ForeignKeyConstraint(["team_salary_id"], ["player_team_salaries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_salary_decision_attribution_event"),
    )
    op.create_index(
        op.f("ix_salary_decision_attributions_player_id"), "salary_decision_attributions", ["player_id"], unique=False
    )
    op.create_index(
        op.f("ix_salary_decision_attributions_first_paid_season"),
        "salary_decision_attributions",
        ["first_paid_season"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_salary_decision_attributions_first_paid_season"), table_name="salary_decision_attributions")
    op.drop_index(op.f("ix_salary_decision_attributions_player_id"), table_name="salary_decision_attributions")
    op.drop_table("salary_decision_attributions")
    op.drop_index(op.f("ix_player_team_salaries_season"), table_name="player_team_salaries")
    op.drop_index(op.f("ix_player_team_salaries_player_id"), table_name="player_team_salaries")
    op.drop_table("player_team_salaries")
