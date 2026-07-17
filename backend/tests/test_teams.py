"""Tests for the teams cap-sheet router."""
import scoutiq.api.routers.teams as teams_router
from scoutiq.api import rosters
import scoutiq.api.valuation as valuation_module
from fastapi.testclient import TestClient

from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.model.roster_fit import build_fit_context
from scoutiq.models import CapConstants, ContractYear, Player, PlayerSalary, PlayerSeason, Team

ATL_ID = 1610612737


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class FakeDB:
    """Minimal fake tuned to the teams router's queries. One team, two players:
    a bargain (paid via contract) and an overpay (paid via realized salary)."""

    def __init__(self, *, missing_team=False):
        self.atl = None if missing_team else Team(
            team_id=ATL_ID, abbreviation="ATL", name="Atlanta Hawks",
            conference="East", division="Southeast",
        )
        self.bos = Team(team_id=1610612738, abbreviation="BOS", name="Boston Celtics")
        self.bargain = Player(player_id=100, full_name="Star Bargain", position="SG", current_team_id=ATL_ID)
        self.overpay = Player(player_id=200, full_name="Vet Overpay", position="PF", current_team_id=ATL_ID)
        self.roster = [self.bargain, self.overpay]
        self.seasons = [
            PlayerSeason(player_id=100, season="2025-26", team_id=ATL_ID, age=25, gp=72, minutes=2400,
                         box={"PTS": 1500}, advanced={"BPM": 3.0}),
            PlayerSeason(player_id=200, season="2025-26", team_id=ATL_ID, age=31, gp=60, minutes=1500,
                         box={"PTS": 700}, advanced={"BPM": -1.0}),
        ]
        # bargain is paid via a contract year; overpay has no contract year → salary fallback.
        self.contract_year = ContractYear(contract_id=1, season="2025-26", aav=10_000_000)
        self.salaries = [PlayerSalary(player_id=200, season="2025-26", salary=30_000_000, source="bbref")]
        self.cap_rows = [CapConstants(
            season="2025-26", salary_cap=154_647_000, tax_line=187_895_000,
            first_apron=195_945_000, second_apron=207_824_000,
        )]

    def get(self, model, key):
        if model is Team and self.atl and key == ATL_ID:
            return self.atl
        if model is Team and key == self.bos.team_id:
            return self.bos
        return None

    def execute(self, stmt):
        sql = str(stmt)
        if "contract_years" in sql:
            return FakeScalarResult([(self.contract_year, 100)])
        if "player_seasons.player_id IN" in sql and "teams" in sql:  # _batched_summaries
            team_by_id = {t.team_id: t for t in (self.atl, self.bos) if t}
            return FakeScalarResult([
                (s.player_id, s.season, team_by_id.get(s.team_id)) for s in self.seasons
            ])
        if "player_seasons" in sql and "teams" in sql:  # _latest_stats_row
            return FakeScalarResult([("2025-26", self.atl)])
        return FakeScalarResult([])

    def scalars(self, stmt):
        sql = str(stmt)
        if "FROM teams" in sql:
            return FakeScalarResult([self.atl, self.bos] if self.atl else [self.bos])
        if "FROM players" in sql:
            return FakeScalarResult(self.roster if self.atl else [])
        if "cap_constants" in sql:
            return FakeScalarResult(self.cap_rows)
        if "player_salaries" in sql:
            return FakeScalarResult(self.salaries)
        if "player_seasons" in sql:
            return FakeScalarResult(self.seasons)
        return FakeScalarResult([])


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _patch_model(monkeypatch):
    # value in feature/roster order: bargain 25%, overpay 8%.
    preds = iter([
        {"value_pct": 25.0, "lo_pct": 20.0, "hi_pct": 30.0, "model_version": "test"},
        {"value_pct": 8.0, "lo_pct": 5.0, "hi_pct": 11.0, "model_version": "test"},
    ])
    monkeypatch.setattr(valuation_module, "predict_many_from_features", lambda rows: [next(preds) for _ in rows])


def test_list_teams():
    response = _client(FakeDB()).get("/teams")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {t["abbreviation"] for t in body} == {"ATL", "BOS"}


def test_cap_sheet_happy_path(monkeypatch):
    _patch_model(monkeypatch)
    response = _client(FakeDB()).get(f"/teams/{ATL_ID}/cap-sheet")
    assert response.status_code == 200
    body = response.json()

    assert body["team"]["abbreviation"] == "ATL"
    assert body["season"] == "2025-26"

    ctx = body["cap_context"]
    assert ctx["salary_cap"] == 154_647_000
    assert ctx["tax_line"] and ctx["first_apron"] and ctx["second_apron"]
    assert ctx["tier"] == "below-tax"  # $40M payroll is well under the tax line

    totals = body["totals"]
    assert totals["roster_size"] == 2
    assert totals["payroll_player_count"] == 2
    assert totals["total_payroll_usd"] == 40_000_000
    assert totals["bargain_count"] == 1
    assert totals["overpay_count"] == 1

    # pay-source precedence: contract for the bargain, realized salary for the overpay.
    by_name = {p["full_name"]: p for p in body["players"]}
    assert by_name["Star Bargain"]["pay_source"] == "contract"
    assert by_name["Vet Overpay"]["pay_source"] == "salary"
    assert by_name["Star Bargain"]["gap_pct"] > 0
    assert by_name["Vet Overpay"]["gap_pct"] < 0

    assert body["top_bargain"]["full_name"] == "Star Bargain"
    assert body["top_overpay"]["full_name"] == "Vet Overpay"


def test_cap_sheet_keeps_roster_when_model_artifact_missing(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "predict_many_from_features",
        lambda rows: (_ for _ in ()).throw(FileNotFoundError("model.joblib missing")),
    )

    response = _client(FakeDB()).get(f"/teams/{ATL_ID}/cap-sheet")

    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["roster_size"] == 2
    assert body["totals"]["valued_player_count"] == 0
    assert body["totals"]["total_value_usd"] == 0
    assert body["top_bargain"] is None
    assert body["top_overpay"] is None
    assert {p["valuation_status"] for p in body["players"]} == {"unavailable"}


def test_team_needs_uses_projected_committed_roster(monkeypatch):
    monkeypatch.setattr(
        rosters,
        "team_cap_hits",
        lambda db, ids, season: ({100: 10_000_000}, {100: "contract"}),
    )
    monkeypatch.setattr(
        teams_router,
        "load_fit_context",
        lambda db, season: build_fit_context([]),
    )

    body = _client(FakeDB()).get(f"/teams/{ATL_ID}/needs?season=2026-27").json()

    assert body["role_season"] == "2025-26"
    assert body["roster_player_count"] == 1
    assert body["profiled_player_count"] == 0
    assert body["confidence"] == "low"


def test_unknown_team_404():
    response = _client(FakeDB(missing_team=True)).get(f"/teams/{ATL_ID}/cap-sheet")
    assert response.status_code == 404
