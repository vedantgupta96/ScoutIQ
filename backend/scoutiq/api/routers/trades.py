"""Fast, two-team manual trade workspaces and modeled analysis."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from scoutiq.api.cap_simulator import SeasonCapData, classify_tier
from scoutiq.api.deps import DB
from scoutiq.api.roster_fit import load_fit_context, needs_response
from scoutiq.api.routers.free_agency import _cap_for, _season_caps
from scoutiq.api.routers.players import LATEST_SEASON, TeamSummary, _team_summary
from scoutiq.api.routers.teams import CAVEAT, team_cap_hits
from scoutiq.api.season import is_valid_season
from scoutiq.api.trades import overall_status, salary_match
from scoutiq.api.valuation import value_players
from scoutiq.model.roster_fit import profile_roster
from scoutiq.models import Player, Team

router = APIRouter(prefix="/trades", tags=["trades"])

WORKSPACE_CACHE_SECONDS = 300
_workspace_cache: dict[tuple[object, str, int], tuple[float, "TradeTeamWorkspace"]] = {}
_workspace_cache_lock = threading.Lock()

NOT_MODELED = [
    "Pre-existing traded-player exceptions", "Non-aggregated multi-player allocation above the second apron",
    "Sign-and-trades", "No-trade clauses and player consent", "Trade kickers and bonuses",
    "Poison-pill and base-year compensation", "Guarantee adjustments", "Trade eligibility dates and waiting periods",
    "Draft assets", "Cash", "Trades involving three or more teams",
]


class TradeRequest(BaseModel):
    season: str
    team_a_id: int
    team_b_id: int
    team_a_sends: list[int] = Field(default_factory=list)
    team_b_sends: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self):
        if not is_valid_season(self.season):
            raise ValueError("season must be a 'YYYY-YY' label")
        if self.team_a_id == self.team_b_id:
            raise ValueError("Trade teams must be distinct")
        for package in (self.team_a_sends, self.team_b_sends):
            if len(package) != len(set(package)):
                raise ValueError("A trade package cannot contain duplicate players")
        if set(self.team_a_sends) & set(self.team_b_sends):
            raise ValueError("A player cannot appear in both trade packages")
        return self


class TradeCapContext(BaseModel):
    salary_cap: int
    tax_line: int
    first_apron: int
    second_apron: int


class TradeWorkspacePlayer(BaseModel):
    player_id: int
    full_name: str
    position: str | None
    cap_hit_usd: int | None
    salary_pct: float | None
    pay_source: str | None


class TradeTeamWorkspace(BaseModel):
    team: TeamSummary
    season: str
    is_projected_cap: bool
    cap_context: TradeCapContext
    payroll_before_usd: int
    tier_before: str
    roster_count: int
    players: list[TradeWorkspacePlayer]
    caveat: str


def _cache_bind(db: DB) -> object:
    """Scope in-process data to its database without retaining a Session."""
    try:
        return db.get_bind()
    except AttributeError:
        return db


def _clear_workspace_cache() -> None:
    """Test/deployment helper; cached values contain no ORM instances."""
    with _workspace_cache_lock:
        _workspace_cache.clear()


def _load_trade_workspaces(
    db: DB,
    team_ids: list[int] | tuple[int, ...],
    season: str,
    *,
    cap: SeasonCapData | None = None,
) -> dict[int, TradeTeamWorkspace]:
    """Load small roster/payroll workspaces in five batched queries for any misses."""
    unique_ids = list(dict.fromkeys(team_ids))
    bind = _cache_bind(db)
    now = time.monotonic()
    found: dict[int, TradeTeamWorkspace] = {}
    missing: list[int] = []
    with _workspace_cache_lock:
        for team_id in unique_ids:
            cached = _workspace_cache.get((bind, season, team_id))
            if cached and now - cached[0] < WORKSPACE_CACHE_SECONDS:
                found[team_id] = cached[1]
            else:
                missing.append(team_id)

    if not missing:
        return found

    if cap is None:
        cap = _cap_for(season, _season_caps(db))
    if cap is None:
        raise HTTPException(503, "No cap constants available")

    teams = db.scalars(select(Team).where(Team.team_id.in_(missing))).all()
    team_by_id = {team.team_id: team for team in teams}
    unknown = [team_id for team_id in missing if team_id not in team_by_id]
    if unknown:
        raise HTTPException(404, f"Team not found: {unknown[0]}")

    roster = db.scalars(
        select(Player)
        .where(Player.current_team_id.in_(missing))
        .order_by(Player.current_team_id, Player.full_name)
    ).all()
    player_ids = [player.player_id for player in roster]
    cap_hits, pay_sources = team_cap_hits(db, player_ids, season)
    players_by_team: dict[int, list[TradeWorkspacePlayer]] = {team_id: [] for team_id in missing}
    for player in roster:
        cap_hit = cap_hits.get(player.player_id)
        players_by_team[player.current_team_id].append(TradeWorkspacePlayer(
            player_id=player.player_id,
            full_name=player.full_name,
            position=player.position,
            cap_hit_usd=cap_hit,
            salary_pct=round(cap_hit / cap.salary_cap * 100, 2) if cap_hit else None,
            pay_source=pay_sources.get(player.player_id),
        ))

    for team_id in missing:
        players = players_by_team[team_id]
        players.sort(key=lambda player: (player.cap_hit_usd or 0, player.full_name), reverse=True)
        payroll = sum(player.cap_hit_usd or 0 for player in players)
        workspace = TradeTeamWorkspace(
            team=_team_summary(team_by_id[team_id]),
            season=season,
            is_projected_cap=cap.is_projected,
            cap_context=TradeCapContext(
                salary_cap=cap.salary_cap,
                tax_line=cap.tax_line,
                first_apron=cap.first_apron,
                second_apron=cap.second_apron,
            ),
            payroll_before_usd=payroll,
            tier_before=classify_tier(payroll, cap.tax_line, cap.first_apron, cap.second_apron),
            roster_count=len(players),
            players=players,
            caveat=CAVEAT,
        )
        found[team_id] = workspace
        with _workspace_cache_lock:
            _workspace_cache[(bind, season, team_id)] = (time.monotonic(), workspace)
    return found


@router.get("/teams/{team_id}/workspace", response_model=TradeTeamWorkspace)
def get_trade_workspace(team_id: int, response: Response, season: str, db: DB = None):
    if not is_valid_season(season):
        raise HTTPException(422, "season must be a 'YYYY-YY' label")
    response.headers["Cache-Control"] = f"public, max-age={WORKSPACE_CACHE_SECONDS}"
    return _load_trade_workspaces(db, [team_id], season)[team_id]


def _selected_values(db: DB, player_ids: set[int]) -> dict[int, float]:
    """Run one model batch for selected players only, never an entire roster."""
    if not player_ids:
        return {}
    valuations = value_players(db, [(pid, LATEST_SEASON) for pid in player_ids])
    return {pid: v.value_pct for (pid, _season), v in valuations.items()}


def _label(status: str) -> str:
    return {
        "modeled-compliant": "Salary-compliant under modeled rules",
        "modeled-noncompliant": "Does not salary match under modeled rules",
        "needs-review": "Manual review required",
        "incomplete": "Select players on both sides",
    }[status]


def _team_analysis(
    sends: list[int],
    receives: list[int],
    workspace: TradeTeamWorkspace,
    other_workspace: TradeTeamWorkspace,
    values: dict[int, float],
    cap: SeasonCapData,
    fit_context,
):
    roster_by_id = {player.player_id: player for player in workspace.players}
    other_by_id = {player.player_id: player for player in other_workspace.players}
    missing = [pid for pid in sends if pid not in roster_by_id]
    if missing:
        raise HTTPException(422, f"Players are not on the stated current roster: {missing}")
    invalid_salary = [pid for pid in sends if not roster_by_id[pid].cap_hit_usd or roster_by_id[pid].cap_hit_usd <= 0]
    if invalid_salary:
        raise HTTPException(422, f"Selected players lack a positive {cap.season} cap hit: {invalid_salary}")
    missing_received = [pid for pid in receives if pid not in other_by_id]
    if missing_received:
        raise HTTPException(422, f"Players are not on the stated current roster: {missing_received}")

    outgoing = sum(roster_by_id[pid].cap_hit_usd or 0 for pid in sends)
    incoming = sum(other_by_id[pid].cap_hit_usd or 0 for pid in receives)
    payroll_before = workspace.payroll_before_usd
    match = salary_match(
        outgoing=outgoing,
        incoming=incoming,
        payroll_before=payroll_before,
        outgoing_count=len(sends),
        salary_cap=cap.salary_cap,
        first_apron=cap.first_apron,
        second_apron=cap.second_apron,
    )
    before_ids = {pid for pid, player in roster_by_id.items() if player.cap_hit_usd and player.cap_hit_usd > 0}
    after_ids = (before_ids - set(sends)) | set(receives)
    before = needs_response(profile_roster(fit_context, before_ids), LATEST_SEASON)
    after = needs_response(profile_roster(fit_context, after_ids), LATEST_SEASON)

    def value_usd(pid: int) -> int | None:
        value_pct = values.get(pid)
        return int(round(value_pct / 100 * cap.salary_cap)) if value_pct is not None else None

    sent_values = [value_usd(pid) for pid in sends]
    received_values = [value_usd(pid) for pid in receives]
    payroll_after = payroll_before - outgoing + incoming
    before_needs = {need.key: need for need in before.needs}
    fit_changes = []
    for need in after.needs:
        prior = before_needs.get(need.key)
        if prior is None:
            continue
        delta = round(need.coverage_pct - prior.coverage_pct, 2)
        if delta:
            fit_changes.append({
                "key": need.key,
                "label": need.label,
                "before_pct": prior.coverage_pct,
                "after_pct": need.coverage_pct,
                "delta_pct": delta,
            })
    fit_changes.sort(key=lambda item: abs(item["delta_pct"]), reverse=True)
    return {
        "team": workspace.team,
        "cap_context": workspace.cap_context,
        "payroll_before_usd": payroll_before,
        "payroll_after_usd": payroll_after,
        "tier_before": workspace.tier_before,
        "tier_after": classify_tier(payroll_after, cap.tax_line, cap.first_apron, cap.second_apron),
        "roster_count_before": len(before_ids),
        "roster_count_after": len(after_ids),
        "outgoing_salary_usd": outgoing,
        "incoming_salary_usd": incoming,
        "salary_delta_usd": incoming - outgoing,
        "selected_outgoing_ids": sends,
        "selected_incoming_ids": receives,
        "selected_outgoing": [roster_by_id[pid].model_dump() for pid in sends],
        "salary_match": match.__dict__,
        "value": {
            "sent_usd": sum(value for value in sent_values if value is not None),
            "received_usd": sum(value for value in received_values if value is not None),
            "delta_usd": sum(value for value in received_values if value is not None) - sum(value for value in sent_values if value is not None),
            "sent_coverage": sum(value is not None for value in sent_values),
            "received_coverage": sum(value is not None for value in received_values),
            "sent_selected": len(sent_values),
            "received_selected": len(received_values),
        },
        "fit_before": before,
        "fit_after": after,
        "fit_changes": fit_changes[:3],
    }


@router.post("/analyze")
def analyze_trade(req: TradeRequest, db: DB = None):
    cap = _cap_for(req.season, _season_caps(db))
    if cap is None:
        raise HTTPException(503, "No cap constants available")
    workspaces = _load_trade_workspaces(db, [req.team_a_id, req.team_b_id], req.season, cap=cap)
    values = _selected_values(db, set(req.team_a_sends) | set(req.team_b_sends))
    fit_context = load_fit_context(db, LATEST_SEASON)
    a = _team_analysis(req.team_a_sends, req.team_b_sends, workspaces[req.team_a_id], workspaces[req.team_b_id], values, cap, fit_context)
    b = _team_analysis(req.team_b_sends, req.team_a_sends, workspaces[req.team_b_id], workspaces[req.team_a_id], values, cap, fit_context)
    status = overall_status(a["salary_match"]["status"], b["salary_match"]["status"])
    summary = {
        "modeled-compliant": "Both teams fit at least one modeled salary-matching path.",
        "modeled-noncompliant": "At least one team exceeds every eligible modeled salary limit.",
        "needs-review": "At least one package requires a CBA allocation path outside this model.",
        "incomplete": "Select at least one player from each team to evaluate salary matching.",
    }[status]
    return {
        "season": req.season,
        "role_season": LATEST_SEASON,
        "is_projected_cap": cap.is_projected,
        "overall_status": status,
        "overall_label": _label(status),
        "summary": summary,
        "team_a": a,
        "team_b": b,
        "assumptions": ["Payroll uses target-season active contract and salary hits for current rosters."],
        "not_modeled": NOT_MODELED,
    }
