"""Roster identity and payroll facts — who is on a team and what they cost.

Shared by every router; routers never import each other.
"""
from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import desc, select

from scoutiq.api.deps import DB
from scoutiq.models import Contract, ContractYear, Player, PlayerSalary, PlayerSeason, Team


class TeamSummary(BaseModel):
    team_id: int
    abbreviation: str | None
    name: str | None


class PlayerSummary(BaseModel):
    player_id: int
    full_name: str
    position: str | None
    latest_season: str | None
    latest_stats_team: TeamSummary | None
    current_team: TeamSummary | None
    current_team_source: str | None
    team_data_note: str | None


def team_summary(team: Team | None) -> TeamSummary | None:
    if team is None:
        return None
    return TeamSummary(team_id=team.team_id, abbreviation=team.abbreviation, name=team.name)


def latest_stats_row(player_id: int, db: DB):
    return db.execute(
        select(PlayerSeason.season, Team)
        .outerjoin(Team, Team.team_id == PlayerSeason.team_id)
        .where(PlayerSeason.player_id == player_id)
        .order_by(desc(PlayerSeason.season))
        .limit(1)
    ).first()


def _player_summary_from_parts(
    player: Player,
    latest_season: str | None,
    latest_stats_team: Team | None,
    current_team: Team | None,
) -> PlayerSummary:
    note = None
    latest_stats_team_summary = team_summary(latest_stats_team)
    current_team_summary = team_summary(current_team)
    if current_team_summary and latest_stats_team_summary and current_team_summary.team_id != latest_stats_team_summary.team_id:
        note = "Current roster team differs from latest loaded stats-season team."
    elif current_team_summary and latest_season is None:
        note = "Current roster team is available, but no loaded stats season exists for this player."
    elif latest_stats_team_summary and not current_team_summary:
        note = "Current roster team has not been loaded; latest stats-season team is historical."

    return PlayerSummary(
        player_id=player.player_id,
        full_name=player.full_name,
        position=player.position,
        latest_season=latest_season,
        latest_stats_team=latest_stats_team_summary,
        current_team=current_team_summary,
        current_team_source=player.current_team_source,
        team_data_note=note,
    )


def batched_summaries(players: list[Player], db: DB) -> dict[int, PlayerSummary]:
    if not players:
        return {}

    player_ids = [player.player_id for player in players]
    # DISTINCT ON (player_id) returns one row per player — their latest season —
    # straight from Postgres, instead of pulling every season row and reducing in
    # Python (which fetched thousands of rows for the 800-candidate watchlist).
    latest_by_player: dict[int, tuple[str, Team | None]] = {
        player_id: (season, team)
        for player_id, season, team in db.execute(
            select(PlayerSeason.player_id, PlayerSeason.season, Team)
            .outerjoin(Team, Team.team_id == PlayerSeason.team_id)
            .where(PlayerSeason.player_id.in_(player_ids))
            .distinct(PlayerSeason.player_id)
            .order_by(PlayerSeason.player_id, desc(PlayerSeason.season))
        ).all()
    }

    current_team_ids = {player.current_team_id for player in players if player.current_team_id}
    current_teams = {
        team.team_id: team
        for team in db.scalars(select(Team).where(Team.team_id.in_(current_team_ids))).all()
    } if current_team_ids else {}

    summaries: dict[int, PlayerSummary] = {}
    for player in players:
        latest = latest_by_player.get(player.player_id)
        summaries[player.player_id] = _player_summary_from_parts(
            player,
            latest[0] if latest else None,
            latest[1] if latest else None,
            current_teams.get(player.current_team_id) if player.current_team_id else None,
        )
    return summaries


CAVEAT = (
    "Roster is derived from each player's current-team flag and may be incomplete or lag "
    "mid-season trades. Cap hit is the contract year where available, else realized salary "
    "(see pay_source). Excludes dead money, cap holds, incomplete-roster charges, "
    "two-way/Exhibit-10 deals, trade exceptions, Bird rights, luxury tax owed, and the "
    "repeater tax."
)


def team_cap_hits(
    db: DB, player_ids: list[int], season: str
) -> tuple[dict[int, int], dict[int, str]]:
    """Per-player cap hit for `season` and where it came from.

    Precedence: the contract year for the season (later contracts win), else the
    realized salary. Shared by the team cap sheet and the simulator's apron overlay so
    both price a roster the same way. Returns (cap_hit_by_player, pay_source_by_player).
    """
    cap_hit_by_player: dict[int, int] = {}
    pay_source_by_player: dict[int, str] = {}
    if not player_ids:
        return cap_hit_by_player, pay_source_by_player

    contract_rows = db.execute(
        select(ContractYear, Contract.player_id)
        .join(Contract, Contract.id == ContractYear.contract_id)
        .where(Contract.player_id.in_(player_ids))
        .where(ContractYear.season == season)
        .order_by(Contract.season_start)
    ).all()
    for cy, pid in contract_rows:
        if cy.aav is not None:
            cap_hit_by_player[pid] = cy.aav
            pay_source_by_player[pid] = "contract"

    salary_rows = db.scalars(
        select(PlayerSalary)
        .where(PlayerSalary.player_id.in_(player_ids))
        .where(PlayerSalary.season == season)
    ).all()
    for sr in salary_rows:
        if sr.player_id not in cap_hit_by_player and sr.salary is not None:
            cap_hit_by_player[sr.player_id] = sr.salary
            pay_source_by_player[sr.player_id] = "salary"

    return cap_hit_by_player, pay_source_by_player
