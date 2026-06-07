"""GET /players/{player_id}/valuation — production-implied value for a player's most recent season."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, select

from scoutiq.api.deps import DB
from scoutiq.llm.player_ratings import PlayerScoutRatings, aggregate_player_scout_ratings, load_player_reports
from scoutiq.model.predict import build_features_from_season, predict_for_player, predict_many_from_features
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason, Team

router = APIRouter(prefix="/players", tags=["players"])

# The most recent completed season for which we have full stats.
# Update each offseason after the ETL runs for the new season.
LATEST_SEASON = "2025-26"


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


class PlayerCardValuation(BaseModel):
    season: str
    value_pct: float
    lo_pct: float
    hi_pct: float
    actual_pct: float | None
    actual_usd: int | None
    gap_pct: float | None
    salary_cap: int | None
    model_version: str


class PlayerCard(PlayerSummary):
    valuation_status: str
    valuation: PlayerCardValuation | None


class PlayerWatchlistResponse(BaseModel):
    items: list[PlayerCard]
    total: int
    limit: int
    offset: int
    bucket: str
    sort: str
    season: str | None
    qualified_only: bool
    caveat: str


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


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    return [term for term in re.split(r"[\s,.'’-]+", query.strip()) if term]


def _player_summary_from_parts(
    player: Player,
    latest_season: str | None,
    latest_stats_team: Team | None,
    current_team: Team | None,
) -> PlayerSummary:
    note = None
    latest_stats_team_summary = _team_summary(latest_stats_team)
    current_team_summary = _team_summary(current_team)
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


def _player_summary(player: Player, db: DB) -> PlayerSummary:
    latest = _latest_stats_row(player.player_id, db)
    latest_season = latest[0] if latest else None
    latest_stats_team = latest[1] if latest else None
    current_team = db.get(Team, player.current_team_id) if player.current_team_id else None
    return _player_summary_from_parts(player, latest_season, latest_stats_team, current_team)


def _search_player_rows(query: str | None, limit: int, db: DB) -> list[Player]:
    stmt = select(Player).order_by(Player.full_name).limit(limit)
    if query:
        terms = _query_terms(query)
        if terms:
            stmt = (
                select(Player)
                .where(and_(*(Player.full_name.ilike(f"%{term}%") for term in terms)))
                .order_by(Player.full_name)
                .limit(limit)
            )
    return db.scalars(stmt).all()


def _watchlist_candidate_rows(
    *,
    query: str | None,
    season: str | None,
    position: str | None,
    team: str | None,
    qualified_only: bool,
    candidate_limit: int,
    db: DB,
) -> list[Player]:
    """Fetch a broad candidate set before valuation ranking.

    Empty-query watchlists default to the latest loaded season so retired or
    stale historical players do not dominate the homepage. Explicit searches
    can still find older players through the normal player-name match.
    """
    if query:
        stmt = select(Player)
        terms = _query_terms(query)
        if terms:
            stmt = stmt.where(and_(*(Player.full_name.ilike(f"%{term}%") for term in terms)))
    else:
        target_season = season or LATEST_SEASON
        stmt = (
            select(Player)
            .join(PlayerSeason, PlayerSeason.player_id == Player.player_id)
            .where(PlayerSeason.season == target_season)
        )
        if qualified_only:
            stmt = stmt.where(PlayerSeason.gp >= 20).where(PlayerSeason.minutes >= 600)

    if position:
        stmt = stmt.where(Player.position.ilike(f"{position}%"))
    if team:
        stmt = stmt.outerjoin(Team, Team.team_id == Player.current_team_id).where(
            Team.abbreviation.ilike(team.strip())
        )

    # Order so the candidate cap, if it ever bites, keeps the most relevant
    # players rather than an alphabetical prefix: most-played for the season
    # board, name for free-text search (which has no season row to sort on).
    order_by = Player.full_name if query else PlayerSeason.minutes.desc().nulls_last()
    return db.scalars(stmt.order_by(order_by).limit(candidate_limit)).all()


def _batched_summaries(players: list[Player], db: DB) -> dict[int, PlayerSummary]:
    if not players:
        return {}

    player_ids = [player.player_id for player in players]
    latest_by_player: dict[int, tuple[str, Team | None]] = {}
    for player_id, season, team in db.execute(
        select(PlayerSeason.player_id, PlayerSeason.season, Team)
        .outerjoin(Team, Team.team_id == PlayerSeason.team_id)
        .where(PlayerSeason.player_id.in_(player_ids))
        .order_by(PlayerSeason.player_id, desc(PlayerSeason.season))
    ).all():
        if player_id not in latest_by_player:
            latest_by_player[player_id] = (season, team)

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
    players = _search_player_rows(query, limit, db)
    summaries = _batched_summaries(players, db)
    return [summaries[p.player_id] for p in players]


def _card_valuations(
    players: list[Player],
    summaries: dict[int, PlayerSummary],
    db: DB,
    season: str | None = None,
) -> dict[int, PlayerCardValuation]:
    """Value each player at `season` if given, else at their latest season.

    The watchlist pins valuation to its target season so a player's gap is
    computed against the season actually being shown. Without this, loading a
    newer stats season (with no salary yet) silently drops everyone, because
    their latest_season has no pay and gap_pct collapses to None.
    """
    def _target(player_id: int) -> str | None:
        return season or summaries[player_id].latest_season

    player_ids = [player.player_id for player in players if _target(player.player_id)]
    if not player_ids:
        return {}

    player_by_id = {player.player_id: player for player in players}
    target_seasons = {_target(player_id) for player_id in player_ids}
    seasons = sorted(season for season in target_seasons if season)

    season_rows = db.scalars(
        select(PlayerSeason)
        .where(PlayerSeason.player_id.in_(player_ids))
        .where(PlayerSeason.season.in_(seasons))
    ).all()
    season_by_key = {(row.player_id, row.season): row for row in season_rows}

    salary_rows = db.scalars(
        select(PlayerSalary)
        .where(PlayerSalary.player_id.in_(player_ids))
        .where(PlayerSalary.season.in_(seasons))
    ).all()
    salary_by_key = {(row.player_id, row.season): row for row in salary_rows}

    cap_rows = db.scalars(select(CapConstants).where(CapConstants.season.in_(seasons))).all()
    cap_by_season = {row.season: row for row in cap_rows}

    feature_rows: list[dict] = []
    feature_keys: list[tuple[int, str]] = []
    for player_id in player_ids:
        target_season = _target(player_id)
        if not target_season:
            continue
        season_row = season_by_key.get((player_id, target_season))
        if season_row is None:
            continue
        feature_rows.append(build_features_from_season(season_row, player_by_id[player_id]))
        feature_keys.append((player_id, target_season))

    predictions = predict_many_from_features(feature_rows)
    valuations: dict[int, PlayerCardValuation] = {}
    for (player_id, season), prediction in zip(feature_keys, predictions):
        salary_row = salary_by_key.get((player_id, season))
        cap_row = cap_by_season.get(season)
        salary_cap = cap_row.salary_cap if cap_row else None
        actual_usd = salary_row.salary if salary_row else None
        actual_pct = round(actual_usd / salary_cap * 100, 2) if (actual_usd and salary_cap) else None
        value_pct = prediction["value_pct"]
        valuations[player_id] = PlayerCardValuation(
            season=season,
            value_pct=value_pct,
            lo_pct=prediction["lo_pct"],
            hi_pct=prediction["hi_pct"],
            actual_pct=actual_pct,
            actual_usd=actual_usd,
            gap_pct=round(value_pct - actual_pct, 2) if actual_pct is not None else None,
            salary_cap=salary_cap,
            model_version=prediction["model_version"],
        )
    return valuations


def _player_cards_from_parts(
    players: list[Player],
    summaries: dict[int, PlayerSummary],
    valuations: dict[int, PlayerCardValuation],
) -> list[PlayerCard]:
    cards: list[PlayerCard] = []
    for player in players:
        summary = summaries[player.player_id]
        valuation = valuations.get(player.player_id)
        cards.append(PlayerCard(
            **summary.model_dump(),
            valuation_status="ready" if valuation else "unavailable",
            valuation=valuation,
        ))
    return cards


@router.get("/cards", response_model=list[PlayerCard])
def get_player_cards(
    query: str | None = Query(None, min_length=1, description="Case-insensitive player-name search"),
    limit: int = Query(40, ge=1, le=50),
    db: DB = None,
):
    """Return player-card summaries plus valuation snippets using batched DB/model work."""
    players = _search_player_rows(query, limit, db)
    summaries = _batched_summaries(players, db)
    try:
        valuations = _card_valuations(players, summaries, db)
    except FileNotFoundError:
        valuations = {}

    return _player_cards_from_parts(players, summaries, valuations)


@router.get("/watchlist", response_model=PlayerWatchlistResponse)
def get_player_watchlist(
    query: str | None = Query(None, min_length=1, description="Case-insensitive player-name search"),
    bucket: Literal["all", "underpaid", "overpaid"] = Query("all"),
    sort: Literal["mismatch", "gap", "value", "pay", "name"] = Query("mismatch"),
    season: str | None = Query(None, description="Stats season for the default watchlist; defaults to latest."),
    position: str | None = Query(None, min_length=1, max_length=8),
    team: str | None = Query(None, min_length=2, max_length=4, description="Current-team abbreviation."),
    qualified_only: bool = Query(True),
    limit: int = Query(24, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: DB = None,
):
    """Return ranked contract mismatches for the homepage watchlist."""
    players = _watchlist_candidate_rows(
        query=query,
        season=season,
        position=position,
        team=team,
        qualified_only=qualified_only,
        candidate_limit=800,  # comfortably exceeds one season's player count
        db=db,
    )
    # Pin valuation to the season the watchlist is showing (default latest), so a
    # player's gap is computed against that season's pay rather than their newest
    # stats season, which may have no salary loaded yet.
    valuation_season = season or LATEST_SEASON
    summaries = _batched_summaries(players, db)
    try:
        valuations = _card_valuations(players, summaries, db, season=valuation_season)
    except FileNotFoundError:
        valuations = {}

    cards = [
        card
        for card in _player_cards_from_parts(players, summaries, valuations)
        if card.valuation and card.valuation.gap_pct is not None
    ]

    if bucket == "underpaid":
        cards = [card for card in cards if (card.valuation and card.valuation.gap_pct > 0)]
    elif bucket == "overpaid":
        cards = [card for card in cards if (card.valuation and card.valuation.gap_pct < 0)]

    def sort_key(card: PlayerCard):
        valuation = card.valuation
        gap = valuation.gap_pct if valuation and valuation.gap_pct is not None else 0
        if sort == "gap":
            return gap
        if sort == "value":
            return valuation.value_pct if valuation else 0
        if sort == "pay":
            return valuation.actual_pct if valuation and valuation.actual_pct is not None else 0
        if sort == "name":
            return card.full_name.lower()
        return abs(gap)

    reverse = sort != "name"
    cards = sorted(cards, key=sort_key, reverse=reverse)
    total = len(cards)
    page = cards[offset:offset + limit]

    return PlayerWatchlistResponse(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        bucket=bucket,
        sort=sort,
        season=valuation_season,
        qualified_only=qualified_only,
        caveat=(
            "Default watchlist ranks qualified players from the latest loaded season by absolute value/pay gap. "
            "Historical players remain searchable by name."
        ),
    )


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
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    latest = _latest_stats_row(player_id, db)
    target_season = season or (latest[0] if latest else LATEST_SEASON)

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
