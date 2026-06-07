"""Deterministic player-similarity scoring for archetypes and replacement markets."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from scoutiq.model.features import primary_position

SimilarityMode = Literal["twins", "contract_comps", "replacements"]


SIMILARITY_BASIS = {
    "twins": [
        "age",
        "position",
        "usage",
        "efficiency",
        "creation",
        "rebounding",
        "defensive activity",
        "workload",
    ],
    "contract_comps": [
        "model value",
        "cap hit",
        "age",
        "role stats",
        "position",
    ],
    "replacements": [
        "position fit",
        "similar role",
        "lower cap hit",
        "model value retention",
        "surplus value",
    ],
}

_MODE_WEIGHTS: dict[SimilarityMode, dict[str, float]] = {
    "twins": {
        "age": 0.8,
        "min_pg": 0.9,
        "pts_pg": 1.2,
        "reb_pg": 0.8,
        "ast_pg": 1.0,
        "stock_pg": 0.7,
        "fg3m_pg": 0.8,
        "USG_PCT": 1.3,
        "TS_PCT": 0.9,
        "AST_PCT": 0.9,
        "REB_PCT": 0.7,
        "BPM": 0.9,
        "OBPM": 0.7,
        "DBPM": 0.5,
        "PER": 0.5,
    },
    "contract_comps": {
        "age": 0.7,
        "pts_pg": 0.8,
        "reb_pg": 0.5,
        "ast_pg": 0.7,
        "USG_PCT": 0.8,
        "TS_PCT": 0.5,
        "BPM": 0.7,
        "value_pct": 1.5,
        "salary_pct": 1.4,
        "gap_pct": 0.8,
    },
    "replacements": {
        "age": 0.7,
        "min_pg": 0.8,
        "pts_pg": 1.0,
        "reb_pg": 0.7,
        "ast_pg": 0.9,
        "stock_pg": 0.6,
        "fg3m_pg": 0.7,
        "USG_PCT": 1.0,
        "TS_PCT": 0.8,
        "BPM": 0.9,
        "value_pct": 1.1,
        "salary_pct": 0.9,
        "gap_pct": 1.2,
    },
}


@dataclass(frozen=True)
class SimilarityRecord:
    player_id: int
    full_name: str
    position: str | None
    features: dict[str, float | None]
    value_pct: float | None = None
    salary_pct: float | None = None
    actual_usd: int | None = None
    gap_pct: float | None = None


@dataclass(frozen=True)
class SimilarityScore:
    record: SimilarityRecord
    score: float
    explanation_tags: list[str]
    deltas: dict[str, float]


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return val if math.isfinite(val) else None


def _per_game(box: dict, key: str, gp: int | None) -> float | None:
    value = _num(box.get(key))
    return value / gp if value is not None and gp and gp > 0 else None


def build_similarity_features(season_row) -> dict[str, float | None]:
    """Build role/archetype features from a PlayerSeason-like row."""
    box = season_row.box or {}
    adv = season_row.advanced or {}
    gp = int(season_row.gp or 0)
    minutes = _num(season_row.minutes)
    tov_pg = _per_game(box, "TOV", gp)
    ast_pg = _per_game(box, "AST", gp)
    stl_pg = _per_game(box, "STL", gp)
    blk_pg = _per_game(box, "BLK", gp)

    features = {
        "age": _num(season_row.age),
        "gp": _num(season_row.gp),
        "minutes": minutes,
        "min_pg": minutes / gp if minutes is not None and gp > 0 else None,
        "pts_pg": _per_game(box, "PTS", gp),
        "reb_pg": _per_game(box, "REB", gp),
        "ast_pg": ast_pg,
        "stl_pg": stl_pg,
        "blk_pg": blk_pg,
        "stock_pg": (stl_pg or 0) + (blk_pg or 0) if stl_pg is not None or blk_pg is not None else None,
        "tov_pg": tov_pg,
        "fg3m_pg": _per_game(box, "FG3M", gp),
        "ast_to_tov": ast_pg / tov_pg if ast_pg is not None and tov_pg and tov_pg > 0 else None,
    }
    for key in [
        "USG_PCT",
        "TS_PCT",
        "EFG_PCT",
        "AST_PCT",
        "OREB_PCT",
        "DREB_PCT",
        "REB_PCT",
        "TM_TOV_PCT",
        "PIE",
        "NET_RATING",
        "BPM",
        "OBPM",
        "DBPM",
        "VORP",
        "WS",
        "WS48",
        "PER",
    ]:
        features[key] = _num(adv.get(key))
    return features


def _mean_std(records: list[SimilarityRecord], keys: list[str]) -> dict[str, tuple[float, float]]:
    stats: dict[str, tuple[float, float]] = {}
    for key in keys:
        vals = [_num(r.features.get(key)) for r in records]
        vals = [v for v in vals if v is not None]
        if not vals:
            stats[key] = (0.0, 1.0)
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(len(vals), 1)
        stats[key] = (mean, math.sqrt(var) or 1.0)
    return stats


def _z(record: SimilarityRecord, key: str, stats: dict[str, tuple[float, float]]) -> float | None:
    val = _num(record.features.get(key))
    if val is None:
        return None
    mean, std = stats[key]
    return (val - mean) / std


def _same_position(a: str | None, b: str | None) -> bool:
    return primary_position(a) == primary_position(b)


def _position_family(position: str | None) -> str | None:
    pos = primary_position(position)
    if pos in {"PG", "SG"}:
        return "guard"
    if pos in {"SF", "PF"}:
        return "wing/forward"
    return pos


def _position_penalty(target: SimilarityRecord, candidate: SimilarityRecord) -> float:
    if _same_position(target.position, candidate.position):
        return 0.0
    if _position_family(target.position) and _position_family(target.position) == _position_family(candidate.position):
        return 0.35
    return 0.9


def _mode_features(record: SimilarityRecord) -> dict[str, float | None]:
    features = dict(record.features)
    features["value_pct"] = record.value_pct
    features["salary_pct"] = record.salary_pct
    features["gap_pct"] = record.gap_pct
    return features


def _eligible(target: SimilarityRecord, candidate: SimilarityRecord, mode: SimilarityMode) -> bool:
    if candidate.player_id == target.player_id:
        return False
    if mode != "replacements":
        return True
    if not _same_position(target.position, candidate.position) and _position_family(target.position) != _position_family(candidate.position):
        return False
    if target.salary_pct is not None and candidate.salary_pct is not None and candidate.salary_pct > target.salary_pct + 0.5:
        return False
    if target.value_pct is not None and candidate.value_pct is not None and candidate.value_pct < target.value_pct - 4.0:
        return False
    return True


def _score_pair(
    target: SimilarityRecord,
    candidate: SimilarityRecord,
    mode: SimilarityMode,
    stats: dict[str, tuple[float, float]],
) -> float:
    weights = _MODE_WEIGHTS[mode]
    target_features = SimilarityRecord(
        target.player_id,
        target.full_name,
        target.position,
        _mode_features(target),
    )
    candidate_features = SimilarityRecord(
        candidate.player_id,
        candidate.full_name,
        candidate.position,
        _mode_features(candidate),
    )
    dist = 0.0
    total = 0.0
    for key, weight in weights.items():
        tz = _z(target_features, key, stats)
        cz = _z(candidate_features, key, stats)
        if tz is None or cz is None:
            continue
        dist += weight * (tz - cz) ** 2
        total += weight
    if total == 0:
        return 0.0
    normalized = math.sqrt(dist / total)
    penalty = _position_penalty(target, candidate)
    if mode == "replacements" and target.salary_pct is not None and candidate.salary_pct is not None:
        # Reward cheaper alternatives after the role similarity is established.
        penalty -= min(0.35, max(0.0, (target.salary_pct - candidate.salary_pct) / 20))
    score = 100 * math.exp(-(normalized + penalty) / 1.65)
    return round(max(0.0, min(100.0, score)), 1)


def _delta(target: SimilarityRecord, candidate: SimilarityRecord, key: str) -> float | None:
    target_val = _num(_mode_features(target).get(key))
    candidate_val = _num(_mode_features(candidate).get(key))
    if target_val is None or candidate_val is None:
        return None
    return round(candidate_val - target_val, 2)


def _tags(target: SimilarityRecord, candidate: SimilarityRecord, mode: SimilarityMode, score: float) -> list[str]:
    tags: list[str] = []
    if _same_position(target.position, candidate.position):
        tags.append("same position")
    elif _position_family(target.position) == _position_family(candidate.position):
        tags.append("position family")

    checks = [
        ("USG_PCT", 0.035, "similar usage"),
        ("TS_PCT", 0.035, "similar efficiency"),
        ("AST_PCT", 0.04, "similar creation"),
        ("REB_PCT", 0.035, "similar rebounding"),
        ("BPM", 1.5, "similar BPM"),
        ("fg3m_pg", 0.7, "similar spacing"),
    ]
    for key, threshold, label in checks:
        diff = _delta(target, candidate, key)
        if diff is not None and abs(diff) <= threshold:
            tags.append(label)

    if mode == "contract_comps":
        if (diff := _delta(target, candidate, "salary_pct")) is not None and abs(diff) <= 3:
            tags.append("similar cap hit")
        if (diff := _delta(target, candidate, "value_pct")) is not None and abs(diff) <= 3:
            tags.append("similar value tier")
    if mode == "replacements":
        if (diff := _delta(target, candidate, "salary_pct")) is not None and diff < -0.5:
            tags.append("cheaper contract")
        if (diff := _delta(target, candidate, "gap_pct")) is not None and diff >= 0:
            tags.append("better surplus")
    if score >= 80:
        tags.append("tight match")
    return tags[:5]


def rank_similar_players(
    records: list[SimilarityRecord],
    target_player_id: int,
    mode: SimilarityMode,
    limit: int,
) -> list[SimilarityScore]:
    """Rank candidate records against one target player."""
    target = next((record for record in records if record.player_id == target_player_id), None)
    if target is None:
        return []
    weights = _MODE_WEIGHTS[mode]
    stats_records = [
        SimilarityRecord(
            record.player_id,
            record.full_name,
            record.position,
            _mode_features(record),
            record.value_pct,
            record.salary_pct,
            record.actual_usd,
            record.gap_pct,
        )
        for record in records
    ]
    stats = _mean_std(stats_records, list(weights))
    scored: list[SimilarityScore] = []
    for candidate in records:
        if not _eligible(target, candidate, mode):
            continue
        score = _score_pair(target, candidate, mode, stats)
        deltas = {
            key: val
            for key in ["age", "pts_pg", "ast_pg", "reb_pg", "USG_PCT", "TS_PCT", "BPM", "value_pct", "salary_pct", "gap_pct"]
            if (val := _delta(target, candidate, key)) is not None
        }
        scored.append(SimilarityScore(
            record=candidate,
            score=score,
            explanation_tags=_tags(target, candidate, mode, score),
            deltas=deltas,
        ))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]
