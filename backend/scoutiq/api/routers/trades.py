"""Fast, two-team manual trade workspaces and modeled analysis."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from scoutiq.api import rosters
from scoutiq.api.cap import SeasonCapData, build_season_sequence, cap_for, classify_tier, load_season_caps
from scoutiq.api.deps import DB
from scoutiq.api.roster_fit import load_fit_context, needs_response
from scoutiq.api.rosters import CAVEAT, TeamSummary
from scoutiq.api.season import LATEST_SEASON, is_valid_season
from scoutiq.api.trade_assets import (
    BALANCE_CAVEAT,
    PICK_VALUE_CAVEAT,
    ROSTER_COUNT_CAVEAT,
    roster_count_legality,
    trade_balance,
    upcoming_draft_year,
    SURPLUS_CAVEAT,
    TEAM_STATES,
    evaluate_pick_legality,
    remaining_contract_surplus,
    value_pick,
)
from scoutiq.api.trades import overall_status, salary_match
from scoutiq.api.valuation import value_players
from scoutiq.model.roster_fit import profile_roster
from scoutiq.models import DraftPick, Player, Team

router = APIRouter(prefix="/trades", tags=["trades"])

WORKSPACE_CACHE_SECONDS = 300
_workspace_cache: dict[tuple[object, str, int], tuple[float, "TradeTeamWorkspace"]] = {}
_workspace_cache_lock = threading.Lock()

NOT_MODELED = [
    "Pre-existing traded-player exceptions", "Non-aggregated multi-player allocation above the second apron",
    "Sign-and-trades", "No-trade clauses and player consent", "Trade kickers and bonuses",
    "Poison-pill and base-year compensation", "Guarantee adjustments", "Trade eligibility dates and waiting periods",
    "Pick swaps (informational only)", "Lottery-odds pick projection", "Full conditional-Stepien modeling",
    "Roster-count hard limits (flagged for review, not enforced — see roster caveat)",
    "In-season sub-14 grace period", "Cash", "Trades involving three or more teams",
]


class TradeRequest(BaseModel):
    season: str
    team_a_id: int
    team_b_id: int
    team_a_sends: list[int] = Field(default_factory=list)
    team_b_sends: list[int] = Field(default_factory=list)
    # Draft-pick asset ids (draft_picks.id) each side sends.
    team_a_sends_picks: list[int] = Field(default_factory=list)
    team_b_sends_picks: list[int] = Field(default_factory=list)
    # Team-state lens: explicit time-discount posture per side.
    team_a_state: str = "neutral"
    team_b_state: str = "neutral"
    # Optional expected-pick-number overrides keyed by draft_picks.id.
    expected_picks: dict[int, int] = Field(default_factory=dict)

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
        for package in (self.team_a_sends_picks, self.team_b_sends_picks):
            if len(package) != len(set(package)):
                raise ValueError("A trade package cannot contain duplicate picks")
        if set(self.team_a_sends_picks) & set(self.team_b_sends_picks):
            raise ValueError("A pick cannot appear in both trade packages")
        for state in (self.team_a_state, self.team_b_state):
            if state not in TEAM_STATES:
                raise ValueError(f"team state must be one of {TEAM_STATES}")
        for expected in self.expected_picks.values():
            if not 1 <= expected <= 60:
                raise ValueError("expected pick numbers must be between 1 and 60")
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
    is_two_way: bool = False


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
        cap = cap_for(season, load_season_caps(db))
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
    cap_hits, pay_sources = rosters.team_cap_hits(db, player_ids, season)
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
            is_two_way=bool(player.is_two_way),
        ))

    for team_id in missing:
        players = players_by_team[team_id]
        players.sort(key=lambda player: (player.cap_hit_usd or 0, player.full_name), reverse=True)
        payroll = sum(player.cap_hit_usd or 0 for player in players)
        workspace = TradeTeamWorkspace(
            team=rosters.team_summary(team_by_id[team_id]),
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


class TradePickAsset(BaseModel):
    pick_id: int
    draft_year: int
    round: int
    original_team: TeamSummary | None
    protected_top: int | None
    swap_rights_team: TeamSummary | None
    converts_to: str | None
    source: str
    notes: str | None
    label: str
    expected_pick: int
    conveyed_pick: int
    years_out: int
    deferral_years: int
    raw_pct: float
    discounted_pct: float
    value_usd: int | None


class TradeTeamPicksResponse(BaseModel):
    team: TeamSummary
    upcoming_draft_year: int
    team_state: str
    picks: list[TradePickAsset]
    caveat: str


def _pick_label(pick: DraftPick, teams_by_id: dict[int, Team]) -> str:
    origin = teams_by_id.get(pick.original_team_id)
    origin_abbr = origin.abbreviation if origin else "???"
    protection = f" (top-{pick.protected_top} protected)" if pick.protected_top else ""
    round_label = "1st" if pick.round == 1 else "2nd"
    return f"{pick.draft_year} {origin_abbr} {round_label}{protection}"


def _pick_assets(
    db: DB,
    picks: list[DraftPick],
    *,
    team_state: str,
    salary_cap: int | None,
    expected_overrides: dict[int, int] | None = None,
) -> list[TradePickAsset]:
    team_ids = {p.original_team_id for p in picks} | {
        p.swap_rights_team_id for p in picks if p.swap_rights_team_id
    }
    teams_by_id = {
        t.team_id: t
        for t in (db.scalars(select(Team).where(Team.team_id.in_(team_ids))).all() if team_ids else [])
    }
    upcoming = upcoming_draft_year(db)
    assets = []
    for pick in picks:
        value = value_pick(
            pick,
            upcoming_draft_year=upcoming,
            team_state=team_state,
            salary_cap=salary_cap,
            expected_pick=(expected_overrides or {}).get(pick.id),
        )
        assets.append(TradePickAsset(
            pick_id=pick.id,
            draft_year=pick.draft_year,
            round=pick.round,
            original_team=rosters.team_summary(teams_by_id.get(pick.original_team_id)),
            protected_top=pick.protected_top,
            swap_rights_team=rosters.team_summary(teams_by_id.get(pick.swap_rights_team_id)) if pick.swap_rights_team_id else None,
            converts_to=pick.converts_to,
            source=pick.source,
            notes=pick.notes,
            label=_pick_label(pick, teams_by_id),
            **value.__dict__,
        ))
    return assets


@router.get("/teams/{team_id}/picks", response_model=TradeTeamPicksResponse)
def get_team_picks(
    team_id: int,
    response: Response,
    season: str = LATEST_SEASON,
    team_state: str = "neutral",
    db: DB = None,
):
    """Draft picks the team currently owns, valued under its team-state lens."""
    if team_state not in TEAM_STATES:
        raise HTTPException(422, f"team_state must be one of {TEAM_STATES}")
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(404, f"Team not found: {team_id}")
    cap = cap_for(season, load_season_caps(db))
    picks = db.scalars(
        select(DraftPick)
        .where(DraftPick.current_team_id == team_id)
        .order_by(DraftPick.draft_year, DraftPick.round)
    ).all()
    response.headers["Cache-Control"] = f"public, max-age={WORKSPACE_CACHE_SECONDS}"
    return TradeTeamPicksResponse(
        team=rosters.team_summary(team),
        upcoming_draft_year=upcoming_draft_year(db),
        team_state=team_state,
        picks=_pick_assets(db, picks, team_state=team_state, salary_cap=cap.salary_cap if cap else None),
        caveat=PICK_VALUE_CAVEAT,
    )


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
    *,
    team_state: str = "neutral",
    picks_outgoing: list[TradePickAsset] | None = None,
    picks_incoming: list[TradePickAsset] | None = None,
    pick_legality=None,
    surplus_by_pid: dict | None = None,
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

    # Roster-count legality on STANDARD contracts only (two-way players excluded).
    standard_before = sum(
        1 for pid in before_ids if not roster_by_id[pid].is_two_way
    )
    standard_outgoing = sum(1 for pid in sends if not roster_by_id[pid].is_two_way)
    standard_incoming = sum(1 for pid in receives if not other_by_id[pid].is_two_way)
    roster_legality = roster_count_legality(
        standard_before=standard_before,
        standard_outgoing=standard_outgoing,
        standard_incoming=standard_incoming,
        two_way_count=sum(1 for player in roster_by_id.values() if player.is_two_way),
    )

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
        "roster_legality": roster_legality.__dict__,
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
        "team_state": team_state,
        "picks_outgoing": [p.model_dump() for p in (picks_outgoing or [])],
        "picks_incoming": [p.model_dump() for p in (picks_incoming or [])],
        "pick_legality": pick_legality.__dict__ if pick_legality else None,
        "assets": _asset_ledger(
            sends, receives, surplus_by_pid or {}, picks_outgoing or [], picks_incoming or []
        ),
    }


def _asset_ledger(
    sends: list[int],
    receives: list[int],
    surplus_by_pid: dict,
    picks_outgoing: list[TradePickAsset],
    picks_incoming: list[TradePickAsset],
) -> dict:
    """Net asset view: remaining-contract surplus for players + discounted pick value."""
    def _surplus(pid: int) -> int | None:
        entry = surplus_by_pid.get(pid)
        return entry.total_surplus_usd if entry else None

    sent_surplus = [_surplus(pid) for pid in sends]
    received_surplus = [_surplus(pid) for pid in receives]
    picks_sent_usd = sum(p.value_usd or 0 for p in picks_outgoing)
    picks_received_usd = sum(p.value_usd or 0 for p in picks_incoming)
    surplus_sent = sum(v for v in sent_surplus if v is not None)
    surplus_received = sum(v for v in received_surplus if v is not None)
    return {
        "player_surplus_sent_usd": surplus_sent,
        "player_surplus_received_usd": surplus_received,
        "player_surplus_coverage_sent": sum(v is not None for v in sent_surplus),
        "player_surplus_coverage_received": sum(v is not None for v in received_surplus),
        "players_detail": {
            str(pid): {
                "total_surplus_usd": entry.total_surplus_usd,
                "expiring": entry.expiring,
                "years": [year.__dict__ for year in entry.years],
            }
            for pid, entry in surplus_by_pid.items()
            if pid in set(sends) | set(receives)
        },
        "picks_sent_usd": picks_sent_usd,
        "picks_received_usd": picks_received_usd,
        "net_usd": (surplus_received + picks_received_usd) - (surplus_sent + picks_sent_usd),
    }


def _load_trade_picks(db: DB, req: TradeRequest) -> tuple[list[DraftPick], list[DraftPick]]:
    """Fetch and ownership-validate each side's outgoing picks."""
    all_ids = set(req.team_a_sends_picks) | set(req.team_b_sends_picks)
    if not all_ids:
        return [], []
    picks = db.scalars(select(DraftPick).where(DraftPick.id.in_(all_ids))).all()
    by_id = {p.id: p for p in picks}
    missing = [pid for pid in all_ids if pid not in by_id]
    if missing:
        raise HTTPException(422, f"Unknown draft pick ids: {missing}")
    for pick_ids, owner_id in ((req.team_a_sends_picks, req.team_a_id), (req.team_b_sends_picks, req.team_b_id)):
        not_owned = [pid for pid in pick_ids if by_id[pid].current_team_id != owner_id]
        if not_owned:
            raise HTTPException(422, f"Picks not owned by the sending team: {not_owned}")
    return [by_id[pid] for pid in req.team_a_sends_picks], [by_id[pid] for pid in req.team_b_sends_picks]


