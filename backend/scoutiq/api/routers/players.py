"""GET /players/{player_id}/valuation — production-implied value for a player's most recent season."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scoutiq.api import rosters
from scoutiq.api.deps import DB
from scoutiq.api.rosters import PlayerSummary, _player_summary_from_parts, latest_stats_row
from scoutiq.api.season import LATEST_SEASON, next_season
from scoutiq.api.valuation import (
    Valuation,
    value_player_detail,
    value_players,
)
from scoutiq.config import settings
from scoutiq.llm import generate
from scoutiq.llm.pricing import Usage
from scoutiq.llm.player_ratings import (
    PlayerScoutRatings,
    aggregate_from_db,
    aggregate_player_scout_ratings,
    load_player_reports,
)
from scoutiq.model.similarity import (
    SIMILARITY_BASIS,
    SimilarityMode,
    SimilarityRecord,
    build_similarity_features,
    rank_similar_players,
)
from scoutiq.models import (
    CapConstants,
    Contract,
    ContractYear,
    Player,
    PlayerRationale,
    PlayerSalary,
    PlayerSeason,
    ScoutReport,
    Team,
)

router = APIRouter(prefix="/players", tags=["players"])


class PlayerCard(PlayerSummary):
    valuation_status: str
    valuation: Valuation | None


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


class PlayerValuationCautionsResponse(BaseModel):
    items: list[PlayerCard]
    total: int
    limit: int
    season: str
    caveat: str


class PlayerContractYear(BaseModel):
    season: str
    cap_hit_usd: int | None
    cap_hit_pct: float | None
    salary_cap: int | None
    is_guaranteed: bool
    is_player_option: bool
    is_team_option: bool
    value_pct: float | None
    value_gap_pct: float | None


class PlayerContractResponse(BaseModel):
    player_id: int
    player_name: str
    contract_id: int
    season_start: str
    years: int
    total_value: int | None
    source: str
    scraped_at: str | None
    extension_start_season: str | None
    years_detail: list[PlayerContractYear]
    caveat: str


class SimilarPlayerResult(BaseModel):
    player: PlayerSummary
    similarity_score: float
    value_pct: float | None
    salary_pct: float | None
    actual_usd: int | None
    gap_pct: float | None
    age: float | None
    explanation_tags: list[str]
    deltas: dict[str, float]


class SimilarPlayersResponse(BaseModel):
    player_id: int
    player_name: str
    season: str
    mode: SimilarityMode
    basis: list[str]
    results: list[SimilarPlayerResult]
    caveat: str


def _next_season(season: str) -> str | None:
    return next_season(season)


def _pct_from_contract_year(year: ContractYear, cap_row: CapConstants | None) -> float | None:
    if year.aav and cap_row and cap_row.salary_cap:
        return round(year.aav / cap_row.salary_cap * 100, 2)
    if year.cap_pct is not None:
        return round(float(year.cap_pct) * 100, 2)
    return None


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    return [term for term in re.split(r"[\s,.'’-]+", query.strip()) if term]


def _player_summary(player: Player, db: DB) -> PlayerSummary:
    latest = latest_stats_row(player.player_id, db)
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
    summaries = rosters.batched_summaries(players, db)
    return [summaries[p.player_id] for p in players]


_PCTL_KEYS = ("gp", "mpg", "pts_pg", "reb_pg", "ast_pg", "bpm")
_PCTL_MIN_PEERS = 20


def _annotate_stat_percentiles(valuations: dict[int, Valuation]) -> None:
    """Stamp league percentile ranks onto card stats, mid-rank for ties."""
    from bisect import bisect_left, bisect_right

    stats_list = [v.stats for v in valuations.values() if v.stats is not None]
    if len(stats_list) < _PCTL_MIN_PEERS:
        return

    sorted_by_key: dict[str, list[float]] = {}
    for key in _PCTL_KEYS:
        values = sorted(
            value for stats in stats_list
            if (value := getattr(stats, key)) is not None
        )
        if len(values) >= _PCTL_MIN_PEERS:
            sorted_by_key[key] = values

    for stats in stats_list:
        pctl: dict[str, int] = {}
        for key, values in sorted_by_key.items():
            value = getattr(stats, key)
            if value is None:
                continue
            mid_rank = (bisect_left(values, value) + bisect_right(values, value)) / 2
            pctl[key] = round(100 * mid_rank / len(values))
        stats.pctl = pctl or None


def _card_valuations(
    players: list[Player],
    summaries: dict[int, PlayerSummary],
    db: DB,
    season: str | None = None,
) -> dict[int, Valuation]:
    """Value each player at `season` if given, else at their latest season.

    The watchlist pins valuation to its target season so a player's gap is
    computed against the season actually being shown. Without this, loading a
    newer stats season (with no salary yet) silently drops everyone, because
    their latest_season has no pay and gap_pct collapses to None.
    """
    def _target(player_id: int) -> str | None:
        return season or summaries[player_id].latest_season

    targets = [
        (player.player_id, _target(player.player_id))
        for player in players
        if _target(player.player_id)
    ]
    if not targets:
        return {}

    valuations = value_players(db, targets)
    return {
        player_id: valuations[(player_id, target_season)]
        for player_id, target_season in targets
        if (player_id, target_season) in valuations
    }


def _player_cards_from_parts(
    players: list[Player],
    summaries: dict[int, PlayerSummary],
    valuations: dict[int, Valuation],
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
    summaries = rosters.batched_summaries(players, db)
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
    summaries = rosters.batched_summaries(players, db)
    try:
        valuations = _card_valuations(players, summaries, db, season=valuation_season)
    except FileNotFoundError:
        valuations = {}

    _annotate_stat_percentiles(valuations)

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


@router.get("/valuation-cautions", response_model=PlayerValuationCautionsResponse)
def get_player_valuation_cautions(
    season: str | None = Query(None, description="Stats/pay season to audit; defaults to latest."),
    qualified_only: bool = Query(True),
    limit: int = Query(12, ge=1, le=50),
    db: DB = None,
):
    """Return live valuation rows where the raw value gap needs extra scrutiny."""
    target_season = season or LATEST_SEASON
    players = _watchlist_candidate_rows(
        query=None,
        season=target_season,
        position=None,
        team=None,
        qualified_only=qualified_only,
        candidate_limit=900,
        db=db,
    )
    summaries = rosters.batched_summaries(players, db)
    try:
        valuations = _card_valuations(players, summaries, db, season=target_season)
    except FileNotFoundError:
        valuations = {}

    cards = [
        card
        for card in _player_cards_from_parts(players, summaries, valuations)
        if card.valuation and card.valuation.verdict_tone == "warning"
    ]
    cards.sort(
        key=lambda card: abs(card.valuation.gap_pct or 0) if card.valuation else 0,
        reverse=True,
    )

    return PlayerValuationCautionsResponse(
        items=cards[:limit],
        total=len(cards),
        limit=limit,
        season=target_season,
        caveat=(
            "Live caution board: rows where production-implied value and pay diverge, but age, minimum "
            "salary, or impact indicators make the raw gap less trustworthy as a clean bargain signal."
        ),
    )


@router.get("/{player_id}/similar", response_model=SimilarPlayersResponse)
def get_similar_players(
    player_id: int,
    mode: SimilarityMode = Query("twins"),
    season: str | None = Query(None, description="Stats season to compare; defaults to player's latest loaded season."),
    limit: int = Query(8, ge=1, le=15),
    min_gp: int = Query(15, ge=0, le=82),
    min_minutes: int = Query(300, ge=0),
    db: DB = None,
):
    """Return role-aware similar players, contract comps, or cheaper replacements."""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    latest = latest_stats_row(player_id, db)
    target_season = season or (latest[0] if latest else LATEST_SEASON)
    season_rows = db.scalars(
        select(PlayerSeason)
        .where(PlayerSeason.season == target_season)
        .where(PlayerSeason.gp >= min_gp)
        .where(PlayerSeason.minutes >= min_minutes)
        .order_by(desc(PlayerSeason.minutes))
        .limit(900)
    ).all()

    if not any(row.player_id == player_id for row in season_rows):
        target_row = db.scalars(
            select(PlayerSeason).where(
                PlayerSeason.player_id == player_id,
                PlayerSeason.season == target_season,
            )
        ).first()
        if target_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No stats for player_id={player_id} in season {target_season}.",
            )
        season_rows = [target_row, *season_rows]

    player_ids = sorted({row.player_id for row in season_rows})
    players = db.scalars(select(Player).where(Player.player_id.in_(player_ids))).all()
    player_by_id = {row.player_id: row for row in players}
    if player_id not in player_by_id:
        player_by_id[player_id] = player
        players = [player, *players]

    cap_row = db.get(CapConstants, target_season)
    salary_cap = cap_row.salary_cap if cap_row else None
    salary_rows = db.scalars(
        select(PlayerSalary)
        .where(PlayerSalary.player_id.in_(player_ids))
        .where(PlayerSalary.season == target_season)
    ).all()
    salary_by_player = {row.player_id: row.salary for row in salary_rows}

    valuations = value_players(db, [(row.player_id, row.season) for row in season_rows])
    value_by_player = {pid: v.value_pct for (pid, _season), v in valuations.items()}

    records: list[SimilarityRecord] = []
    for row in season_rows:
        candidate = player_by_id.get(row.player_id)
        if candidate is None:
            continue
        actual_usd = salary_by_player.get(row.player_id)
        salary_pct = round(actual_usd / salary_cap * 100, 2) if actual_usd and salary_cap else None
        value_pct = value_by_player.get(row.player_id)
        records.append(SimilarityRecord(
            player_id=row.player_id,
            full_name=candidate.full_name,
            position=candidate.position,
            features=build_similarity_features(row),
            value_pct=value_pct,
            salary_pct=salary_pct,
            actual_usd=actual_usd,
            gap_pct=round(value_pct - salary_pct, 2) if value_pct is not None and salary_pct is not None else None,
        ))

    summaries = rosters.batched_summaries(players, db)
    results = []
    for item in rank_similar_players(records, player_id, mode, limit):
        summary = summaries.get(item.record.player_id)
        if summary is None:
            continue
        results.append(SimilarPlayerResult(
            player=summary,
            similarity_score=item.score,
            value_pct=item.record.value_pct,
            salary_pct=item.record.salary_pct,
            actual_usd=item.record.actual_usd,
            gap_pct=item.record.gap_pct,
            age=item.record.features.get("age"),
            explanation_tags=item.explanation_tags,
            deltas=item.deltas,
        ))

    return SimilarPlayersResponse(
        player_id=player_id,
        player_name=player.full_name,
        season=target_season,
        mode=mode,
        basis=SIMILARITY_BASIS[mode],
        results=results,
        caveat=(
            "Similarity uses same-season role, efficiency, advanced-stat, age, position, value, and cap-hit "
            "features where available. It is deterministic and separate from the valuation model artifact."
        ),
    )


@router.get("/{player_id}", response_model=PlayerSummary)
def get_player(player_id: int, db: DB = None):
    """Return profile basics and latest available season for a player."""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    return _player_summary(player, db)


@router.get("/{player_id}/contract", response_model=PlayerContractResponse)
def get_player_contract(player_id: int, db: DB = None):
    """Return the player's current Spotrac contract timeline."""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    contract = db.scalars(
        select(Contract)
        .where(Contract.player_id == player_id)
        .order_by(desc(Contract.season_start), desc(Contract.scraped_at))
        .limit(1)
    ).first()
    if contract is None:
        raise HTTPException(status_code=404, detail=f"No contract found for player_id={player_id}.")

    year_rows = db.scalars(
        select(ContractYear)
        .where(ContractYear.contract_id == contract.id)
        .order_by(ContractYear.season)
    ).all()
    seasons = [row.season for row in year_rows]
    cap_rows = db.scalars(select(CapConstants).where(CapConstants.season.in_(seasons))).all() if seasons else []
    cap_by_season = {row.season: row for row in cap_rows}

    # Model value per contract season, batched: value_players scores every season that
    # actually has stats together, instead of one prediction per contract year — most
    # future years have no stats and are simply absent from the result.
    value_by_season: dict[str, float] = {}
    if seasons:
        valuations = value_players(db, [(player_id, season) for season in seasons])
        value_by_season = {season: v.value_pct for (pid, season), v in valuations.items()}

    years_detail: list[PlayerContractYear] = []
    for row in year_rows:
        cap_row = cap_by_season.get(row.season)
        cap_hit_pct = _pct_from_contract_year(row, cap_row)
        value_pct = value_by_season.get(row.season)
        value_gap_pct = (
            round(value_pct - cap_hit_pct, 2)
            if (value_pct is not None and cap_hit_pct is not None)
            else None
        )

        years_detail.append(PlayerContractYear(
            season=row.season,
            cap_hit_usd=row.aav,
            cap_hit_pct=cap_hit_pct,
            salary_cap=cap_row.salary_cap if cap_row else None,
            is_guaranteed=row.is_guaranteed,
            is_player_option=row.is_player_option,
            is_team_option=row.is_team_option,
            value_pct=value_pct,
            value_gap_pct=value_gap_pct,
        ))

    extension_start = _next_season(max(seasons)) if seasons else None
    return PlayerContractResponse(
        player_id=player_id,
        player_name=player.full_name,
        contract_id=contract.id,
        season_start=contract.season_start,
        years=contract.years,
        total_value=contract.total_value,
        source=contract.source,
        scraped_at=contract.scraped_at.isoformat() if contract.scraped_at else None,
        extension_start_season=extension_start,
        years_detail=years_detail,
        caveat=(
            "Spotrac forward contract structure. Value gaps are shown only for seasons with loaded "
            "stats/model coverage; future seasons remain contract-only until new stats arrive."
        ),
    )


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

    latest = latest_stats_row(player_id, db)
    target_season = season or (latest[0] if latest else LATEST_SEASON)

    try:
        valuation, features, attribution = value_player_detail(db, player_id, target_season)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail=f"No stats for player_id={player_id} in season {target_season}.",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "player_id": player_id,
        "player_name": player.full_name,
        "position": player.position,
        "current_team": rosters.team_summary(db.get(Team, player.current_team_id)) if player.current_team_id else None,
        "season": target_season,
        "value_pct": valuation.value_pct,
        "lo_pct": valuation.lo_pct,
        "hi_pct": valuation.hi_pct,
        "actual_pct": valuation.actual_pct,
        "actual_usd": valuation.actual_usd,
        "gap_pct": valuation.gap_pct,
        "salary_cap": valuation.salary_cap,
        "value_usd": valuation.value_usd,
        "model_version": valuation.model_version,
        "features": features,
        "attribution": attribution,
        "verdict_label": valuation.verdict_label,
        "verdict_tone": valuation.verdict_tone,
        "caution_flags": valuation.caution_flags,
        "caveat": valuation.caveat,
        "computed_at": valuation.computed_at,
    }


