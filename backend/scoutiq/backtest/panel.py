"""Build the backtest panel from Postgres (docs/10 §4).

Merges three existing tables into one player-season record — no new data:
- `player_seasons`  → age, gp, minutes, real production (WS / VORP / BPM)
- `player_valuations` → the model's as-of value signal (value_pct)
- `player_salaries` + `cap_constants` → salary as % of cap (the cost / grading input)

`actual_pct` is derived independently from salary ÷ cap (not from the valuation row) so the
grading side never depends on the model.
"""
from __future__ import annotations

from sqlalchemy import select

from scoutiq.api.deps import DB
from scoutiq.backtest.engine import Panel, SeasonStat, make_panel
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason, PlayerValuation


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def build_panel(db: DB) -> Panel:
    caps = {
        r.season: r.salary_cap
        for r in db.scalars(select(CapConstants)).all()
        if r.salary_cap
    }
    salaries = {
        (r.player_id, r.season): r.salary
        for r in db.scalars(select(PlayerSalary)).all()
        if r.salary
    }
    valuations = {
        (v.player_id, v.season): float(v.value_pct)
        for v in db.scalars(select(PlayerValuation)).all()
    }
    players = {p.player_id: p for p in db.scalars(select(Player)).all()}

    stats: list[SeasonStat] = []
    for ps in db.scalars(select(PlayerSeason)).all():
        adv = ps.advanced or {}
        cap = caps.get(ps.season)
        salary = salaries.get((ps.player_id, ps.season))
        actual_pct = round(salary / cap * 100, 2) if (salary and cap) else None
        value_pct = valuations.get((ps.player_id, ps.season))
        gap_pct = (
            round(value_pct - actual_pct, 2)
            if (value_pct is not None and actual_pct is not None)
            else None
        )
        player = players.get(ps.player_id)
        gp = ps.gp or 0
        minutes = float(ps.minutes or 0)
        stats.append(SeasonStat(
            player_id=ps.player_id,
            full_name=player.full_name if player else str(ps.player_id),
            season=ps.season,
            position=player.position if player else None,
            age=ps.age,
            gp=gp,
            mpg=round(minutes / gp, 1) if gp else 0.0,
            ws=_num(adv.get("WS")),
            vorp=_num(adv.get("VORP")),
            bpm=_num(adv.get("BPM")),
            value_pct=value_pct,
            actual_pct=actual_pct,
            gap_pct=gap_pct,
        ))
    return make_panel(stats)
