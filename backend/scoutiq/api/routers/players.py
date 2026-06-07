"""GET /players/{player_id}/valuation — production-implied value for a player's most recent season."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from scoutiq.api.deps import DB
from scoutiq.llm.player_ratings import PlayerScoutRatings, aggregate_player_scout_ratings, load_player_reports
from scoutiq.model.predict import predict_for_player
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason, Team

router = APIRouter(prefix="/players", tags=["players"])

# The most recent completed season for which we have full stats.
# Update each offseason after the ETL runs for the new season.
LATEST_SEASON = "2024-25"


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


def _team_summary(team: Team | None) -> TeamSummary | None:
    if team is None:
        return None
    return TeamSummary(team_id=team.team_id, abbreviation=team.abbreviation, name=team.name)


def _latest_stats_row(player_id: int, db: DB):
    return db.execute(
        select(PlayerSeason.season, Team)
        .outerjoin(Team, Team.team_id == PlayerSeason.team_id)
        .where(PlayerSeason.player_id == player_id)
        .order_by(desc(PlayerSeason.season))
        .limit(1)
    ).first()


def _player_summary(player: Player, db: DB) -> PlayerSummary:
    latest = _latest_stats_row(player.player_id, db)
    latest_season = latest[0] if latest else None
    latest_stats_team = _team_summary(latest[1]) if latest else None
    current_team = _team_summary(db.get(Team, player.current_team_id)) if player.current_team_id else None

    note = None
    if current_team and latest_stats_team and current_team.team_id != latest_stats_team.team_id:
        note = "Current roster team differs from latest loaded stats-season team."
    elif current_team and latest_season is None:
        note = "Current roster team is available, but no loaded stats season exists for this player."
    elif latest_stats_team and not current_team:
        note = "Current roster team has not been loaded; latest stats-season team is historical."

    return PlayerSummary(
        player_id=player.player_id,
        full_name=player.full_name,
        position=player.position,
        latest_season=latest_season,
        latest_stats_team=latest_stats_team,
        current_team=current_team,
        current_team_source=player.current_team_source,
        team_data_note=note,
    )


@router.get("", response_model=list[PlayerSummary])
def search_players(
    query: str | None = Query(None, min_length=1, description="Case-insensitive player-name search"),
    limit: int = Query(20, ge=1, le=50),
    db: DB = None,
):
    """Search players by name.

    If `query` is omitted, returns the first `limit` players alphabetically. This keeps the endpoint
    useful for dashboard bootstrap/autocomplete without inventing a ranking model.
    """
    stmt = select(Player).order_by(Player.full_name).limit(limit)
    if query:
        stmt = select(Player).where(Player.full_name.ilike(f"%{query}%")).order_by(Player.full_name).limit(limit)

    players = db.scalars(stmt).all()
    return [_player_summary(p, db) for p in players]


@router.get("/{player_id}", response_model=PlayerSummary)
def get_player(player_id: int, db: DB = None):
    """Return profile basics and latest available season for a player."""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    return _player_summary(player, db)


@router.get("/{player_id}/valuation")
def get_valuation(player_id: int, season: str | None = None, db: DB = None):
    """Return production-implied value and salary gap for a player.

    - `season` defaults to the most recent season with stats.
    - `value_pct` is what production says the player is worth (% of cap).
    - `actual_pct` is what they were actually paid (% of cap).
    - `gap_pct` = value_pct - actual_pct  (positive → underpaid, negative → overpaid).
    - `lo_pct` / `hi_pct` are the 80% conformal prediction interval bounds.
    """
    target_season = season or LATEST_SEASON

    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    try:
        prediction = predict_for_player(player_id, target_season, db)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail=f"No stats for player_id={player_id} in season {target_season}.",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # realized salary for this season (if known)
    salary_row = db.scalars(
        select(PlayerSalary).where(
            PlayerSalary.player_id == player_id,
            PlayerSalary.season == target_season,
        )
    ).first()

    cap_row = db.get(CapConstants, target_season)
    salary_cap = cap_row.salary_cap if cap_row else None

    actual_usd = salary_row.salary if salary_row else None
    actual_pct = round(actual_usd / salary_cap * 100, 2) if (actual_usd and salary_cap) else None
    value_pct = prediction["value_pct"]
    gap_pct = round(value_pct - actual_pct, 2) if actual_pct is not None else None

    return {
        "player_id": player_id,
        "player_name": player.full_name,
        "position": player.position,
        "current_team": _team_summary(db.get(Team, player.current_team_id)) if player.current_team_id else None,
        "season": target_season,
        "value_pct": value_pct,
        "lo_pct": prediction["lo_pct"],
        "hi_pct": prediction["hi_pct"],
        "actual_pct": actual_pct,
        "actual_usd": actual_usd,
        "gap_pct": gap_pct,
        "salary_cap": salary_cap,
        "value_usd": int(value_pct / 100 * salary_cap) if salary_cap else None,
        "model_version": prediction["model_version"],
        "features": prediction.get("features"),
    }


@router.get("/{player_id}/scout-ratings", response_model=PlayerScoutRatings)
def get_scout_ratings(player_id: int, db: DB = None):
    """Return fixture-backed scout-rating aggregates for a player.

    Phase 2B is intentionally offline-first: this reads committed synthetic
    reports and does not call live LLMs, Sonar, or a scout-report database.
    """
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    try:
        reports = load_player_reports()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Scout-rating fixture unavailable: {exc}") from exc

    return aggregate_player_scout_ratings(player_id, player.full_name, reports)
