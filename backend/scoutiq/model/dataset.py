"""Build the modeling table from the data layer.

One row per (player, season t) that is *trainable*: has BBRef advanced stats at t AND a known salary in
season t+1 (so the target exists). Strict temporal framing — every feature is from season t or earlier;
the target is season t+1 — so there is no leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scoutiq.config import settings
from scoutiq.db import engine
from scoutiq.model.features import LAG_SRC, NBA_ADV, BBREF_ADV, POSITIONS, primary_position

_PER_GAME_SRC = {
    "pts_pg": "PTS", "reb_pg": "REB", "ast_pg": "AST",
    "stl_pg": "STL", "blk_pg": "BLK", "tov_pg": "TOV", "fg3m_pg": "FG3M",
}


def build_dataset() -> pd.DataFrame:
    ps = pd.read_sql("select player_id, season, age, gp, minutes, box, advanced from player_seasons", engine)
    players = pd.read_sql("select player_id, full_name, position from players", engine)
    sal = pd.read_sql("select player_id, season, salary from player_salaries", engine)
    cap = pd.read_sql("select season, salary_cap from cap_constants", engine)

    seasons = settings.seasons
    next_season = {seasons[i]: seasons[i + 1] for i in range(len(seasons) - 1)}
    cap_map = cap.set_index("season")["salary_cap"]
    sal_map = sal.set_index(["player_id", "season"])["salary"]

    # expand JSONB dict columns into real columns
    box = pd.json_normalize(ps["box"].apply(lambda d: d or {}))
    adv = pd.json_normalize(ps["advanced"].apply(lambda d: d or {}))
    df = pd.concat(
        [ps.drop(columns=["box", "advanced"]).reset_index(drop=True),
         box.reset_index(drop=True), adv.reset_index(drop=True)],
        axis=1,
    )

    # per-game rates (guard against gp=0)
    gp = df["gp"].replace(0, np.nan)
    for col, src in _PER_GAME_SRC.items():
        df[col] = (df[src] / gp) if src in df.columns else np.nan

    # ensure every advanced feature column exists even if absent from all JSON
    for c in NBA_ADV + BBREF_ADV:
        if c not in df.columns:
            df[c] = np.nan

    # position one-hot
    df = df.merge(players, on="player_id", how="left")
    pos1 = df["position"].map(primary_position)
    for p in POSITIONS:
        df[f"pos_{p}"] = (pos1 == p).astype(float)

    # lagged season context: self-merge on (player, previous season)
    prev_season = {seasons[i + 1]: seasons[i] for i in range(len(seasons) - 1)}
    lag = df[["player_id", "season"] + LAG_SRC].copy()
    lag.columns = ["player_id", "lag_join_season"] + [f"lag_{c}" for c in LAG_SRC]
    df["lag_join_season"] = df["season"].map(prev_season)
    df = df.merge(lag, on=["player_id", "lag_join_season"], how="left")
    df = df.drop(columns=["lag_join_season"])
    df["d_pts_pg"] = df["pts_pg"] - df["lag_pts_pg"]
    df["gp_2yr"] = df["gp"].fillna(0) + df["lag_gp"].fillna(0)

    # contract-decision flag: the target season is the first year of a Spotrac
    # contract for this player — the rows where a valuation model is actionable.
    contracts = pd.read_sql("select player_id, season_start from contracts", engine)
    starts = set(zip(contracts["player_id"], contracts["season_start"]))

    # prior pay (feature) and next-season pay (target), both as % of that season's cap
    prior_salary = pd.Series(
        [sal_map.get((pid, s), np.nan) for pid, s in zip(df["player_id"], df["season"])],
        index=df.index,
    )
    df["prior_pct_cap"] = prior_salary / df["season"].map(cap_map)

    df["next_season"] = df["season"].map(next_season)
    df["target_cap"] = df["next_season"].map(cap_map)
    df["target_salary"] = pd.Series(
        [sal_map.get((pid, ns), np.nan) for pid, ns in zip(df["player_id"], df["next_season"])],
        index=df.index,
    )
    df["pct_cap_next"] = df["target_salary"] / df["target_cap"]

    df["decision_point"] = [
        (pid, ns) in starts for pid, ns in zip(df["player_id"], df["next_season"])
    ]

    # trainable rows only: target known AND BBRef advanced present
    df = df[df["pct_cap_next"].notna() & df["BPM"].notna()].reset_index(drop=True)
    return df
