from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.testclient import TestClient

import scoutiq.api.routers.headshots as headshots_router
import scoutiq.api.routers.simulator as simulator_router
import scoutiq.api.routers.players as players_router
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.models import CapConstants, Contract, ContractYear, Player, PlayerSalary, PlayerSeason, Team


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
            advanced={
                "USG_PCT": 0.23,
                "TS_PCT": 0.60,
                "AST_PCT": 0.22,
                "REB_PCT": 0.07,
                "BPM": 2.5,
                "OBPM": 3.2,
                "DBPM": -0.7,
                "PER": 16.0,
            },
        )
        self.similar_players = [
            self.player,
            Player(
                player_id=203924,
                full_name="Buddy Hield",
                position="SG",
                current_team_id=1610612744,
                current_team_source="nba_api.commonallplayers:2025-26",
            ),
            Player(
                player_id=1630591,
                full_name="Jalen Suggs",
                position="SG-PG",
                current_team_id=1610612753,
                current_team_source="nba_api.commonallplayers:2025-26",
            ),
            Player(
                player_id=1628976,
                full_name="Wendell Carter Jr.",
                position="C",
                current_team_id=1610612753,
                current_team_source="nba_api.commonallplayers:2025-26",
            ),
        ]
        self.golden_state = Team(team_id=1610612744, abbreviation="GSW", name="Golden State Warriors")
        self.similar_seasons = [
            self.player_season,
            PlayerSeason(
                player_id=203924,
                season="2024-25",
                team_id=1610612744,
                age=32,
                gp=72,
                minutes=2200,
                box={"PTS": 1250, "REB": 260, "AST": 180, "STL": 60, "BLK": 20, "TOV": 110, "FG3M": 260},
                advanced={
                    "USG_PCT": 0.21,
                    "TS_PCT": 0.59,
                    "AST_PCT": 0.14,
                    "REB_PCT": 0.06,
                    "BPM": 1.8,
                    "OBPM": 2.8,
                    "DBPM": -1.0,
                    "PER": 14.5,
                },
            ),
            PlayerSeason(
                player_id=1630591,
                season="2024-25",
                team_id=1610612753,
                age=23,
                gp=75,
                minutes=2300,
                box={"PTS": 1125, "REB": 310, "AST": 330, "STL": 115, "BLK": 35, "TOV": 135, "FG3M": 145},
                advanced={
                    "USG_PCT": 0.20,
                    "TS_PCT": 0.57,
                    "AST_PCT": 0.20,
                    "REB_PCT": 0.075,
                    "BPM": 2.1,
                    "OBPM": 1.5,
                    "DBPM": 0.6,
                    "PER": 15.0,
                },
            ),
            PlayerSeason(
                player_id=1628976,
                season="2024-25",
                team_id=1610612753,
                age=25,
                gp=60,
                minutes=1500,
                box={"PTS": 700, "REB": 500, "AST": 120, "STL": 40, "BLK": 45, "TOV": 75, "FG3M": 55},
                advanced={
                    "USG_PCT": 0.18,
                    "TS_PCT": 0.61,
                    "AST_PCT": 0.10,
                    "REB_PCT": 0.17,
                    "BPM": 1.2,
                    "OBPM": 0.3,
                    "DBPM": 0.9,
                    "PER": 16.8,
                },
            ),
        ]
        self.salary = PlayerSalary(
            player_id=1630217,
            season="2024-25",
            salary=28_000_000,
            source="bbref",
        )
        self.salaries = [
            self.salary,
            PlayerSalary(player_id=203924, season="2024-25", salary=9_000_000, source="bbref"),
            PlayerSalary(player_id=1630591, season="2024-25", salary=8_000_000, source="bbref"),
            PlayerSalary(player_id=1628976, season="2024-25", salary=12_000_000, source="bbref"),
        ]
        self.contract = Contract(
            id=42,
            player_id=1630217,
            team_id=1610612753,
            season_start="2024-25",
            years=2,
            total_value=60_000_000,
            source="spotrac",
            scraped_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        self.contract_years = [
            ContractYear(
                contract_id=42,
                season="2024-25",
                aav=28_000_000,
                cap_pct=0.1992,
                is_guaranteed=True,
                is_player_option=False,
                is_team_option=False,
            ),
            ContractYear(
                contract_id=42,
                season="2025-26",
                aav=32_000_000,
                cap_pct=0.2069,
                is_guaranteed=False,
                is_player_option=True,
                is_team_option=False,
            ),
        ]
        self.cap_rows = [
            CapConstants(
                season="2024-25",
                salary_cap=140_588_000,
                tax_line=170_814_000,
                first_apron=178_132_000,
                second_apron=188_931_000,
            ),
        ]

    def get(self, model, key):
        if model is Player and self.player and key == self.player.player_id:
            return self.player
        if model is Team and key == self.memphis.team_id:
            return self.memphis
        if model is Team and key == self.orlando.team_id:
            return self.orlando
        if model is Team and key == self.golden_state.team_id:
            return self.golden_state
        if model is CapConstants and key == "2024-25":
            return self.cap_rows[0]
        return None

    def execute(self, stmt):
        sql = str(stmt)
        if "player_seasons.player_id IN" in sql and "player_seasons.season" in sql and "teams" in sql:
            team_by_id = {
                self.memphis.team_id: self.memphis,
                self.orlando.team_id: self.orlando,
                self.golden_state.team_id: self.golden_state,
            }
            rows = [
                (season.player_id, "2024-25", team_by_id.get(season.team_id))
                for season in self.similar_seasons
            ]
            return FakeScalarResult(rows if self.player else [])
        if "player_seasons.season" in sql and "teams" in sql:
            return FakeScalarResult([("2024-25", self.memphis)] if self.player else [])
        return FakeScalarResult([])

    def scalars(self, stmt):
        sql = str(stmt)
        if "FROM contracts" in sql:
            return FakeScalarResult([self.contract] if self.player else [])
        if "FROM contract_years" in sql:
            return FakeScalarResult(self.contract_years if self.player else [])
        if "FROM teams" in sql:
            return FakeScalarResult([self.memphis, self.orlando, self.golden_state])
        if "cap_constants" in sql:
            return FakeScalarResult(self.cap_rows)
        if "player_salaries" in sql:
            return FakeScalarResult(self.salaries if self.player else [])
        if "SELECT players." in sql:
            if "players.player_id IN" in sql:
                return FakeScalarResult(self.similar_players if self.player else [])
            return FakeScalarResult([self.player] if self.player else [])
        if "SELECT player_seasons.season" in sql:
            return FakeScalarResult(["2024-25"] if self.player else [])
        if "player_seasons" in sql:
            if "player_seasons.gp >=" in sql or "player_seasons.minutes >=" in sql:
                return FakeScalarResult(self.similar_seasons if self.player else [])
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
        "predict_from_features",
        lambda features: {
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
    assert body["valuation_season"] == "2025-26"  # defaults to VALUATION_SEASON
    assert body["assumptions"]["standalone_contract_only"] is True
    assert body["years"][0]["is_projected_cap"] is False
    assert body["years"][1]["is_projected_cap"] is True
    assert "cap_hit_vs_tax" not in body["years"][0]


def test_deprecated_simulator_alias_still_works(monkeypatch):
    monkeypatch.setattr(
        simulator_router,
        "predict_from_features",
        lambda features: {
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


def test_simulate_compare_ranks_scenarios(monkeypatch):
    monkeypatch.setattr(
        simulator_router,
        "predict_from_features",
        lambda features: {
            "value_pct": 25.0,
            "lo_pct": 20.0,
            "hi_pct": 30.0,
            "model_version": "v0-gbm-conformal",
        },
    )
    client = _client(FakeDB())

    response = client.post(
        "/simulate/compare",
        json={
            "scenarios": [
                {"player_id": 1630217, "aav_pct": 20.0, "years": 4, "start_season": "2024-25"},
                {"player_id": 1630217, "aav_pct": 30.0, "years": 2, "start_season": "2024-25"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["scenarios"]) == 2
    assert len(body["deltas"]) == 2
    # value gap = 25 - aav_pct → +5 for scenario 0, -5 for scenario 1, so 0 is the better value.
    assert body["best_value_index"] == 0
    assert body["deltas"][0]["value_gap_pct"] == 5.0
    assert body["deltas"][1]["value_gap_pct"] == -5.0


def test_simulate_compare_rejects_single_scenario():
    client = _client(FakeDB())
    response = client.post(
        "/simulate/compare",
        json={"scenarios": [{"player_id": 1630217, "aav_pct": 20.0, "years": 1, "start_season": "2024-25"}]},
    )
    assert response.status_code == 422


def test_simulator_malformed_start_season_returns_422_not_500():
    client = _client(FakeDB())

    response = client.post(
        "/simulate/contract",
        json={"player_id": 1630217, "aav_pct": 20.0, "years": 1, "start_season": "banana"},
    )

    assert response.status_code == 422
    # Clean validation message, not a leaked int() ValueError.
    assert "literal" not in response.text.lower()


def test_simulator_malformed_valuation_season_returns_422():
    client = _client(FakeDB())

    response = client.post(
        "/simulate/contract",
        json={
            "player_id": 1630217,
            "aav_pct": 20.0,
            "years": 1,
            "start_season": "2024-25",
            "valuation_season": "2024-99",
        },
    )

    assert response.status_code == 422


def test_rationale_load_managed_returns_actionable_404(monkeypatch):
    """A scouted player with no valuation-capable season gets a specific, actionable
    error explaining which signal is missing — not a generic 'no stats' 404."""

    class _Ratings:
        traits = [object()]  # non-empty → scout coverage present

    monkeypatch.setattr(players_router, "aggregate_from_db", lambda *a, **k: _Ratings())
    monkeypatch.setattr(players_router.settings, "ANTHROPIC_API_KEY", "test-key", raising=False)

    def _no_valuation(*a, **k):
        raise HTTPException(status_code=404, detail="No stats for player_id=1630217 in season 2025-26.")

    monkeypatch.setattr(players_router, "get_valuation", _no_valuation)
    client = _client(FakeDB())

    response = client.get("/players/1630217/rationale?consensus=fusion")

    assert response.status_code == 404
    assert "scouting coverage but no model valuation" in response.json()["detail"]


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
    assert body[0]["valuation"]["verdict_label"] == "Significant bargain"
    assert body[0]["valuation"]["verdict_tone"] == "positive"
    assert body[0]["valuation"]["caution_flags"] == []


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


def test_valuation_cautions_returns_warning_verdicts(monkeypatch):
    monkeypatch.setattr(
        players_router,
        "predict_many_from_features",
        lambda rows: [
            {
                "value_pct": 35.0,
                "lo_pct": 30.0,
                "hi_pct": 40.0,
                "model_version": "v0-gbm-conformal",
            }
            for _ in rows
        ],
    )
    fake = FakeDB()
    fake.player_season.age = 37
    fake.player_season.advanced = {
        **fake.player_season.advanced,
        "BPM": -0.4,
        "WS48": 0.009,
        "NET_RATING": -12.1,
        "TS_PCT": 0.528,
        "USG_PCT": 0.252,
    }
    client = _client(fake)

    response = client.get("/players/valuation-cautions?season=2024-25&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Desmond Bane"
    assert body["items"][0]["valuation"]["verdict_label"] == "Salary bargain"
    assert body["items"][0]["valuation"]["verdict_tone"] == "warning"


def test_valuation_without_season_uses_latest_available_player_season(monkeypatch):
    captured = {}

    def fake_predict(features):
        captured["gp"] = features["gp"]
        return {
            "value_pct": 23.5,
            "lo_pct": 18.1,
            "hi_pct": 28.9,
            "model_version": "v0-gbm-conformal",
        }

    monkeypatch.setattr(players_router, "predict_from_features", fake_predict)
    client = _client(FakeDB())

    response = client.get("/players/1630217/valuation")

    assert response.status_code == 200
    assert response.json()["season"] == "2024-25"
    assert captured["gp"] == 70


def test_valuation_verdict_cautions_minimum_veteran_impact_gap():
    label, tone, flags, caveat = players_router._valuation_verdict(
        gap_pct=15.76,
        actual_pct=1.48,
        features={
            "age": 37,
            "BPM": "-0.4",
            "WS48": ".009",
            "NET_RATING": -12.1,
            "TS_PCT": 0.528,
            "USG_PCT": 0.252,
        },
    )

    assert label == "Salary bargain"
    assert tone == "warning"
    assert "Age 35+" in flags
    assert "Minimum-salary gap" in flags
    assert "Negative BPM" in flags
    assert caveat


def test_player_contract_returns_current_contract_timeline(monkeypatch):
    # The contract endpoint batches valuation across the seasons that have stats
    # (only 2024-25 in the fake), so patch the batched scorer rather than the
    # per-player one. The fake returns just the 2024-25 season row, so 2025-26
    # gets no value.
    monkeypatch.setattr(
        players_router,
        "predict_many_from_features",
        lambda rows: [
            {"value_pct": 23.5, "lo_pct": 18.1, "hi_pct": 28.9, "model_version": "v0-gbm-conformal"}
            for _ in rows
        ],
    )
    client = _client(FakeDB())

    response = client.get("/players/1630217/contract")

    assert response.status_code == 200
    body = response.json()
    assert body["player_name"] == "Desmond Bane"
    assert body["season_start"] == "2024-25"
    assert body["years"] == 2
    assert body["total_value"] == 60_000_000
    assert body["extension_start_season"] == "2026-27"
    assert body["years_detail"][0]["season"] == "2024-25"
    assert body["years_detail"][0]["cap_hit_pct"] == 19.92
    assert body["years_detail"][0]["value_pct"] == 23.5
    assert body["years_detail"][0]["value_gap_pct"] == 3.58
    assert body["years_detail"][1]["is_player_option"] is True
    assert body["years_detail"][1]["value_pct"] is None


def test_similar_players_returns_role_and_market_context(monkeypatch):
    def fake_predict_many(rows):
        predictions = []
        for row in rows:
            pts_pg = row.get("pts_pg") or 0
            if pts_pg > 20:
                value = 23.5
            elif pts_pg > 16:
                value = 14.0
            elif pts_pg > 14:
                value = 20.5
            else:
                value = 10.0
            predictions.append({
                "value_pct": value,
                "lo_pct": max(value - 4, 0),
                "hi_pct": value + 4,
                "model_version": "v0-gbm-conformal",
            })
        return predictions

    monkeypatch.setattr(players_router, "predict_many_from_features", fake_predict_many)
    client = _client(FakeDB())

    response = client.get("/players/1630217/similar?mode=replacements&season=2024-25&limit=5&min_minutes=0")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "replacements"
    assert body["season"] == "2024-25"
    assert "lower cap hit" in body["basis"]
    assert body["results"]
    result_names = [row["player"]["full_name"] for row in body["results"]]
    assert "Jalen Suggs" in result_names
    assert "Wendell Carter Jr." not in result_names
    first = body["results"][0]
    assert first["player"]["player_id"] != 1630217
    assert first["salary_pct"] < 19.92
    assert first["explanation_tags"]
    assert "salary_pct" in first["deltas"]


def test_backtest_returns_committed_metrics():
    client = _client(FakeDB())

    response = client.get("/backtest")

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "v0-gbm-conformal"
    assert body["metrics"]["n_test"] == 699
    assert body["metrics"]["test_seasons"] == ["2024-25", "2025-26"]
    assert "metrics.json" in body["artifacts"]


def test_health_exposes_current_season():
    client = _client(FakeDB())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # current_season is the UI's source of truth; it must mirror LATEST_SEASON.
    assert body["current_season"] == players_router.LATEST_SEASON


def test_player_headshot_fetches_and_caches_image(monkeypatch, tmp_path):
    calls = {"count": 0}

    class FakeResponse:
        status_code = 200
        content = b"png-bytes"
        headers = {"content-type": "image/png"}

    def fake_get(url, headers, timeout):
        calls["count"] += 1
        return FakeResponse()

    monkeypatch.setattr(headshots_router, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(headshots_router.requests, "get", fake_get)
    client = _client(FakeDB())

    first = client.get("/players/1630217/headshot")
    second = client.get("/players/1630217/headshot")

    assert first.status_code == 200
    assert first.content == b"png-bytes"
    assert second.status_code == 200
    assert second.content == b"png-bytes"
    assert calls["count"] == 1
    assert (tmp_path / "1630217.png").exists()


def test_player_headshot_negative_caches_missing_image(monkeypatch, tmp_path):
    calls = {"count": 0}

    class FakeResponse:
        status_code = 404
        content = b""
        headers = {"content-type": "text/html"}

    def fake_get(url, headers, timeout):
        calls["count"] += 1
        return FakeResponse()

    monkeypatch.setattr(headshots_router, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(headshots_router.requests, "get", fake_get)
    client = _client(FakeDB())

    first = client.get("/players/999999/headshot")
    second = client.get("/players/999999/headshot")

    assert first.status_code == 404
    assert second.status_code == 404
    assert calls["count"] == 1
    assert (tmp_path / "999999.missing").exists()


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
