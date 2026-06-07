from fastapi.testclient import TestClient

import scoutiq.api.routers.simulator as simulator_router
import scoutiq.api.routers.players as players_router
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason, Team


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class FakeDB:
    def __init__(self, *, missing_player=False):
        self.player = None if missing_player else Player(
            player_id=1630217,
            full_name="Desmond Bane",
            position="SG",
            current_team_id=1610612753,
            current_team_source="nba_api.commonallplayers:2025-26",
        )
        self.memphis = Team(team_id=1610612763, abbreviation="MEM", name="Memphis Grizzlies")
        self.orlando = Team(team_id=1610612753, abbreviation="ORL", name="Orlando Magic")
        self.player_season = PlayerSeason(
            player_id=1630217,
            season="2024-25",
            team_id=1610612763,
            age=26,
            gp=70,
            minutes=2400,
            box={"PTS": 1500, "REB": 300, "AST": 400, "STL": 80, "BLK": 20, "TOV": 150, "FG3M": 200},
            advanced={},
        )
        self.salary = PlayerSalary(
            player_id=1630217,
            season="2024-25",
            salary=28_000_000,
            source="bbref",
        )
        self.cap_rows = [
            CapConstants(
                season="2024-25",
                salary_cap=140_588_000,
                tax_line=170_814_000,
                first_apron=178_132_000,
                second_apron=188_931_000,
            )
        ]

    def get(self, model, key):
        if model is Player and self.player and key == self.player.player_id:
            return self.player
        if model is Team and key == self.memphis.team_id:
            return self.memphis
        if model is Team and key == self.orlando.team_id:
            return self.orlando
        return None

    def execute(self, stmt):
        sql = str(stmt)
        if "SELECT player_seasons.player_id" in sql and "player_seasons.season" in sql and "teams" in sql:
            return FakeScalarResult([(self.player.player_id, "2024-25", self.memphis)] if self.player else [])
        if "player_seasons.season" in sql and "teams" in sql:
            return FakeScalarResult([("2024-25", self.memphis)] if self.player else [])
        return FakeScalarResult([])

    def scalars(self, stmt):
        sql = str(stmt)
        if "FROM teams" in sql:
            return FakeScalarResult([self.memphis, self.orlando])
        if "cap_constants" in sql:
            return FakeScalarResult(self.cap_rows)
        if "player_salaries" in sql:
            return FakeScalarResult([self.salary] if self.player else [])
        if "SELECT players." in sql:
            return FakeScalarResult([self.player] if self.player else [])
        if "SELECT player_seasons.season" in sql:
            return FakeScalarResult(["2024-25"] if self.player else [])
        if "player_seasons" in sql:
            return FakeScalarResult([self.player_season] if self.player else [])
        return FakeScalarResult([])


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_simulate_contract_happy_path(monkeypatch):
    monkeypatch.setattr(
        simulator_router,
        "predict_for_player",
        lambda player_id, season, db: {
            "value_pct": 23.5,
            "lo_pct": 18.1,
            "hi_pct": 28.9,
            "model_version": "v0-gbm-conformal",
        },
    )
    client = _client(FakeDB())

    response = client.post(
        "/simulate/contract",
        json={
            "player_id": 1630217,
            "aav_pct": 20.0,
            "years": 2,
            "player_option_years": 1,
            "start_season": "2024-25",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["player_name"] == "Desmond Bane"
    assert body["value_gap_pct"] == 3.5
    assert body["valuation_season"] == "2024-25"
    assert body["assumptions"]["standalone_contract_only"] is True
    assert body["years"][0]["is_projected_cap"] is False
    assert body["years"][1]["is_projected_cap"] is True
    assert "cap_hit_vs_tax" not in body["years"][0]


def test_deprecated_simulator_alias_still_works(monkeypatch):
    monkeypatch.setattr(
        simulator_router,
        "predict_for_player",
        lambda player_id, season, db: {
            "value_pct": 20.0,
            "lo_pct": 15.0,
            "hi_pct": 25.0,
            "model_version": "v0-gbm-conformal",
        },
    )
    client = _client(FakeDB())

    response = client.post(
        "/simulator/cap",
        json={"player_id": 1630217, "aav_pct": 20.0, "years": 1, "start_season": "2024-25"},
    )

    assert response.status_code == 200
    assert response.json()["player_name"] == "Desmond Bane"


def test_simulator_invalid_option_totals_return_422():
    client = _client(FakeDB())

    response = client.post(
        "/simulate/contract",
        json={
            "player_id": 1630217,
            "aav_pct": 20.0,
            "years": 2,
            "guaranteed_years": 2,
            "player_option_years": 1,
            "start_season": "2024-25",
        },
    )

    assert response.status_code == 422


def test_simulator_missing_player_returns_404():
    client = _client(FakeDB(missing_player=True))

    response = client.post(
        "/simulate/contract",
        json={"player_id": 999, "aav_pct": 20.0, "years": 1, "start_season": "2024-25"},
    )

    assert response.status_code == 404


def test_player_search_and_profile_shapes():
    client = _client(FakeDB())

    search = client.get("/players?query=bane&limit=5")
    profile = client.get("/players/1630217")

    assert search.status_code == 200
    assert search.json() == [
        {
            "player_id": 1630217,
            "full_name": "Desmond Bane",
            "position": "SG",
            "latest_season": "2024-25",
            "latest_stats_team": {
                "team_id": 1610612763,
                "abbreviation": "MEM",
                "name": "Memphis Grizzlies",
            },
            "current_team": {
                "team_id": 1610612753,
                "abbreviation": "ORL",
                "name": "Orlando Magic",
            },
            "current_team_source": "nba_api.commonallplayers:2025-26",
            "team_data_note": "Current roster team differs from latest loaded stats-season team.",
        }
    ]
    assert profile.status_code == 200
    assert profile.json()["latest_season"] == "2024-25"
    assert profile.json()["latest_stats_team"]["abbreviation"] == "MEM"
    assert profile.json()["current_team"]["abbreviation"] == "ORL"


def test_player_search_accepts_reordered_name_tokens():
    client = _client(FakeDB())

    response = client.get("/players?query=bane%20des&limit=5")

    assert response.status_code == 200
    assert response.json()[0]["full_name"] == "Desmond Bane"


def test_player_cards_returns_batched_valuation_snippets(monkeypatch):
    monkeypatch.setattr(
        players_router,
        "predict_many_from_features",
        lambda rows: [
            {
                "value_pct": 23.5,
                "lo_pct": 18.1,
                "hi_pct": 28.9,
                "model_version": "v0-gbm-conformal",
            }
            for _ in rows
        ],
    )
    client = _client(FakeDB())

    response = client.get("/players/cards?query=bane%20des&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["full_name"] == "Desmond Bane"
    assert body[0]["latest_stats_team"]["abbreviation"] == "MEM"
    assert body[0]["current_team"]["abbreviation"] == "ORL"
    assert body[0]["valuation_status"] == "ready"
    assert body[0]["valuation"]["season"] == "2024-25"
    assert body[0]["valuation"]["value_pct"] == 23.5
    assert body[0]["valuation"]["actual_pct"] == 19.92
    assert body[0]["valuation"]["gap_pct"] == 3.58


def test_player_watchlist_defaults_to_ranked_recent_mismatches(monkeypatch):
    monkeypatch.setattr(
        players_router,
        "predict_many_from_features",
        lambda rows: [
            {
                "value_pct": 23.5,
                "lo_pct": 18.1,
                "hi_pct": 28.9,
                "model_version": "v0-gbm-conformal",
            }
            for _ in rows
        ],
    )
    client = _client(FakeDB())

    # Pin to the fixture's season (FakeDB models a 2024-25 player); the default
    # season tracks LATEST_SEASON, which is exercised separately at the API level.
    response = client.get("/players/watchlist?bucket=underpaid&season=2024-25&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "underpaid"
    assert body["season"] == "2024-25"
    assert body["qualified_only"] is True
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Desmond Bane"
    assert body["items"][0]["valuation"]["gap_pct"] == 3.58


def test_valuation_without_season_uses_latest_available_player_season(monkeypatch):
    captured = {}

    def fake_predict(player_id, season, db):
        captured["season"] = season
        return {
            "value_pct": 23.5,
            "lo_pct": 18.1,
            "hi_pct": 28.9,
            "model_version": "v0-gbm-conformal",
            "features": {"gp": 70},
        }

    monkeypatch.setattr(players_router, "predict_for_player", fake_predict)
    client = _client(FakeDB())

    response = client.get("/players/1630217/valuation")

    assert response.status_code == 200
    assert response.json()["season"] == "2024-25"
    assert captured["season"] == "2024-25"


def test_backtest_returns_committed_metrics():
    client = _client(FakeDB())

    response = client.get("/backtest")

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "v0-gbm-conformal"
    assert body["metrics"]["n_test"] == 796
    assert "metrics.json" in body["artifacts"]


def test_health_exposes_current_season():
    client = _client(FakeDB())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # current_season is the UI's source of truth; it must mirror LATEST_SEASON.
    assert body["current_season"] == players_router.LATEST_SEASON


def test_scout_ratings_eval_returns_offline_fixture_report():
    client = _client(FakeDB())

    response = client.get("/llm/scout-ratings/eval")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "offline_fixture"
    assert body["gold_count"] == 12
    assert body["fixture_prediction_count"] == 12
    assert body["report"]["expected_trait_count"] == 72
    assert body["report"]["trait_coverage"] == 1.0
    assert body["report"]["invalid_output_count"] == 0
    assert "basketball_iq" in body["traits"]
    assert body["examples"][0]["ratings"][0]["evidence_span"]


def test_player_scout_ratings_returns_fixture_aggregate():
    client = _client(FakeDB())

    response = client.get("/players/1630217/scout-ratings")

    assert response.status_code == 200
    body = response.json()
    assert body["player_id"] == 1630217
    assert body["source_mode"] == "synthetic_fixture"
    assert body["report_count"] == 2
    assert len(body["traits"]) == 6
    assert body["traits"][0]["trait"] == "leadership"
    assert body["traits"][0]["average_score"] == 4.0
    assert body["traits"][0]["evidence"]
