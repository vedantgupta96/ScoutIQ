"""Deterministic roster-needs and candidate-fit scoring.

This is a descriptive decision-support model, not an outcome predictor. It turns
already-loaded role statistics into league-normalized player contributions, compares a
projected roster with the median team benchmark, and measures how much a candidate reduces
the visible deficits. Contract value and cap feasibility remain separate signals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Literal

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class DimensionSpec:
    key: str
    label: str
    features: tuple[tuple[str, float], ...]
    top_n: int
    caution: str | None = None


DIMENSIONS: tuple[DimensionSpec, ...] = (
    DimensionSpec(
        "creation",
        "Creation",
        (("AST_PCT", 0.45), ("ast_to_tov", 0.25), ("ast_pg", 0.20), ("USG_PCT", 0.10)),
        3,
    ),
    DimensionSpec(
        "spacing",
        "Spacing",
        (("fg3m_pg", 0.55), ("TS_PCT", 0.25), ("EFG_PCT", 0.20)),
        5,
    ),
    DimensionSpec(
        "scoring",
        "Scoring",
        (("pts_pg", 0.35), ("USG_PCT", 0.25), ("OBPM", 0.25), ("TS_PCT", 0.15)),
        4,
    ),
    DimensionSpec(
        "rebounding",
        "Rebounding & size",
        (("REB_PCT", 0.55), ("reb_pg", 0.25), ("OREB_PCT", 0.20)),
        4,
    ),
    DimensionSpec(
        "defense",
        "Defensive activity",
        (("DBPM", 0.40), ("stock_pg", 0.30), ("NET_RATING", 0.20), ("DEF_RATING", -0.10)),
        5,
        "Public individual defense metrics are noisy; treat this as an activity/impact proxy.",
    ),
    DimensionSpec(
        "availability",
        "Availability & depth",
        (("gp", 0.55), ("min_pg", 0.45)),
        8,
    ),
)

FEATURE_KEYS = tuple(
    sorted({feature for dimension in DIMENSIONS for feature, _ in dimension.features})
)


@dataclass(frozen=True)
class RoleRecord:
    player_id: int
    team_id: int | None
    position: str | None
    features: dict[str, float | None]


@dataclass(frozen=True)
class PlayerDimension:
    capacity: float
    coverage: float


@dataclass(frozen=True)
class RosterNeed:
    key: str
    label: str
    coverage_pct: float
    deficit_pct: float
    status: Literal["critical", "need", "covered"]
    caution: str | None


@dataclass(frozen=True)
class TeamFitProfile:
    roster_player_count: int
    profiled_player_count: int
    confidence: Confidence
    needs: list[RosterNeed]


@dataclass(frozen=True)
class CandidateFill:
    key: str
    label: str
    coverage_gain_pct: float
    deficit_reduction_pct: float


@dataclass(frozen=True)
class CandidateFit:
    player_id: int
    fit_score: float
    confidence: Confidence
    fills: list[CandidateFill]
    reasons: list[str]


@dataclass(frozen=True)
class FitContext:
    records: dict[int, RoleRecord]
    player_dimensions: dict[int, dict[str, PlayerDimension]]
    benchmarks: dict[str, float]


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    return mean, std if std > 1e-9 else 1.0


def _workload(features: dict[str, float | None]) -> float:
    min_pg = _num(features.get("min_pg"))
    if min_pg is None:
        return 0.25
    return max(0.15, min(1.0, min_pg / 30.0))


def _player_dimension(
    record: RoleRecord,
    spec: DimensionSpec,
    feature_stats: dict[str, tuple[float, float]],
) -> PlayerDimension:
    weighted_z = 0.0
    available_weight = 0.0
    total_weight = sum(abs(weight) for _, weight in spec.features)

    for feature, weight in spec.features:
        value = _num(record.features.get(feature))
        if value is None:
            continue
        mean, std = feature_stats[feature]
        z_score = max(-2.5, min(2.5, (value - mean) / std))
        direction = 1.0 if weight >= 0 else -1.0
        weighted_z += z_score * direction * abs(weight)
        available_weight += abs(weight)

    if available_weight == 0:
        return PlayerDimension(capacity=0.0, coverage=0.0)

    role_z = weighted_z / available_weight
    normalized = max(0.0, min(1.0, (role_z + 2.0) / 4.0))
    workload = 1.0 if spec.key == "availability" else _workload(record.features)
    return PlayerDimension(
        capacity=normalized * workload,
        coverage=available_weight / total_weight,
    )


def _team_capacity(
    player_dimensions: dict[int, dict[str, PlayerDimension]],
    player_ids: set[int],
    spec: DimensionSpec,
) -> float:
    contributions = sorted(
        (
            player_dimensions[player_id][spec.key].capacity
            for player_id in player_ids
            if player_id in player_dimensions
        ),
        reverse=True,
    )
    return sum(contributions[: spec.top_n])


def build_fit_context(records: list[RoleRecord]) -> FitContext:
    """Normalize league role data and derive median full-roster benchmarks."""
    records_by_id = {record.player_id: record for record in records}
    feature_stats = {
        feature: _mean_std(
            [value for record in records if (value := _num(record.features.get(feature))) is not None]
        )
        for feature in FEATURE_KEYS
    }
    player_dimensions = {
        record.player_id: {
            spec.key: _player_dimension(record, spec, feature_stats) for spec in DIMENSIONS
        }
        for record in records
    }

    players_by_team: dict[int, set[int]] = {}
    for record in records:
        if record.team_id is not None:
            players_by_team.setdefault(record.team_id, set()).add(record.player_id)

    benchmarks: dict[str, float] = {}
    for spec in DIMENSIONS:
        team_capacities = [
            _team_capacity(player_dimensions, player_ids, spec)
            for player_ids in players_by_team.values()
            if len(player_ids) >= 5
        ]
        fallback = spec.top_n * 0.5
        benchmarks[spec.key] = max(0.25, median(team_capacities) if team_capacities else fallback)

    return FitContext(
        records=records_by_id,
        player_dimensions=player_dimensions,
        benchmarks=benchmarks,
    )


def _confidence(profiled: int, total: int, feature_coverage: float) -> Confidence:
    roster_coverage = profiled / total if total > 0 else 0.0
    if total >= 8 and roster_coverage >= 0.80 and feature_coverage >= 0.70:
        return "high"
    if total >= 5 and roster_coverage >= 0.55 and feature_coverage >= 0.45:
        return "medium"
    return "low"


def profile_roster(context: FitContext, player_ids: set[int]) -> TeamFitProfile:
    """Compare a projected roster with median league team role coverage."""
    profiled_ids = {player_id for player_id in player_ids if player_id in context.records}
    coverage_values = [
        dimension.coverage
        for player_id in profiled_ids
        for dimension in context.player_dimensions[player_id].values()
    ]
    feature_coverage = (
        sum(coverage_values) / len(coverage_values) if coverage_values else 0.0
    )

    needs: list[RosterNeed] = []
    for spec in DIMENSIONS:
        benchmark = context.benchmarks[spec.key]
        capacity = _team_capacity(context.player_dimensions, profiled_ids, spec)
        coverage_pct = max(0.0, min(150.0, capacity / benchmark * 100.0))
        deficit_pct = max(0.0, 100.0 - coverage_pct)
        status: Literal["critical", "need", "covered"]
        if deficit_pct >= 25:
            status = "critical"
        elif deficit_pct >= 10:
            status = "need"
        else:
            status = "covered"
        needs.append(
            RosterNeed(
                key=spec.key,
                label=spec.label,
                coverage_pct=round(coverage_pct, 1),
                deficit_pct=round(deficit_pct, 1),
                status=status,
                caution=spec.caution,
            )
        )

    needs.sort(key=lambda need: (need.deficit_pct, need.label), reverse=True)
    return TeamFitProfile(
        roster_player_count=len(player_ids),
        profiled_player_count=len(profiled_ids),
        confidence=_confidence(len(profiled_ids), len(player_ids), feature_coverage),
        needs=needs,
    )


def score_candidate(
    context: FitContext,
    roster_player_ids: set[int],
    candidate_player_id: int,
) -> CandidateFit:
    """Measure the marginal roster-deficit reduction from adding one candidate."""
    before = profile_roster(context, roster_player_ids)
    if candidate_player_id in roster_player_ids or candidate_player_id not in context.records:
        return CandidateFit(
            player_id=candidate_player_id,
            fit_score=0.0,
            confidence="low" if candidate_player_id not in context.records else before.confidence,
            fills=[],
            reasons=["No measurable reduction against the current projected roster."],
        )

    after = profile_roster(context, {*roster_player_ids, candidate_player_id})
    after_by_key = {need.key: need for need in after.needs}
    fills: list[CandidateFill] = []
    weighted_reduction = 0.0
    total_weight = 0.0
    total_deficit = sum(need.deficit_pct for need in before.needs)

    for need in before.needs:
        if need.deficit_pct <= 0:
            continue
        after_need = after_by_key[need.key]
        reduction = max(0.0, need.deficit_pct - after_need.deficit_pct)
        if reduction > 0.05:
            fills.append(
                CandidateFill(
                    key=need.key,
                    label=need.label,
                    coverage_gain_pct=round(
                        max(0.0, after_need.coverage_pct - need.coverage_pct), 1
                    ),
                    deficit_reduction_pct=round(reduction, 1),
                )
            )
        weight = need.deficit_pct ** 1.5
        weighted_reduction += weight * min(1.0, reduction / need.deficit_pct)
        total_weight += weight

    fills.sort(key=lambda fill: (fill.deficit_reduction_pct, fill.label), reverse=True)
    share_filled = weighted_reduction / total_weight if total_weight else 0.0
    need_severity = min(1.0, total_deficit / 100.0)
    fit_score = 100.0 * share_filled * need_severity
    top_need = before.needs[0].key if before.needs else None
    reasons = []
    for fill in fills[:3]:
        prefix = "Addresses top need" if fill.key == top_need else "Adds"
        reasons.append(f"{prefix}: {fill.label} (+{fill.coverage_gain_pct:.1f} coverage)")
    if not reasons:
        reasons.append("Adds depth, but not in a current measured deficit.")

    candidate_dimensions = context.player_dimensions[candidate_player_id].values()
    candidate_coverage = sum(item.coverage for item in candidate_dimensions) / len(DIMENSIONS)
    if before.confidence == "high" and candidate_coverage >= 0.70:
        confidence: Confidence = "high"
    elif before.confidence != "low" and candidate_coverage >= 0.45:
        confidence = "medium"
    else:
        confidence = "low"

    return CandidateFit(
        player_id=candidate_player_id,
        fit_score=round(fit_score, 1),
        confidence=confidence,
        fills=fills[:3],
        reasons=reasons,
    )


def rank_candidates(
    context: FitContext,
    roster_player_ids: set[int],
    candidate_player_ids: list[int],
) -> list[CandidateFit]:
    return sorted(
        (
            score_candidate(context, roster_player_ids, player_id)
            for player_id in candidate_player_ids
        ),
        key=lambda result: (result.fit_score, result.player_id),
        reverse=True,
    )
