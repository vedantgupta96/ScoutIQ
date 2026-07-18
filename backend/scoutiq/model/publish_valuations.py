"""Publish precomputed player valuations to Postgres.

Runs the valuation model once over every loaded player-season and upserts the results
into `player_valuations`, so API reads become indexed SELECTs instead of per-request
inference. Run after any ETL load or model retrain (model.train chains it by default):

    python -m scoutiq.model.publish_valuations                 # all loaded seasons
    python -m scoutiq.model.publish_valuations --season 2025-26

Deterministic and idempotent: re-running with unchanged data/model rewrites identical
rows with a fresh computed_at. Verdict and card-stat semantics come from
`scoutiq.api.valuation` so published rows match what live fallback would compute.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from scoutiq.api.valuation import card_stats_from_features, valuation_verdict
from scoutiq.db import get_session
from scoutiq.model.predict import (
    build_features_from_season,
    predict_many_from_features,
    prev_season_label,
    previous_seasons_for,
)
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason, PlayerValuation

# Watchlist qualification floors (mirrors the watchlist candidate query).
QUALIFIED_MIN_GP = 20
QUALIFIED_MIN_MINUTES = 600

# Card stat keys that get a league percentile, and the minimum peer-set size below
# which percentiles are withheld (mirrors the watchlist's annotation rules).
PCTL_KEYS = ("gp", "mpg", "pts_pg", "reb_pg", "ast_pg", "bpm")
PCTL_MIN_PEERS = 20


def annotate_percentiles(stats_list: list[dict]) -> None:
    """Stamp league percentile ranks (mid-rank for ties) onto card-stat dicts in place."""
    if len(stats_list) < PCTL_MIN_PEERS:
        return

    sorted_by_key: dict[str, list[float]] = {}
    for key in PCTL_KEYS:
        values = sorted(
            value for stats in stats_list
            if (value := stats.get(key)) is not None
        )
        if len(values) >= PCTL_MIN_PEERS:
            sorted_by_key[key] = values

    for stats in stats_list:
        pctl: dict[str, int] = {}
        for key, values in sorted_by_key.items():
            value = stats.get(key)
            if value is None:
                continue
            mid_rank = (bisect_left(values, value) + bisect_right(values, value)) / 2
            pctl[key] = round(100 * mid_rank / len(values))
        stats["pctl"] = pctl or None


def build_season_rows(db: Session, season: str, computed_at: datetime) -> list[dict]:
    """Compute one season's valuation rows (one model batch, no writes)."""
    season_rows = db.scalars(
        select(PlayerSeason).where(PlayerSeason.season == season)
    ).all()
    if not season_rows:
        return []

    player_ids = [row.player_id for row in season_rows]
    players_by_id = {
        player.player_id: player
        for player in db.scalars(
            select(Player).where(Player.player_id.in_(player_ids))
        ).all()
    }
    prev_by_key = previous_seasons_for(season_rows, db)
    salary_by_player = {
        row.player_id: row.salary
        for row in db.scalars(
            select(PlayerSalary)
            .where(PlayerSalary.player_id.in_(player_ids))
            .where(PlayerSalary.season == season)
        ).all()
    }
    cap_row = db.get(CapConstants, season)
    salary_cap = cap_row.salary_cap if cap_row else None

    feature_rows: list[dict] = []
    kept: list[PlayerSeason] = []
    for row in season_rows:
        player = players_by_id.get(row.player_id)
        if player is None:
            continue
        prev = prev_by_key.get((row.player_id, prev_season_label(season)))
        feature_rows.append(build_features_from_season(row, player, prev=prev))
        kept.append(row)

    predictions = predict_many_from_features(feature_rows)

    values: list[dict] = []
    for row, features, prediction in zip(kept, feature_rows, predictions):
        actual_usd = salary_by_player.get(row.player_id)
        actual_pct = (
            round(actual_usd / salary_cap * 100, 2) if (actual_usd and salary_cap) else None
        )
        value_pct = prediction["value_pct"]
        gap_pct = round(value_pct - actual_pct, 2) if actual_pct is not None else None
        verdict_label, verdict_tone, caution_flags, caveat = valuation_verdict(
            gap_pct=gap_pct, actual_pct=actual_pct, features=features
        )
        qualified = bool(
            (row.gp or 0) >= QUALIFIED_MIN_GP
            and float(row.minutes or 0) >= QUALIFIED_MIN_MINUTES
        )
        stats = card_stats_from_features(features)
        values.append({
            "player_id": row.player_id,
            "season": season,
            "value_pct": value_pct,
            "lo_pct": prediction["lo_pct"],
            "hi_pct": prediction["hi_pct"],
            "actual_usd": actual_usd,
            "actual_pct": actual_pct,
            "gap_pct": gap_pct,
            "qualified": qualified,
            "verdict_label": verdict_label,
            "verdict_tone": verdict_tone,
            "caution_flags": caution_flags,
            "caveat": caveat,
            "stats": stats.model_dump() if stats else None,
            "features": features,
            "model_version": prediction["model_version"],
            "computed_at": computed_at,
        })

    # League percentiles across the season's qualified, valued peers — the same pool
    # the watchlist qualifies, so stored percentiles match what the board shows.
    qualified_stats = [v["stats"] for v in values if v["qualified"] and v["stats"]]
    annotate_percentiles(qualified_stats)
    return values


def upsert_rows(db: Session, values: list[dict]) -> None:
    if not values:
        return
    stmt = pg_insert(PlayerValuation).values(values)
    update_cols = {
        col: stmt.excluded[col]
        for col in values[0]
        if col not in ("player_id", "season")
    }
    db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_player_valuation_season", set_=update_cols
        )
    )


def publish(seasons: list[str] | None = None) -> int:
    computed_at = datetime.now(timezone.utc)
    total = 0
    with get_session() as db:
        if not seasons:
            seasons = sorted(
                db.scalars(select(PlayerSeason.season).distinct()).all()
            )
        for season in seasons:
            values = build_season_rows(db, season, computed_at)
            upsert_rows(db, values)
            total += len(values)
            print(f"  {season}: {len(values)} valuations")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish precomputed valuations to Postgres.")
    parser.add_argument(
        "--season", action="append", dest="seasons", metavar="YYYY-YY",
        help="Season to publish (repeatable). Default: every season with loaded stats.",
    )
    args = parser.parse_args()
    total = publish(args.seasons)
    print(f"publish_valuations: upserted {total} rows")


if __name__ == "__main__":
    main()
