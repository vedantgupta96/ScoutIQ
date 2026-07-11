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
from sqlalchemy.orm import Session

from scoutiq.model.features import (
    BBREF_ADV,
    FEATURE_COLS,
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


def build_features_from_season(ps: PlayerSeason, player: Player | None) -> dict[str, Any]:
    """Build model features from already-loaded ORM rows."""
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

    pos = primary_position(player.position) if player else None
    for p in POSITIONS:
        features[f"pos_{p}"] = 1.0 if pos == p else 0.0

    return features


def predict_many_from_features(feature_rows: list[dict[str, Any]]) -> list[dict]:
    """Vectorized prediction for batch API responses."""
    if not feature_rows:
        return []
    art = load_artifact()
    df = pd.DataFrame(feature_rows).reindex(columns=FEATURE_COLS)
    preds = art["model"].predict(df)
    qhat = art["qhat_80"]
    return [
        {
            "value_pct": round(float(pred) * 100, 2),
            "lo_pct": round(max(float(pred) - qhat, 0.0) * 100, 2),
            "hi_pct": round((float(pred) + qhat) * 100, 2),
            "model_version": art["version"],
        }
        for pred in preds
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

    player = session.get(Player, player_id)
    return build_features_from_season(ps, player)


def predict_for_player(player_id: int, season: str, session: Session) -> dict:
    """End-to-end: player_id + season → full prediction dict including feature values."""
    features = build_player_features(player_id, season, session)
    result = predict_from_features(features)
    result["features"] = {k: (None if (v is None or (isinstance(v, float) and math.isnan(v))) else v)
                          for k, v in features.items()}
    return result
