"""Model inference — load the joblib artifact and produce predictions.

Two entry points:
  predict_from_features(features): raw dict → prediction dict (no DB needed)
  predict_for_player(player_id, season, session): fetches stats from DB, calls above

The model artifact is loaded once and cached module-level (singleton pattern).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoutiq.model.features import (
    BBREF_ADV,
    FEATURE_COLS,
    LAG_SRC,
    NBA_ADV,
    POSITIONS,
    primary_position,
)
from scoutiq.models import Player, PlayerSeason

ART = Path(__file__).parent / "artifacts"

_PER_GAME_SRC = {
    "pts_pg": "PTS",
    "reb_pg": "REB",
    "ast_pg": "AST",
    "stl_pg": "STL",
    "blk_pg": "BLK",
    "tov_pg": "TOV",
    "fg3m_pg": "FG3M",
}

_artifact: dict | None = None


def load_artifact() -> dict:
    global _artifact
    if _artifact is None:
        path = ART / "model.joblib"
        if not path.exists():
            raise FileNotFoundError(
                f"model.joblib not found at {path}. "
                "Run `python -m scoutiq.model.train` to generate it."
            )
        _artifact = joblib.load(path)
    return _artifact


def predict_from_features(features: dict[str, Any]) -> dict:
    """Raw feature dict → prediction dict.

    Missing features should be None / NaN — HistGradientBoosting handles them natively.
    Returns value_pct, lo_pct, hi_pct (all as % of cap, e.g. 18.5 means 18.5%).
    """
    return predict_many_from_features([features])[0]


def _as_float(value: Any) -> float | None:
    """Stat inputs are loosely typed — bbref loads store some numerics as strings
    (e.g. BPM "0.5", WS48 ".116") and Numeric columns yield Decimal. Coerce or
    drop, so every downstream consumer (model, API responses, verdict flags)
    sees float | None."""
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def prev_season_label(season: str) -> str:
    """'2025-26' -> '2024-25'."""
    start = int(season[:4])
    return f"{start - 1}-{str(start)[2:]}"


def previous_seasons_for(
    season_rows: list[PlayerSeason], session: Session
) -> dict[tuple[int, str], PlayerSeason]:
    """Load the exact prior-season rows needed by a batch in one query."""
    if not season_rows:
        return {}
    player_ids = {row.player_id for row in season_rows}
    seasons = {prev_season_label(row.season) for row in season_rows}
    rows = session.scalars(
        select(PlayerSeason).where(
            PlayerSeason.player_id.in_(player_ids),
            PlayerSeason.season.in_(seasons),
        )
    ).all()
    return {(row.player_id, row.season): row for row in rows}


def _season_stat(ps: PlayerSeason, key: str) -> float | None:
    """One coerced stat off a season row, per-game where the key demands it."""
    gp = ps.gp or 0
    if key == "gp":
        return float(gp)
    if key == "minutes":
        return _as_float(ps.minutes)
    if key in _PER_GAME_SRC:
        val = _as_float((ps.box or {}).get(_PER_GAME_SRC[key]))
        return val / gp if (val is not None and gp > 0) else None
    return _as_float((ps.advanced or {}).get(key))


def build_features_from_season(
    ps: PlayerSeason,
    player: Player | None,
    prev: PlayerSeason | None = None,
) -> dict[str, Any]:
    """Build model features from already-loaded ORM rows.

    `prev` is the same player's previous season row; without it the lag features
    are None, which the model treats as "no known history" (rookie state).
    """
    box = ps.box or {}
    adv = ps.advanced or {}
    gp = ps.gp or 0

    features: dict[str, Any] = {
        "age": ps.age,
        "gp": gp,
        "minutes": _as_float(ps.minutes),
    }

    for col, src in _PER_GAME_SRC.items():
        val = _as_float(box.get(src))
        features[col] = val / gp if (val is not None and gp > 0) else None

    for col in NBA_ADV:
        features[col] = _as_float(adv.get(col))

    for col in BBREF_ADV:
        features[col] = _as_float(adv.get(col))

    for col in LAG_SRC:
        features[f"lag_{col}"] = _season_stat(prev, col) if prev is not None else None
    features["d_pts_pg"] = (
        features["pts_pg"] - features["lag_pts_pg"]
        if features["pts_pg"] is not None and features["lag_pts_pg"] is not None
        else None
    )
    features["gp_2yr"] = float(gp) + (features["lag_gp"] or 0.0)

    pos = primary_position(player.position) if player else None
    for p in POSITIONS:
        features[f"pos_{p}"] = 1.0 if pos == p else 0.0

    return features


def predict_many_from_features(feature_rows: list[dict[str, Any]]) -> list[dict]:
    """Vectorized prediction for batch API responses.

    v1 artifacts carry CQR quantile models, so intervals are per-player
    (adaptive); v0 artifacts fall back to the fixed conformal half-width.
    """
    if not feature_rows:
        return []
    art = load_artifact()
    df = pd.DataFrame(feature_rows).reindex(columns=FEATURE_COLS)
    preds = art["model"].predict(df)

    if "model_lo" in art:
        qhat = art["cqr_qhat_80"]
        lo = art["model_lo"].predict(df) - qhat
        hi = art["model_hi"].predict(df) + qhat
        # Quantile crossing is rare but possible; keep the band around the point.
        lo = np.minimum(lo, preds)
        hi = np.maximum(hi, preds)
    else:
        qhat = art["qhat_80"]
        lo, hi = preds - qhat, preds + qhat

    return [
        {
            "value_pct": round(float(pred) * 100, 2),
            "lo_pct": round(max(float(l), 0.0) * 100, 2),
            "hi_pct": round(float(h) * 100, 2),
            "model_version": art["version"],
        }
        for pred, l, h in zip(preds, lo, hi)
    ]


# Feature groups for deterministic attribution: swap a group to the league-median
# profile and read the prediction delta. Grouped (not per-feature) because the
# UI answer is "what drives this value", not 30 correlated micro-effects.
ATTRIBUTION_GROUPS: dict[str, tuple[str, list[str]]] = {
    "scoring": ("Scoring volume", ["pts_pg", "fg3m_pg"]),
    "efficiency": ("Scoring efficiency", ["TS_PCT", "EFG_PCT", "USG_PCT"]),
    "playmaking": ("Playmaking", ["ast_pg", "AST_PCT", "tov_pg", "TM_TOV_PCT"]),
    "rebounding": ("Rebounding", ["reb_pg", "REB_PCT", "OREB_PCT", "DREB_PCT"]),
    "impact": ("Defense & impact", [
        "stl_pg", "blk_pg", "BPM", "OBPM", "DBPM", "VORP", "WS", "WS48", "PER",
        "PIE", "OFF_RATING", "DEF_RATING", "NET_RATING",
    ]),
    "availability": ("Availability", ["gp", "minutes", "gp_2yr"]),
    "trajectory": ("Trajectory", [f"lag_{c}" for c in LAG_SRC] + ["d_pts_pg"]),
    "age": ("Age", ["age"]),
}


def attribute_prediction(features: dict[str, Any]) -> list[dict] | None:
    """Grouped occlusion attribution vs the league-median profile.

    For each group, replace the player's values with training medians and
    report the prediction delta: "+2.1% of cap from scoring volume". Deltas
    do not sum exactly to the total (feature interactions); consumers should
    present them as drivers, not a ledger.
    """
    art = load_artifact()
    medians = art.get("feature_medians")
    if not medians:
        return None

    rows = [dict(features)]
    keys = list(ATTRIBUTION_GROUPS.keys())
    for key in keys:
        occluded = dict(features)
        for col in ATTRIBUTION_GROUPS[key][1]:
            occluded[col] = medians.get(col)
        rows.append(occluded)

    df = pd.DataFrame(rows).reindex(columns=FEATURE_COLS)
    preds = art["model"].predict(df)
    base = float(preds[0])
    return [
        {
            "group": key,
            "label": ATTRIBUTION_GROUPS[key][0],
            "delta_pct": round((base - float(preds[i + 1])) * 100, 2),
        }
        for i, key in enumerate(keys)
    ]


def build_player_features(player_id: int, season: str, session: Session) -> dict[str, Any]:
    """Fetch a player+season from the DB and return a feature dict ready for predict_from_features."""
    from sqlalchemy import select
    ps = session.scalars(
        select(PlayerSeason).where(
            PlayerSeason.player_id == player_id,
            PlayerSeason.season == season,
        )
    ).first()
    if ps is None:
        raise LookupError(f"No stats for player_id={player_id} season={season}")

    prev = session.scalars(
        select(PlayerSeason).where(
            PlayerSeason.player_id == player_id,
            PlayerSeason.season == prev_season_label(season),
        )
    ).first()
    player = session.get(Player, player_id)
    return build_features_from_season(ps, player, prev=prev)


def predict_for_player(player_id: int, season: str, session: Session) -> dict:
    """End-to-end: player_id + season → full prediction dict including feature values."""
    features = build_player_features(player_id, season, session)
    result = predict_from_features(features)
    result["features"] = {k: (None if (v is None or (isinstance(v, float) and math.isnan(v))) else v)
                          for k, v in features.items()}
    return result
