import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from scoutiq.api.cap_simulator import SeasonCapData
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.api.routers import trades as trades_router
from scoutiq.api.rosters import TeamSummary
from scoutiq.api.routers.trades import (
    TradeCapContext,
    TradeRequest,
    TradeTeamWorkspace,
    TradeWorkspacePlayer,
)
from scoutiq.api.trades import expanded_fixed_amount, overall_status, salary_match
from scoutiq.model.roster_fit import build_fit_context


def test_expanded_fixed_scales_with_cap():
    assert expanded_fixed_amount(140_588_000) == 7_752_000


def test_standard_and_expanded_paths():
    standard = salary_match(outgoing=10_000_000, incoming=10_250_000, payroll_before=150_000_000,
                            outgoing_count=1, salary_cap=140_588_000, first_apron=178_132_000,
                            second_apron=188_931_000)
    assert standard.status == "pass"
    failure = salary_match(outgoing=5_000_000, incoming=20_000_000, payroll_before=170_000_000,
                           outgoing_count=1, salary_cap=140_588_000, first_apron=178_132_000,
                           second_apron=188_931_000)
    assert failure.status == "fail" and failure.margin < 0


def test_cap_room_aggregated_expanded_and_allowance_paths():
    cap_room = salary_match(outgoing=5_000_000, incoming=15_000_000, payroll_before=125_000_000,
                            outgoing_count=1, salary_cap=140_588_000, first_apron=178_132_000,
                            second_apron=188_931_000)
    assert cap_room.method == "cap-room"
    aggregated = salary_match(outgoing=20_000_000, incoming=20_250_000, payroll_before=170_000_000,
                              outgoing_count=2, salary_cap=140_588_000, first_apron=178_132_000,
                              second_apron=188_931_000)
    assert aggregated.method == "aggregated-standard-tpe"
    expanded = salary_match(outgoing=10_000_000, incoming=17_000_000, payroll_before=150_000_000,
                            outgoing_count=1, salary_cap=140_588_000, first_apron=178_132_000,
                            second_apron=188_931_000)
    assert expanded.method == "expanded-tpe"
    above_apron = salary_match(outgoing=10_000_000, incoming=10_250_000, payroll_before=180_000_000,
                              outgoing_count=1, salary_cap=140_588_000, first_apron=178_132_000,
                              second_apron=188_931_000)
    assert above_apron.status == "fail"
    assert above_apron.allowed_incoming == 10_000_000


def test_incomplete_and_overall_precedence():
    incomplete = salary_match(outgoing=0, incoming=10, payroll_before=0, outgoing_count=0,
                              salary_cap=100, first_apron=120, second_apron=130)
    assert incomplete.status == "incomplete"
    assert overall_status("incomplete", "needs-review") == "incomplete"
    assert overall_status("pass", "fail") == "modeled-noncompliant"
    assert overall_status("pass", "pass") == "modeled-compliant"


def test_multi_player_above_second_apron_needs_review():
    result = salary_match(outgoing=20_000_000, incoming=21_000_000, payroll_before=195_000_000,
                          outgoing_count=2, salary_cap=140_588_000, first_apron=178_132_000,
                          second_apron=188_931_000)
    assert result.status == "needs-review"
    assert overall_status("pass", "needs-review") == "needs-review"


def test_trade_route_and_request_validation():
    assert "/trades/analyze" in app.openapi()["paths"]
    with pytest.raises(ValidationError, match="distinct"):
        TradeRequest(season="2026-27", team_a_id=1, team_b_id=1)
    with pytest.raises(ValidationError, match="both trade packages"):
        TradeRequest(season="2026-27", team_a_id=1, team_b_id=2,
                     team_a_sends=[10], team_b_sends=[10])


def _workspace(team_id: int, salary: int) -> TradeTeamWorkspace:
    cap = TradeCapContext(
        salary_cap=160_000_000,
        tax_line=190_000_000,
        first_apron=200_000_000,
        second_apron=210_000_000,
    )
    return TradeTeamWorkspace(
        team=TeamSummary(team_id=team_id, abbreviation=f"T{team_id}", name=f"Team {team_id}"),
        season="2026-27",
        is_projected_cap=True,
        cap_context=cap,
        payroll_before_usd=170_000_000,
        tier_before="below-tax",
        roster_count=15,
        # Primary (traded) player first, then filler standard players so the roster is
        # count-valid (15 standard) and the roster-count check doesn't fire on a stub.
        players=[TradeWorkspacePlayer(
            player_id=team_id * 10,
            full_name=f"Player {team_id * 10}",
            position="G",
            cap_hit_usd=salary,
            salary_pct=round(salary / cap.salary_cap * 100, 2) if salary else None,
            pay_source="contract",
        )] + [TradeWorkspacePlayer(
            player_id=team_id * 1000 + i,
            full_name=f"Filler {team_id}-{i}",
            position="G",
            cap_hit_usd=2_000_000,
            salary_pct=1.25,
            pay_source="contract",
        ) for i in range(14)],
        caveat="Test roster caveat.",
    )


