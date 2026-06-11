"""GET /teams and /teams/{team_id}/cap-sheet — roster-level cap intelligence.

Rolls each team's roster up into a cap sheet: total payroll against the tax line
and the two aprons, plus per-player model value vs pay (bargain/overpay). This is
the team layer the single-player surfaces feed into, and where the apron
thresholds actually bind (a lone contract never reaches them).
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from scoutiq.api.cap_simulator import classify_tier
from scoutiq.api.deps import DB
from scoutiq.api.season import is_valid_season
from scoutiq.api.routers.players import (
    LATEST_SEASON,
    PlayerSummary,
    TeamSummary,
    _batched_summaries,
    _team_summary,
)
from scoutiq.model.predict import build_features_from_season, predict_many_from_features
from scoutiq.config import settings
from scoutiq.models import (
    CapConstants,
    Contract,
    ContractYear,
    Player,
    PlayerSalary,
    PlayerSeason,
    Team,
)

router = APIRouter(prefix="/teams", tags=["teams"])

LOGO_CACHE_DIR = settings.RAW_DIR / "team_logos"
LOGO_CDN_URL = "https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"
LOGO_HEADERS = {"User-Agent": "ScoutIQ/0.1 (personal portfolio research; contact via github)"}
LOGO_CACHE_SECONDS = 604_800  # 7 days

CAVEAT = (
    "Roster is derived from each player's current-team flag and may be incomplete or lag "
    "mid-season trades. Cap hit is the contract year where available, else realized salary "
    "(see pay_source). Excludes dead money, cap holds, incomplete-roster charges, "
    "two-way/Exhibit-10 deals, trade exceptions, Bird rights, luxury tax owed, and the "
    "repeater tax."
)


@router.get("/{team_id}/logo")
def team_logo(team_id: int) -> FileResponse:
    """Return an NBA team logo through the API so browsers avoid CDN flakiness."""
    LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logo_path = LOGO_CACHE_DIR / f"{team_id}.svg"

    if logo_path.exists():
        return FileResponse(
            logo_path,
            media_type="image/svg+xml",
            headers={"Cache-Control": f"public, max-age={LOGO_CACHE_SECONDS}"},
        )

    try:
        resp = requests.get(LOGO_CDN_URL.format(team_id=team_id), headers=LOGO_HEADERS, timeout=8)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail="team logo fetch failed") from e

    content_type = resp.headers.get("content-type", "").lower()
    if resp.status_code != 200 or not resp.content or "svg" not in content_type:
        raise HTTPException(status_code=404, detail="team logo unavailable")

    logo_path.write_bytes(resp.content)
    return FileResponse(
        logo_path,
        media_type="image/svg+xml",
        headers={"Cache-Control": f"public, max-age={LOGO_CACHE_SECONDS}"},
    )


class TeamListItem(BaseModel):
    team_id: int
    abbreviation: str | None
    name: str | None
    conference: str | None
    division: str | None


class TeamCapContext(BaseModel):
    season: str
    salary_cap: int | None
    tax_line: int | None
    first_apron: int | None
    second_apron: int | None
    tier: str  # below-tax | taxpayer | first-apron | second-apron
    room_to_tax: int | None          # signed; negative = over the line
    room_to_first_apron: int | None
    room_to_second_apron: int | None


class TeamCapTotals(BaseModel):
    total_payroll_usd: int
    payroll_pct: float | None
    total_value_usd: int
    surplus_usd: int          # total model value − total payroll
    surplus_pct: float | None
    roster_size: int
    payroll_player_count: int  # players with a known cap hit
    valued_player_count: int   # players with a model value
    bargain_count: int
    overpay_count: int


class TeamCapSheetPlayer(PlayerSummary):
    age: int | None
    cap_hit_usd: int | None
    salary_pct: float | None
    value_pct: float | None
    value_usd: int | None
    gap_pct: float | None
    valuation_status: str  # ready | unavailable
    pay_source: str | None  # contract | salary | None


class TeamCapSheetResponse(BaseModel):
    team: TeamSummary
    season: str
    cap_context: TeamCapContext
    totals: TeamCapTotals
    players: list[TeamCapSheetPlayer]
    top_bargain: TeamCapSheetPlayer | None
    top_overpay: TeamCapSheetPlayer | None
    caveat: str


def _apron(cap_row: CapConstants | None, field: str, proxy_mult: float) -> int | None:
    """Apron value, falling back to a tax-line proxy before the 2023-24 CBA (mirrors simulator)."""
    base = getattr(cap_row, field) if cap_row else None
    if base:
        return base
    if cap_row and cap_row.tax_line:
        return int(cap_row.tax_line * proxy_mult)
    return None


def team_cap_hits(
    db: DB, player_ids: list[int], season: str
) -> tuple[dict[int, int], dict[int, str]]:
    """Per-player cap hit for `season` and where it came from.

    Precedence: the contract year for the season (later contracts win), else the
    realized salary. Shared by the team cap sheet and the simulator's apron overlay so
    both price a roster the same way. Returns (cap_hit_by_player, pay_source_by_player).
    """
    cap_hit_by_player: dict[int, int] = {}
    pay_source_by_player: dict[int, str] = {}
    if not player_ids:
        return cap_hit_by_player, pay_source_by_player

    contract_rows = db.execute(
        select(ContractYear, Contract.player_id)
        .join(Contract, Contract.id == ContractYear.contract_id)
        .where(Contract.player_id.in_(player_ids))
        .where(ContractYear.season == season)
        .order_by(Contract.season_start)
    ).all()
    for cy, pid in contract_rows:
        if cy.aav is not None:
            cap_hit_by_player[pid] = cy.aav
            pay_source_by_player[pid] = "contract"

    salary_rows = db.scalars(
        select(PlayerSalary)
        .where(PlayerSalary.player_id.in_(player_ids))
        .where(PlayerSalary.season == season)
    ).all()
    for sr in salary_rows:
        if sr.player_id not in cap_hit_by_player and sr.salary is not None:
            cap_hit_by_player[sr.player_id] = sr.salary
            pay_source_by_player[sr.player_id] = "salary"

    return cap_hit_by_player, pay_source_by_player


@router.get("", response_model=list[TeamListItem])
def list_teams(db: DB = None):
    """All teams, ordered by name — drives the war-room picker."""
    teams = db.scalars(select(Team).order_by(Team.name)).all()
    return [
        TeamListItem(
            team_id=t.team_id,
            abbreviation=t.abbreviation,
            name=t.name,
            conference=t.conference,
            division=t.division,
        )
        for t in teams
    ]


@router.get("/{team_id}/cap-sheet", response_model=TeamCapSheetResponse)
def get_team_cap_sheet(team_id: int, season: str | None = None, db: DB = None):
    """Roster cap sheet: payroll vs tax/apron + per-player value-vs-pay."""
    if season is not None and not is_valid_season(season):
        raise HTTPException(
            status_code=422, detail="season must be a 'YYYY-YY' label, e.g. '2025-26'."
        )
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found.")
    target = season or LATEST_SEASON

    roster = db.scalars(select(Player).where(Player.current_team_id == team_id)).all()
    player_ids = [p.player_id for p in roster]
    player_by_id = {p.player_id: p for p in roster}
    # Batch every player's summary (latest season + team) in two queries instead
    # of one latest-season lookup per rostered player inside the loop below.
    summaries = _batched_summaries(roster, db)

    cap_row = db.scalars(select(CapConstants).where(CapConstants.season == target)).first()
    salary_cap = cap_row.salary_cap if cap_row else None
    tax_line = cap_row.tax_line if cap_row else None
    first_apron = _apron(cap_row, "first_apron", 1.032)
    second_apron = _apron(cap_row, "second_apron", 1.097)

    # Cap hit precedence: contract year for the season (later contracts win), else realized salary.
    cap_hit_by_player, pay_source_by_player = team_cap_hits(db, player_ids, target)

    # Model value: batch over rostered players that have a stats season.
    season_rows = (
        db.scalars(
            select(PlayerSeason)
            .where(PlayerSeason.player_id.in_(player_ids))
            .where(PlayerSeason.season == target)
        ).all()
        if player_ids
        else []
    )
    season_by_player = {r.player_id: r for r in season_rows}

    feature_rows: list[dict] = []
    feature_ids: list[int] = []
    for pid in player_ids:
        sr = season_by_player.get(pid)
        if sr is None:
            continue
        feature_rows.append(build_features_from_season(sr, player_by_id[pid]))
        feature_ids.append(pid)
    try:
        value_by_player = dict(zip(feature_ids, predict_many_from_features(feature_rows)))
    except FileNotFoundError:
        value_by_player = {}

    players: list[TeamCapSheetPlayer] = []
    total_payroll = 0
    total_value = 0
    payroll_count = 0
    valued_count = 0
    bargains = 0
    overpays = 0

    for p in roster:
        summary = summaries[p.player_id]
        cap_hit = cap_hit_by_player.get(p.player_id)
        pay_source = pay_source_by_player.get(p.player_id)
        salary_pct = round(cap_hit / salary_cap * 100, 2) if (cap_hit and salary_cap) else None

        pred = value_by_player.get(p.player_id)
        value_pct = pred["value_pct"] if pred else None
        value_usd = int(round(value_pct / 100 * salary_cap)) if (value_pct is not None and salary_cap) else None
        gap_pct = (
            round(value_pct - salary_pct, 2)
            if (value_pct is not None and salary_pct is not None)
            else None
        )
        season_row = season_by_player.get(p.player_id)
        age = season_row.age if season_row else None

        if cap_hit:
            total_payroll += cap_hit
            payroll_count += 1
        if value_usd is not None:
            total_value += value_usd
            valued_count += 1
        if gap_pct is not None:
            if gap_pct >= 1:
                bargains += 1
            elif gap_pct <= -1:
                overpays += 1

        players.append(
            TeamCapSheetPlayer(
                **summary.model_dump(),
                age=age,
                cap_hit_usd=cap_hit,
                salary_pct=salary_pct,
                value_pct=value_pct,
                value_usd=value_usd,
                gap_pct=gap_pct,
                valuation_status="ready" if pred else "unavailable",
                pay_source=pay_source,
            )
        )

    # Default ordering: biggest cap hit first.
    players.sort(key=lambda x: (x.cap_hit_usd or 0), reverse=True)

    payroll_pct = round(total_payroll / salary_cap * 100, 2) if salary_cap else None
    surplus_usd = total_value - total_payroll
    surplus_pct = round(surplus_usd / salary_cap * 100, 2) if salary_cap else None
    tier = classify_tier(total_payroll, tax_line, first_apron, second_apron)

    gapped = [pl for pl in players if pl.gap_pct is not None]
    top_bargain = max(gapped, key=lambda x: x.gap_pct, default=None)
    top_overpay = min(gapped, key=lambda x: x.gap_pct, default=None)
    if top_bargain and top_bargain.gap_pct < 1:
        top_bargain = None
    if top_overpay and top_overpay.gap_pct > -1:
        top_overpay = None

    return TeamCapSheetResponse(
        team=_team_summary(team),
        season=target,
        cap_context=TeamCapContext(
            season=target,
            salary_cap=salary_cap,
            tax_line=tax_line,
            first_apron=first_apron,
            second_apron=second_apron,
            tier=tier,
            room_to_tax=(tax_line - total_payroll) if tax_line else None,
            room_to_first_apron=(first_apron - total_payroll) if first_apron else None,
            room_to_second_apron=(second_apron - total_payroll) if second_apron else None,
        ),
        totals=TeamCapTotals(
            total_payroll_usd=total_payroll,
            payroll_pct=payroll_pct,
            total_value_usd=total_value,
            surplus_usd=surplus_usd,
            surplus_pct=surplus_pct,
            roster_size=len(roster),
            payroll_player_count=payroll_count,
            valued_player_count=valued_count,
            bargain_count=bargains,
            overpay_count=overpays,
        ),
        players=players,
        top_bargain=top_bargain,
        top_overpay=top_overpay,
        caveat=CAVEAT,
    )
