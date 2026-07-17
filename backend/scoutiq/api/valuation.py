"""Valuation — the one module that produces player valuations.

Every API surface gets valuations from here; none re-assembles the pipeline. Degrade
contract (ADR-0001): a missing model artifact yields empty results, a target without a
stats season is absent from the result; callers render without valuations.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel
from sqlalchemy import select

from scoutiq.api.deps import DB
from scoutiq.model.predict import (
    attribute_prediction,
    build_features_from_season,
    predict_from_features,
    predict_many_from_features,
    prev_season_label,
    previous_seasons_for,
)
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason

Target = tuple[int, str]


class PlayerCardStats(BaseModel):
    """Compact production context for card surfaces; season-consistent with the valuation."""

    gp: int | None
    mpg: float | None
    pts_pg: float | None
    reb_pg: float | None
    ast_pg: float | None
    ts_pct: float | None
    bpm: float | None
    # League percentile (0-100) per stat key, computed across the watchlist's
    # full valued candidate set. Absent when the peer set is too small.
    pctl: dict[str, int] | None = None


class Valuation(BaseModel):
    season: str
    value_pct: float
    lo_pct: float
    hi_pct: float
    actual_usd: int | None
    actual_pct: float | None
    gap_pct: float | None
    salary_cap: int | None
    value_usd: int | None
    model_version: str
    verdict_label: str
    verdict_tone: str
    caution_flags: list[str]
    caveat: str | None
    stats: PlayerCardStats | None = None


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def card_stats_from_features(features: dict) -> PlayerCardStats | None:
    """Pull the card's production line out of the already-built model features."""
    gp = _num(features.get("gp"))
    minutes = _num(features.get("minutes"))
    ts_pct = _num(features.get("TS_PCT"))

    def _rounded(key: str) -> float | None:
        value = _num(features.get(key))
        return round(value, 1) if value is not None else None

    stats = PlayerCardStats(
        gp=int(gp) if gp else None,
        mpg=round(minutes / gp, 1) if (minutes is not None and gp) else None,
        pts_pg=_rounded("pts_pg"),
        reb_pg=_rounded("reb_pg"),
        ast_pg=_rounded("ast_pg"),
        ts_pct=round(ts_pct, 3) if ts_pct is not None else None,
        bpm=_rounded("BPM"),
    )
    if all(value is None for value in stats.model_dump().values()):
        return None
    return stats


def classify_gap(gap_pct: float | None) -> tuple[str, str]:
    """The raw value-pay gap ladder, with no caution-flag interaction."""
    if gap_pct is None:
        return "No data", "neutral"
    if gap_pct >= 3:
        return "Significant bargain", "positive"
    if gap_pct >= 1:
        return "Bargain", "positive"
    if gap_pct > -1:
        return "Fair value", "neutral"
    if gap_pct > -3:
        return "Slight overpay", "negative"
    return "Overpaid", "negative"


def valuation_verdict(
    *,
    gap_pct: float | None,
    actual_pct: float | None,
    features: dict,
) -> tuple[str, str, list[str], str | None]:
    """Translate raw value-pay gap into a trust-aware display verdict.

    The raw model output stays untouched. This layer prevents cheap, high-usage
    players with weak impact indicators from reading as clean bargains.
    """
    if gap_pct is None:
        label, tone = classify_gap(None)
        return label, tone, [], None

    flags: list[str] = []
    age = _num(features.get("age"))
    bpm = _num(features.get("BPM"))
    ws48 = _num(features.get("WS48"))
    net_rating = _num(features.get("NET_RATING"))
    ts_pct = _num(features.get("TS_PCT"))
    usg_pct = _num(features.get("USG_PCT"))

    if age is not None and age >= 35:
        flags.append("Age 35+")
    if actual_pct is not None and actual_pct < 3 and gap_pct >= 8:
        flags.append("Minimum-salary gap")
    if bpm is not None and bpm < 0:
        flags.append("Negative BPM")
    if ws48 is not None and ws48 < 0.05:
        flags.append("Low WS/48")
    if net_rating is not None and net_rating <= -5:
        flags.append("Poor on-court net")
    if ts_pct is not None and usg_pct is not None and ts_pct < 0.54 and usg_pct >= 0.22:
        flags.append("High-use efficiency risk")

    if gap_pct >= 3:
        if flags:
            return (
                "Salary bargain",
                "warning",
                flags,
                "Large positive gap is driven by pay versus box production; impact indicators are mixed.",
            )
        label, tone = classify_gap(gap_pct)
        return label, tone, [], None
    if gap_pct >= 1:
        if flags:
            return (
                "Bargain, monitor impact",
                "warning",
                flags,
                "Positive gap has production support, but impact indicators need review.",
            )
        label, tone = classify_gap(gap_pct)
        return label, tone, [], None
    label, tone = classify_gap(gap_pct)
    return label, tone, flags, None


