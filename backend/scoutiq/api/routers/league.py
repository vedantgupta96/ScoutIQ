"""GET /league/cap-landscape — every team's cap position for a season, at a glance.

Runs the per-team cap-sheet computation from teams.py across every team in one batch
(no per-team queries), producing the tier distribution and a sortable payroll table
the /league route renders.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from scoutiq.api import rosters
from scoutiq.api.cap import TIER_ORDER, apron_values, classify_tier, room_to_lines
from scoutiq.api.deps import DB
from scoutiq.api.season import LATEST_SEASON, is_valid_season, next_season
from scoutiq.api.valuation import value_players
from scoutiq.models import CapConstants, Contract, ContractYear, Player, Team

router = APIRouter(prefix="/league", tags=["league"])

CAVEAT = (
    "Payroll uses the contract-year cap hit for the season (later contracts win) or "
    "realized salary otherwise. Expiring salary is money with no contract-year in the "
    "following season. Tax/apron thresholds are the stored season values; apron proxies "
    "are used where exact figures are unpublished. Surplus is total model value minus "
    "payroll and is separate from cap compliance."
)


class LeagueTeamRow(BaseModel):
    team: rosters.TeamSummary
    tier: str
    total_payroll_usd: int
    payroll_pct: float | None
    room_to_cap_usd: int | None
    room_to_tax_usd: int | None
    room_to_first_apron_usd: int | None
    room_to_second_apron_usd: int | None
    total_value_usd: int
    surplus_usd: int
    surplus_pct: float | None
    expiring_usd: int
    expiring_pct: float | None
    roster_size: int
    payroll_player_count: int


class LeagueCapContext(BaseModel):
    season: str
    salary_cap: int | None
    tax_line: int | None
    first_apron: int | None
    second_apron: int | None


class LeagueCapResponse(BaseModel):
    context: LeagueCapContext
    tier_counts: dict[str, int]
    teams_with_cap_room: int
    league_expiring_usd: int
    team_count: int
    teams: list[LeagueTeamRow]
    caveat: str


@router.get("/cap-landscape", response_model=LeagueCapResponse)
def get_league_cap_landscape(season: str | None = Query(None), db: DB = None):
    """League-wide cap tier distribution + per-team payroll/value table."""
    if season is not None and not is_valid_season(season):
        raise HTTPException(
            status_code=422, detail="season must be a 'YYYY-YY' label, e.g. '2025-26'."
        )
    target = season or LATEST_SEASON

    cap_row = db.scalars(select(CapConstants).where(CapConstants.season == target)).first()
    salary_cap = cap_row.salary_cap if cap_row else None
    tax_line = cap_row.tax_line if cap_row else None
    first_apron, second_apron = apron_values(cap_row)

    teams = db.scalars(select(Team)).all()

    roster = db.scalars(select(Player).where(Player.current_team_id.isnot(None))).all()
    ids_by_team: dict[int, list[int]] = {}
    all_ids: list[int] = []
    for p in roster:
        ids_by_team.setdefault(p.current_team_id, []).append(p.player_id)
        all_ids.append(p.player_id)

    cap_hit_by_player, _ = rosters.team_cap_hits(db, all_ids, target)
    vals = value_players(db, [(pid, target) for pid in all_ids])
    value_by_player = {pid: vals.get((pid, target)) for pid in all_ids}

    has_next: set[int] = set()
    if all_ids:
        nxt = next_season(target)
        rows = db.execute(
            select(Contract.player_id)
            .join(ContractYear, ContractYear.contract_id == Contract.id)
            .where(Contract.player_id.in_(all_ids))
            .where(ContractYear.season == nxt)
        ).all()
        has_next = {pid for (pid,) in rows}

    league_rows: list[LeagueTeamRow] = []
    for team in teams:
        team_ids = ids_by_team.get(team.team_id, [])

        total_payroll = sum(cap_hit_by_player.get(pid, 0) for pid in team_ids)
        payroll_count = sum(1 for pid in team_ids if cap_hit_by_player.get(pid))

        total_value = sum(
            value_by_player[pid].value_usd
            for pid in team_ids
            if value_by_player.get(pid) is not None and value_by_player[pid].value_usd is not None
        )
        surplus = total_value - total_payroll

        expiring = sum(
            cap_hit_by_player.get(pid, 0)
            for pid in team_ids
            if cap_hit_by_player.get(pid) and pid not in has_next
        )

        tier = classify_tier(total_payroll, tax_line, first_apron, second_apron)
        rooms = room_to_lines(
            total_payroll,
            salary_cap=salary_cap,
            tax_line=tax_line,
            first_apron=first_apron,
            second_apron=second_apron,
        )

        payroll_pct = round(total_payroll / salary_cap * 100, 2) if salary_cap else None
        surplus_pct = round(surplus / salary_cap * 100, 2) if salary_cap else None
        expiring_pct = round(expiring / salary_cap * 100, 2) if salary_cap else None

        league_rows.append(
            LeagueTeamRow(
                team=rosters.team_summary(team),
                tier=tier,
                total_payroll_usd=total_payroll,
                payroll_pct=payroll_pct,
                room_to_cap_usd=rooms.room_to_cap,
                room_to_tax_usd=rooms.room_to_tax,
                room_to_first_apron_usd=rooms.room_to_first_apron,
                room_to_second_apron_usd=rooms.room_to_second_apron,
                total_value_usd=total_value,
                surplus_usd=surplus,
                surplus_pct=surplus_pct,
                expiring_usd=expiring,
                expiring_pct=expiring_pct,
                roster_size=len(team_ids),
                payroll_player_count=payroll_count,
            )
        )

    league_rows.sort(key=lambda r: r.total_payroll_usd, reverse=True)

    tier_counts = {t: 0 for t in TIER_ORDER}
    for row in league_rows:
        tier_counts[row.tier] += 1

    teams_with_cap_room = sum(
        1 for row in league_rows if row.room_to_cap_usd is not None and row.room_to_cap_usd > 0
    )
    league_expiring_usd = sum(row.expiring_usd for row in league_rows)

    return LeagueCapResponse(
        context=LeagueCapContext(
            season=target,
            salary_cap=salary_cap,
            tax_line=tax_line,
            first_apron=first_apron,
            second_apron=second_apron,
        ),
        tier_counts=tier_counts,
        teams_with_cap_room=teams_with_cap_room,
        league_expiring_usd=league_expiring_usd,
        team_count=len(league_rows),
        teams=league_rows,
        caveat=CAVEAT,
    )