def test_trade_workspace_route_is_lightweight_and_cacheable(monkeypatch):
    workspace = _workspace(1, 10_000_000)
    calls = []
    monkeypatch.setattr(
        trades_router,
        "_load_trade_workspaces",
        lambda db, ids, season, **kwargs: calls.append((ids, season)) or {1: workspace},
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app).get("/trades/teams/1/workspace?season=2026-27")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    assert calls == [([1], "2026-27")]
    body = response.json()
    assert body["players"][0] == {
        "player_id": 10,
        "full_name": "Player 10",
        "position": "G",
        "cap_hit_usd": 10_000_000,
        "salary_pct": 6.25,
        "pay_source": "contract",
        "is_two_way": False,
    }


def test_trade_endpoint_is_lean_when_incomplete(monkeypatch):
    response = _trade_response(monkeypatch, sends_a=[], sends_b=[])
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "incomplete"
    assert body["is_projected_cap"] is True
    assert "roster_players" not in body["team_a"]
    assert body["team_a"]["selected_outgoing"] == []


class _NoContractsDB:
    """Bare session for analyze tests: no contracts or picks, so those layers degrade."""

    class _Empty:
        def all(self):
            return []

        def first(self):
            return None

    def execute(self, stmt):
        return self._Empty()

    def scalars(self, stmt):
        return self._Empty()


def _trade_response(monkeypatch, salary_a=10_000_000, salary_b=10_000_000,
                    value_a=10.0, value_b=8.0, sends_a=None, sends_b=None):
    cap = SeasonCapData("2026-27", 160_000_000, 190_000_000, 200_000_000, 210_000_000,
                        is_projected=True)

    monkeypatch.setattr(trades_router, "load_season_caps", lambda db: {cap.season: cap})
    monkeypatch.setattr(trades_router, "cap_for", lambda season, caps: cap)
    monkeypatch.setattr(
        trades_router,
        "_load_trade_workspaces",
        lambda db, ids, season, **kwargs: {
            1: _workspace(1, salary_a),
            2: _workspace(2, salary_b),
        },
    )
    monkeypatch.setattr(
        trades_router,
        "_selected_values",
        lambda db, ids: {pid: value for pid, value in ((10, value_a), (20, value_b)) if value is not None},
    )
    monkeypatch.setattr(trades_router, "load_fit_context", lambda db, season: build_fit_context([]))
    app.dependency_overrides[get_db] = lambda: _NoContractsDB()
    try:
        return TestClient(app).post("/trades/analyze", json={
            "season": "2026-27", "team_a_id": 1, "team_b_id": 2,
            "team_a_sends": [10] if sends_a is None else sends_a,
            "team_b_sends": [20] if sends_b is None else sends_b,
        })
    finally:
        app.dependency_overrides.clear()


def test_trade_endpoint_compliant_and_target_cap_value(monkeypatch):
    response = _trade_response(monkeypatch)
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "modeled-compliant"
    assert body["team_a"]["value"]["sent_usd"] == 16_000_000
    assert body["team_a"]["value"]["received_usd"] == 12_800_000
    assert "roster_players" not in body["team_a"]
    assert body["team_a"]["fit_after"]["confidence"] == "low"
    assert body["team_a"]["fit_changes"] == []


def test_trade_endpoint_noncompliant(monkeypatch):
    response = _trade_response(monkeypatch, salary_a=5_000_000, salary_b=20_000_000)
    assert response.status_code == 200
    assert response.json()["overall_status"] == "modeled-noncompliant"


def test_trade_endpoint_rejects_unknown_or_zero_salary(monkeypatch):
    assert _trade_response(monkeypatch, sends_a=[999]).status_code == 422
    assert _trade_response(monkeypatch, salary_a=0).status_code == 422


def test_trade_endpoint_unavailable_value_degrades(monkeypatch):
    response = _trade_response(monkeypatch, value_a=None, value_b=None)
    assert response.status_code == 200
    body = response.json()
    assert body["team_a"]["value"]["sent_coverage"] == 0
    assert body["team_b"]["value"]["received_coverage"] == 0
