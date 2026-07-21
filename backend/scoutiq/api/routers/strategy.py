"""Strategy Lab — backtest a roster-building strategy over historical NBA seasons (docs/10).

POST /strategy/backtest runs a StrategySpec against the cached historical panel and returns
realized-surplus performance vs benchmarks. GET /strategy/presets and /strategy/meta drive
the builder UI.
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from scoutiq.api.deps import DB
from scoutiq.backtest.engine import SIGNALS, StrategySpec, run_backtest
from scoutiq.backtest.panel import build_panel

router = APIRouter(prefix="/strategy", tags=["strategy"])

PANEL_CACHE_SECONDS = 3600
_panel_cache: dict[object, tuple[float, object]] = {}
_panel_lock = threading.Lock()


def _bind(db: DB) -> object:
    try:
        return db.get_bind()
    except AttributeError:
        return db


def _cached_panel(db: DB):
    key = _bind(db)
    now = time.monotonic()
    with _panel_lock:
        hit = _panel_cache.get(key)
        if hit and now - hit[0] < PANEL_CACHE_SECONDS:
            return hit[1]
    panel = build_panel(db)
    with _panel_lock:
        _panel_cache[key] = (time.monotonic(), panel)
    return panel


class StrategyRequest(BaseModel):
    min_mpg: float = Field(20.0, ge=0, le=48)
    min_gp: int = Field(40, ge=0, le=82)
    min_age: int | None = Field(None, ge=17, le=45)
    max_age: int | None = Field(None, ge=17, le=45)
    positions: list[str] | None = None
    min_bpm: float | None = Field(None, ge=-15, le=20)
    require_undervalued: bool = False
    min_value_pct: float | None = Field(None, ge=0, le=100)
    signal: str = "gap"
    portfolio_size: int = Field(10, ge=1, le=30)
    horizon: int = Field(3, ge=1, le=5)
    start_season: str | None = None
    end_season: str | None = None

    def to_spec(self) -> StrategySpec:
        signal = self.signal if self.signal in SIGNALS else "gap"
        return StrategySpec(
            min_mpg=self.min_mpg, min_gp=self.min_gp, min_age=self.min_age, max_age=self.max_age,
            positions=tuple(self.positions) if self.positions else None,
            min_bpm=self.min_bpm, require_undervalued=self.require_undervalued,
            min_value_pct=self.min_value_pct, signal=signal,
            portfolio_size=self.portfolio_size, horizon=self.horizon,
            start_season=self.start_season, end_season=self.end_season,
        )


PRESETS = [
    {
        "id": "value",
        "name": "Value — most undervalued",
        "description": "Buy the biggest model bargains among rotation players; hold 3 seasons.",
        "spec": {"signal": "gap", "require_undervalued": True, "portfolio_size": 10, "horizon": 3},
    },
    {
        "id": "youth-upside",
        "name": "Youth upside",
        "description": "Undervalued players 23 or younger — bet on bargains that grow.",
        "spec": {"signal": "gap", "require_undervalued": True, "max_age": 23, "portfolio_size": 10, "horizon": 3},
    },
    {
        "id": "chase-production",
        "name": "Chase production",
        "description": "Sign the highest Win-Shares players regardless of cost (a naive baseline).",
        "spec": {"signal": "ws", "portfolio_size": 10, "horizon": 3},
    },
    {
        "id": "two-way-value",
        "name": "Two-way value",
        "description": "Undervalued players with a real defensive/all-around edge (BPM ≥ 2).",
        "spec": {"signal": "gap", "require_undervalued": True, "min_bpm": 2.0, "portfolio_size": 10, "horizon": 3},
    },
]


@router.get("/presets")
def get_presets():
    return {"presets": PRESETS, "signals": list(SIGNALS)}


@router.get("/meta")
def get_meta(db: DB = None):
    panel = _cached_panel(db)
    decisionable = [s for s in panel.seasons if panel.has_future(s)]
    return {
        "seasons": panel.seasons,
        "decision_seasons": decisionable,
        "signals": list(SIGNALS),
        "n_player_seasons": len(panel.rows),
        "pct_of_cap_per_win": None,  # anchor is a fixed documented constant (engine.PCT_OF_CAP_PER_WIN)
    }


@router.post("/backtest")
def post_backtest(req: StrategyRequest, db: DB = None):
    panel = _cached_panel(db)
    result = run_backtest(panel, req.to_spec())
    return vars(result)
