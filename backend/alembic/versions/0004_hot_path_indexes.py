"""add indexes for API hot paths

Revision ID: 0004_hot_path_indexes
Revises: 0003_player_current_team
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_hot_path_indexes"
down_revision: Union[str, None] = "0003_player_current_team"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_players_current_team_id",
            "players",
            ["current_team_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_player_seasons_season_minutes",
            "player_seasons",
            ["season", "minutes"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_contracts_player_latest",
            "contracts",
            ["player_id", "season_start", "scraped_at"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_contract_years_season_contract_id",
            "contract_years",
            ["season", "contract_id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_contract_years_season_contract_id",
            table_name="contract_years",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_contracts_player_latest",
            table_name="contracts",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_player_seasons_season_minutes",
            table_name="player_seasons",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_players_current_team_id",
            table_name="players",
            postgresql_concurrently=True,
        )