@router.get("/{player_id}/scout-ratings", response_model=PlayerScoutRatings)
def get_scout_ratings(player_id: int, db: DB = None):
    """Return scout-rating aggregates for a player.

    Serves real Sonar-sourced, Claude-extracted ratings from the DB when the player has coverage,
    falling back to the committed synthetic fixture otherwise. Read-only: never calls Sonar/Claude.
    """
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    db_ratings = aggregate_from_db(db, player_id, player.full_name)
    if db_ratings is not None:
        return db_ratings

    try:
        reports = load_player_reports()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Scout-rating fixture unavailable: {exc}") from exc

    return aggregate_player_scout_ratings(player_id, player.full_name, reports)


# --- Grounded rationale ------------------------------------------------------

class RationaleCost(BaseModel):
    input_tokens: int
    output_tokens: int
    est_cost_usd: float
    sonar_cost_usd: float


class PlayerRationaleResponse(BaseModel):
    player_id: int
    player_name: str
    consensus_mode: str
    rationale: str
    citations: list[str]
    cost: RationaleCost
    grounding_issues: list[str]
    model: str | None
    generated_at: str | None
    cached: bool
    caveat: str


def _contract_summary(db: DB, player_id: int) -> str | None:
    contract = db.scalars(
        select(Contract).where(Contract.player_id == player_id)
        .order_by(desc(Contract.season_start), desc(Contract.scraped_at)).limit(1)
    ).first()
    if contract is None:
        return None
    total = f"${contract.total_value / 1e6:.1f}M" if contract.total_value else "?"
    return f"{contract.years}yr / {total} from {contract.season_start}"