def _escalate_status(salary_status: str, *statuses: str | None) -> str:
    """Fold pick-legality and roster-count outcomes into the salary verdict.

    A hard `fail` (Stepien) makes the trade noncompliant; a `needs-review` (protected
    pick, roster-count warning) downgrades an otherwise-compliant trade to needs-review.
    """
    present = [s for s in statuses if s]
    if salary_status == "incomplete":
        return salary_status
    if "fail" in present:
        return "modeled-noncompliant"
    if "needs-review" in present and salary_status == "modeled-compliant":
        return "needs-review"
    return salary_status


@router.post("/analyze")
def analyze_trade(req: TradeRequest, db: DB = None):
    cap = cap_for(req.season, load_season_caps(db))
    if cap is None:
        raise HTTPException(503, "No cap constants available")
    workspaces = _load_trade_workspaces(db, [req.team_a_id, req.team_b_id], req.season, cap=cap)
    all_players = set(req.team_a_sends) | set(req.team_b_sends)
    values = _selected_values(db, all_players)
    fit_context = load_fit_context(db, LATEST_SEASON)

    a_picks, b_picks = _load_trade_picks(db, req)
    upcoming = upcoming_draft_year(db)
    legality_a = evaluate_pick_legality(
        db, req.team_a_id, req.team_a_sends_picks, req.team_b_sends_picks, upcoming_year=upcoming
    ) if (a_picks or b_picks) else None
    legality_b = evaluate_pick_legality(
        db, req.team_b_id, req.team_b_sends_picks, req.team_a_sends_picks, upcoming_year=upcoming
    ) if (a_picks or b_picks) else None

    # Cap sequence through the longest plausible remaining contract, for surplus pricing.
    season_caps = {c.season: c for c in build_season_sequence(req.season, 6, load_season_caps(db))}
    surplus_a = remaining_contract_surplus(
        db, sorted(all_players), values, season_caps,
        from_season=req.season, team_state=req.team_a_state,
    )
    surplus_b = remaining_contract_surplus(
        db, sorted(all_players), values, season_caps,
        from_season=req.season, team_state=req.team_b_state,
    )

    def assets_for(picks: list[DraftPick], state: str) -> list[TradePickAsset]:
        return _pick_assets(
            db, picks, team_state=state, salary_cap=cap.salary_cap, expected_overrides=req.expected_picks
        )

    a = _team_analysis(
        req.team_a_sends, req.team_b_sends, workspaces[req.team_a_id], workspaces[req.team_b_id],
        values, cap, fit_context,
        team_state=req.team_a_state,
        picks_outgoing=assets_for(a_picks, req.team_a_state),
        picks_incoming=assets_for(b_picks, req.team_a_state),
        pick_legality=legality_a,
        surplus_by_pid=surplus_a,
    )
    b = _team_analysis(
        req.team_b_sends, req.team_a_sends, workspaces[req.team_b_id], workspaces[req.team_a_id],
        values, cap, fit_context,
        team_state=req.team_b_state,
        picks_outgoing=assets_for(b_picks, req.team_b_state),
        picks_incoming=assets_for(a_picks, req.team_b_state),
        pick_legality=legality_b,
        surplus_by_pid=surplus_b,
    )
    balance = trade_balance(
        a_value_in_usd=a["assets"]["player_surplus_received_usd"] + a["assets"]["picks_received_usd"],
        a_value_out_usd=a["assets"]["player_surplus_sent_usd"] + a["assets"]["picks_sent_usd"],
        b_value_in_usd=b["assets"]["player_surplus_received_usd"] + b["assets"]["picks_received_usd"],
        b_value_out_usd=b["assets"]["player_surplus_sent_usd"] + b["assets"]["picks_sent_usd"],
        salary_cap=cap.salary_cap,
        a_valued=a["value"]["sent_coverage"] + a["value"]["received_coverage"],
        a_selected=a["value"]["sent_selected"] + a["value"]["received_selected"],
        b_valued=b["value"]["sent_coverage"] + b["value"]["received_coverage"],
        b_selected=b["value"]["sent_selected"] + b["value"]["received_selected"],
    )
    salary_status = overall_status(a["salary_match"]["status"], b["salary_match"]["status"])
    status = _escalate_status(
        salary_status,
        legality_a.status if legality_a else None,
        legality_b.status if legality_b else None,
        a["roster_legality"]["status"],
        b["roster_legality"]["status"],
    )
    summary = {
        "modeled-compliant": "Both teams fit at least one modeled salary-matching path.",
        "modeled-noncompliant": "At least one team fails a modeled salary or pick-legality rule.",
        "needs-review": "At least one package needs review — a CBA allocation path, conditional pick protection, or a roster-count adjustment outside this model.",
        "incomplete": "Select at least one player from each team to evaluate salary matching.",
    }[status]
    return {
        "season": req.season,
        "role_season": LATEST_SEASON,
        "is_projected_cap": cap.is_projected,
        "overall_status": status,
        "overall_label": _label(status),
        "summary": summary,
        "balance": balance.__dict__,
        "team_a": a,
        "team_b": b,
        "assumptions": [
            "Payroll uses target-season active contract and salary hits for current rosters.",
            PICK_VALUE_CAVEAT,
            SURPLUS_CAVEAT,
            ROSTER_COUNT_CAVEAT,
            BALANCE_CAVEAT,
        ],
        "not_modeled": NOT_MODELED,
    }
