"""Database adapter and response models for deterministic roster-fit scoring."""
from __future__ import annotations

import threading
import time

from pydantic import BaseModel
from sqlalchemy import select

from scoutiq.api.deps import DB
from scoutiq.model.roster_fit import (
    CandidateFit,
    FitContext,
    RoleRecord,
    TeamFitProfile,
    build_fit_context,
)
from scoutiq.model.similarity import build_similarity_features
from scoutiq.models import Player, PlayerSeason

FIT_CAVEAT = (
    "Roster needs compare the selected projected roster with median league team role coverage. "
    "Player contributions use latest-season stats and recent minutes as a role proxy, not a "
    "minutes forecast. Fit is deterministic marginal deficit reduction; it is separate from "
    "contract value and cap feasibility. Public individual defense metrics are noisy."
)

_FIT_CONTEXT_TTL_SECONDS = 300
_fit_context_cache: dict[tuple[object, str], tuple[float, FitContext]] = {}
_fit_context_cache_lock = threading.Lock()


class RosterNeedResponse(BaseModel):
    key: str
    label: str
    coverage_pct: float
    deficit_pct: float
    status: str
    caution: str | None


class TeamNeedsResponse(BaseModel):
    role_season: str
    roster_player_count: int
    profiled_player_count: int
    confidence: str
    needs: list[RosterNeedResponse]
    caveat: str


class CandidateFillResponse(BaseModel):
    key: str
    label: str
    coverage_gain_pct: float
    deficit_reduction_pct: float


class CandidateFitResponse(BaseModel):
    fit_score: float
    confidence: str
    fills: list[CandidateFillResponse]
    reasons: list[str]


def load_fit_context(db: DB, role_season: str) -> FitContext:
    """Load one comparable stats season league-wide and build the fit context."""
    bind = db.get_bind() if hasattr(db, "get_bind") else db
    cache_key = (bind, role_season)
    now = time.monotonic()
    with _fit_context_cache_lock:
        cached = _fit_context_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]

    season_rows = db.scalars(
        select(PlayerSeason)
        .where(PlayerSeason.season == role_season)
        .where(PlayerSeason.gp >= 5)
        .where(PlayerSeason.minutes >= 100)
    ).all()
    player_ids = [row.player_id for row in season_rows]
    players = (
        db.scalars(select(Player).where(Player.player_id.in_(player_ids))).all()
        if player_ids
        else []
    )
    player_by_id = {player.player_id: player for player in players}

    records = []
    for row in season_rows:
        player = player_by_id.get(row.player_id)
        if player is None:
            continue
        records.append(
            RoleRecord(
                player_id=row.player_id,
                team_id=row.team_id or player.current_team_id,
                position=player.position,
                features=build_similarity_features(row),
            )
        )
    context = build_fit_context(records)
    with _fit_context_cache_lock:
        _fit_context_cache[cache_key] = (now + _FIT_CONTEXT_TTL_SECONDS, context)
        expired = [key for key, (expires_at, _) in _fit_context_cache.items() if expires_at <= now]
        for key in expired:
            _fit_context_cache.pop(key, None)
    return context


def needs_response(profile: TeamFitProfile, role_season: str) -> TeamNeedsResponse:
    return TeamNeedsResponse(
        role_season=role_season,
        roster_player_count=profile.roster_player_count,
        profiled_player_count=profile.profiled_player_count,
        confidence=profile.confidence,
        needs=[RosterNeedResponse(**vars(need)) for need in profile.needs],
        caveat=FIT_CAVEAT,
    )


def candidate_fit_response(result: CandidateFit) -> CandidateFitResponse:
    return CandidateFitResponse(
        fit_score=result.fit_score,
        confidence=result.confidence,
        fills=[CandidateFillResponse(**vars(fill)) for fill in result.fills],
        reasons=result.reasons,
    )
