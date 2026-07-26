"""Rolling-origin (expanding-window) folds over target seasons.

A fold trains on every target season strictly before its validation target, so
no future season can leak into training or calibration. Fold definitions are a
pure, deterministic function of the sorted target seasons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd


@dataclass(frozen=True)
class Fold:
    train_targets: tuple[str, ...]
    val_target: str


def rolling_origin_folds(target_seasons: Sequence[str], min_train_seasons: int = 3) -> list[Fold]:
    """Fold i trains on the first i target seasons and validates on the (i+1)-th.
    Every ``val_target`` is strictly greater than all of its ``train_targets``
    (season strings sort chronologically), so validation is always out-of-time.
    """
    if min_train_seasons < 1:
        raise ValueError("min_train_seasons must be >= 1")
    ordered = sorted(set(target_seasons))
    return [Fold(tuple(ordered[:i]), ordered[i]) for i in range(min_train_seasons, len(ordered))]


def fold_frames(df: pd.DataFrame, fold: Fold) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split the modeling table into (train, val) for one fold using the target
    season column ``next_season``. Train rows all have a target strictly before
    the validation target — the leakage guarantee, enforced here in one place.
    """
    train = df[df["next_season"].isin(fold.train_targets)]
    val = df[df["next_season"] == fold.val_target]
    return train, val