@router.get("/{player_id}/rationale", response_model=PlayerRationaleResponse)
def get_player_rationale(
    player_id: int,
    consensus: Literal["fusion", "multi_source"] | None = None,
    refresh: bool = False,
    db: DB = None,
):
    """Generate (and cache) a grounded, cited verdict fusing the model's value gap with the scouting signal.

    Live LLM call — a deliberate, scoped exception to the offline posture; cached per (player, mode),
    `refresh=true` forces a fresh generation. Requires scout coverage + a valuation.
    """
    mode = consensus or settings.RATIONALE_CONSENSUS_MODE
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")

    if not refresh:
        cached = db.scalars(
            select(PlayerRationale).where(
                PlayerRationale.player_id == player_id, PlayerRationale.consensus_mode == mode
            )
        ).first()
        if cached is not None:
            return _rationale_response(player, cached, cached_flag=True)

    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set; rationale generation unavailable.")
    if mode == "multi_source" and not settings.PERPLEXITY_API_KEY:
        raise HTTPException(status_code=503, detail="PERPLEXITY_API_KEY not set; multi_source mode unavailable.")

    ratings = aggregate_from_db(db, player_id, player.full_name)
    if ratings is None or not ratings.traits:
        raise HTTPException(status_code=404, detail="No scout coverage for this player; cannot ground a rationale.")

    # The player is scouted but may have no valuation-capable season (load-managed,
    # injured, or never logged qualifying minutes). Re-frame that 404 so the caller
    # knows *which* signal is missing rather than getting a generic "no stats" error.
    try:
        val = get_valuation(player_id, None, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"{player.full_name} has scouting coverage but no model valuation "
                    "(no season with qualifying stats — e.g. load-managed or injured). "
                    "A grounded rationale needs a production-implied value gap to ground against."
                ),
            ) from exc
        raise
    traits = [(t.trait.value, t.average_score, (t.evidence[0] if t.evidence else "")) for t in ratings.traits]

    sonar_usage: Usage | None = None
    if mode == "multi_source":
        narratives, citations, sonar_usage = generate.gather_multi_source(
            player_id, player.full_name, settings.CURRENT_SEASON, settings.RATIONALE_MULTI_SOURCE_N
        )
        if not narratives:
            raise HTTPException(status_code=503, detail="Sonar returned no narratives for multi_source mode.")
    else:
        db_reports = db.scalars(select(ScoutReport).where(ScoutReport.player_id == player_id)).all()
        narratives = [r.source_text for r in db_reports]
        citations = list(dict.fromkeys(c for r in db_reports for c in (r.citations or [])))

    inputs = generate.RationaleInputs(
        player_name=player.full_name,
        season=val.get("season"),
        value_pct=val.get("value_pct"),
        actual_pct=val.get("actual_pct"),
        gap_pct=val.get("gap_pct"),
        verdict_label=val.get("verdict_label"),
        caution_flags=val.get("caution_flags") or [],
        contract_summary=_contract_summary(db, player_id),
        traits=traits,
        narratives=narratives,
        citations=citations,
    )
    try:
        result = generate.generate_rationale(
            inputs, api_key=settings.ANTHROPIC_API_KEY, model=settings.SCOUTIQ_LLM_MODEL, sonar_usage=sonar_usage
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Rationale generation failed: {exc}") from exc

    now = datetime.now(tz=timezone.utc)
    db.execute(
        pg_insert(PlayerRationale)
        .values(
            player_id=player_id, consensus_mode=mode, rationale_text=result.text,
            citations=result.citations, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            est_cost_usd=result.est_cost_usd, model=settings.SCOUTIQ_LLM_MODEL, generated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_player_rationale_mode",
            set_={
                "rationale_text": result.text, "citations": result.citations,
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                "est_cost_usd": result.est_cost_usd, "model": settings.SCOUTIQ_LLM_MODEL, "generated_at": now,
            },
        )
    )

    return PlayerRationaleResponse(
        player_id=player_id,
        player_name=player.full_name,
        consensus_mode=mode,
        rationale=result.text,
        citations=result.citations,
        cost=RationaleCost(
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            est_cost_usd=result.est_cost_usd, sonar_cost_usd=result.sonar_cost_usd,
        ),
        grounding_issues=result.grounding_issues,
        model=settings.SCOUTIQ_LLM_MODEL,
        generated_at=now.isoformat(),
        cached=False,
        caveat=(
            "Generated by Claude, fusing the production-implied value model with cited scouting reports. "
            "Model-written analysis, not official guidance — verify against the cited sources."
        ),
    )


def _rationale_response(player: Player, row: PlayerRationale, *, cached_flag: bool) -> PlayerRationaleResponse:
    return PlayerRationaleResponse(
        player_id=row.player_id,
        player_name=player.full_name,
        consensus_mode=row.consensus_mode,
        rationale=row.rationale_text,
        citations=row.citations or [],
        cost=RationaleCost(
            input_tokens=row.input_tokens or 0, output_tokens=row.output_tokens or 0,
            est_cost_usd=float(row.est_cost_usd or 0), sonar_cost_usd=0.0,
        ),
        grounding_issues=[],
        model=row.model,
        generated_at=row.generated_at.isoformat() if row.generated_at else None,
        cached=cached_flag,
        caveat=(
            "Generated by Claude, fusing the production-implied value model with cited scouting reports. "
            "Model-written analysis, not official guidance — verify against the cited sources."
        ),
    )