def _assemble_valuation(
    season: str,
    prediction: dict,
    features: dict,
    salary_row: PlayerSalary | None,
    cap_row: CapConstants | None,
) -> Valuation:
    salary_cap = cap_row.salary_cap if cap_row else None
    actual_usd = salary_row.salary if salary_row else None
    actual_pct = round(actual_usd / salary_cap * 100, 2) if (actual_usd and salary_cap) else None
    value_pct = prediction["value_pct"]
    gap_pct = round(value_pct - actual_pct, 2) if actual_pct is not None else None
    verdict_label, verdict_tone, caution_flags, caveat = valuation_verdict(
        gap_pct=gap_pct,
        actual_pct=actual_pct,
        features=features,
    )
    return Valuation(
        season=season,
        value_pct=value_pct,
        lo_pct=prediction["lo_pct"],
        hi_pct=prediction["hi_pct"],
        actual_usd=actual_usd,
        actual_pct=actual_pct,
        gap_pct=gap_pct,
        salary_cap=salary_cap,
        value_usd=int(round(value_pct / 100 * salary_cap)) if salary_cap else None,
        model_version=prediction["model_version"],
        verdict_label=verdict_label,
        verdict_tone=verdict_tone,
        caution_flags=caution_flags,
        caveat=caveat,
        stats=card_stats_from_features(features),
    )


def value_players(db: DB, targets: Iterable[Target]) -> dict[Target, Valuation]:
    """Batch-value every (player_id, season) target in one round of queries."""
    targets = list(dict.fromkeys(targets))
    if not targets:
        return {}

    player_ids = sorted({player_id for player_id, _ in targets})
    seasons = sorted({season for _, season in targets})
    target_set = set(targets)

    season_rows = db.scalars(
        select(PlayerSeason)
        .where(PlayerSeason.player_id.in_(player_ids))
        .where(PlayerSeason.season.in_(seasons))
    ).all()
    season_by_key = {
        (row.player_id, row.season): row
        for row in season_rows
        if (row.player_id, row.season) in target_set
    }

    players = db.scalars(select(Player).where(Player.player_id.in_(player_ids))).all()
    player_by_id = {player.player_id: player for player in players}
    prev_by_key = previous_seasons_for(list(season_by_key.values()), db)

    salary_rows = db.scalars(
        select(PlayerSalary)
        .where(PlayerSalary.player_id.in_(player_ids))
        .where(PlayerSalary.season.in_(seasons))
    ).all()
    salary_by_key = {(row.player_id, row.season): row for row in salary_rows}

    cap_rows = db.scalars(select(CapConstants).where(CapConstants.season.in_(seasons))).all()
    cap_by_season = {row.season: row for row in cap_rows}

    feature_rows: list[dict] = []
    feature_keys: list[Target] = []
    for target in targets:
        season_row = season_by_key.get(target)
        if season_row is None:
            continue
        player_id, season = target
        prev = prev_by_key.get((player_id, prev_season_label(season)))
        feature_rows.append(build_features_from_season(season_row, player_by_id.get(player_id), prev=prev))
        feature_keys.append(target)

    try:
        predictions = predict_many_from_features(feature_rows)
    except FileNotFoundError:
        return {}

    features_by_key = dict(zip(feature_keys, feature_rows))
    valuations: dict[Target, Valuation] = {}
    for target, prediction in zip(feature_keys, predictions):
        _, season = target
        valuations[target] = _assemble_valuation(
            season,
            prediction,
            features_by_key[target],
            salary_by_key.get(target),
            cap_by_season.get(season),
        )
    return valuations


def value_player_detail(db: DB, player_id: int, season: str) -> tuple[Valuation, dict, list | None]:
    """Full single-player valuation: the model's feature row, prediction, and attribution.

    Raises LookupError if `season` has no loaded stats for this player; lets
    FileNotFoundError (missing model artifact) propagate to the caller.
    """
    season_row = db.scalars(
        select(PlayerSeason).where(
            PlayerSeason.player_id == player_id,
            PlayerSeason.season == season,
        )
    ).first()
    if season_row is None:
        raise LookupError(f"No stats for player_id={player_id} in season {season}.")

    player = db.get(Player, player_id)
    prev_by_key = previous_seasons_for([season_row], db)
    prev = prev_by_key.get((player_id, prev_season_label(season)))
    features = build_features_from_season(season_row, player, prev=prev)
    prediction = predict_from_features(features)

    salary_row = db.scalars(
        select(PlayerSalary).where(
            PlayerSalary.player_id == player_id,
            PlayerSalary.season == season,
        )
    ).first()
    cap_row = db.get(CapConstants, season)
    valuation = _assemble_valuation(season, prediction, features, salary_row, cap_row)
    normalized_features = {k: (None if v != v else v) for k, v in features.items()}
    attribution = attribute_prediction(features)
    return valuation, normalized_features, attribution
