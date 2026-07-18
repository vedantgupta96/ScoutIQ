"""Read access to precomputed player valuations.

Routers ask this module for stored rows first and fall back to live model inference
only for keys that have no published row (e.g. mid-backfill, or a fake test session).
That keeps every endpoint correct with an empty table while making the populated
table the fast path in production.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from scoutiq.models import PlayerValuation

ValuationKey = tuple[int, str]  # (player_id, season)


def stored_valuations(
    db: Session, keys: Iterable[ValuationKey], *, with_features: bool = False
) -> dict[ValuationKey, PlayerValuation]:
    """Fetch published valuation rows for exactly the requested (player, season) keys.

    `features` is the widest column and only the player-profile valuation endpoint
    reads it, so it stays deferred unless explicitly requested — league-wide callers
    move ~40 floats × hundreds of players less over the wire.
    """
    wanted = {(pid, season) for pid, season in keys if season}
    if not wanted:
        return {}
    stmt = select(PlayerValuation).where(
        PlayerValuation.player_id.in_({pid for pid, _ in wanted}),
        PlayerValuation.season.in_({season for _, season in wanted}),
    )
    if not with_features:
        stmt = stmt.options(defer(PlayerValuation.features))
    rows = db.scalars(stmt).all()
    return {
        (row.player_id, row.season): row
        for row in rows
        if (row.player_id, row.season) in wanted
    }


def prediction_dict(row: PlayerValuation) -> dict:
    """Shape a stored row like the live `predict_many_from_features` output."""
    return {
        "value_pct": float(row.value_pct),
        "lo_pct": float(row.lo_pct),
        "hi_pct": float(row.hi_pct),
        "model_version": row.model_version,
    }
