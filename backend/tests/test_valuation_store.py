"""Precompute tests: published valuations serve reads without model inference."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import scoutiq.api.valuation as valuation_module
import scoutiq.model.publish_valuations as publish_valuations
from scoutiq.api.deps import get_db
from scoutiq.api.main import app
from scoutiq.model.valuation_store import prediction_dict, stored_valuations
from scoutiq.models import CapConstants, Player, PlayerSalary, PlayerSeason, PlayerValuation

from tests.test_api import FakeDB, FakeScalarResult

COMPUTED_AT = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def _stored_row(player_id=1630217, season="2025-26", **overrides) -> PlayerValuation:
    defaults = dict(
        player_id=player_id,
        season=season,
        value_pct=24.1,
        lo_pct=16.9,
        hi_pct=29.2,
        actual_usd=34_005_250,
        actual_pct=24.19,
        gap_pct=-0.09,
        qualified=True,
        verdict_label="Fair value",
        verdict_tone="neutral",
        caution_flags=[],
        caveat=None,
        stats={"gp": 69, "mpg": 32.0, "pts_pg": 24.3, "reb_pg": 4.6, "ast_pg": 5.2,
               "ts_pct": 0.601, "bpm": 3.1, "pctl": {"pts_pg": 91}},
        features={"age": 27.0, "gp": 69, "minutes": 2205.2, "pts_pg": 24.3, "BPM": 3.1},
        model_version="v1-gbm-cqr-lags-dpcal",
        computed_at=COMPUTED_AT,
    )
    defaults.update(overrides)
    return PlayerValuation(**defaults)


class StoredValuationDB(FakeDB):
    """FakeDB plus published valuation rows."""

    def __init__(self, rows):
        super().__init__()
        self.valuation_rows = rows

    def scalars(self, stmt):
        if "player_valuations" in str(stmt):
            return FakeScalarResult(self.valuation_rows)
        return super().scalars(stmt)


def _client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _fail_predict(*args, **kwargs):
    raise AssertionError("model inference must not run when a published row exists")


def test_stored_valuations_filters_to_requested_keys():
    rows = [_stored_row(season="2025-26"), _stored_row(season="2012-13")]
    db = StoredValuationDB(rows)

    result = stored_valuations(db, [(1630217, "2025-26")])

    assert set(result) == {(1630217, "2025-26")}
    assert prediction_dict(result[(1630217, "2025-26")]) == {
        "value_pct": 24.1,
        "lo_pct": 16.9,
        "hi_pct": 29.2,
        "model_version": "v1-gbm-cqr-lags-dpcal",
    }


def test_value_players_serves_published_rows_without_model(monkeypatch):
    monkeypatch.setattr(valuation_module, "predict_many_from_features", _fail_predict)
    db = StoredValuationDB([_stored_row(season="2024-25")])

    valuations = valuation_module.value_players(db, [(1630217, "2024-25")])

    valuation = valuations[(1630217, "2024-25")]
    assert valuation.value_pct == 24.1
    assert valuation.verdict_label == "Fair value"
    assert valuation.salary_cap == 140_588_000  # cap row still resolved for the season
    assert valuation.value_usd == int(round(24.1 / 100 * 140_588_000))
    assert valuation.computed_at == COMPUTED_AT.isoformat()


def test_watchlist_serves_published_rows_without_model(monkeypatch):
    monkeypatch.setattr(valuation_module, "predict_many_from_features", _fail_predict)
    client = _client(StoredValuationDB([_stored_row(season="2025-26")]))

    response = client.get("/players/watchlist?bucket=all&limit=24&offset=0")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    valuation = items[0]["valuation"]
    assert valuation["value_pct"] == 24.1
    assert valuation["verdict_label"] == "Fair value"
    assert valuation["stats"]["pts_pg"] == 24.3


def test_valuation_endpoint_serves_published_row_without_model(monkeypatch):
    monkeypatch.setattr(valuation_module, "predict_from_features", _fail_predict)
    monkeypatch.setattr(valuation_module, "attribute_prediction", lambda features: None)
    client = _client(StoredValuationDB([_stored_row(season="2024-25")]))

    response = client.get("/players/1630217/valuation?season=2024-25")

    assert response.status_code == 200
    body = response.json()
    assert body["value_pct"] == 24.1
    assert body["gap_pct"] == -0.09
    assert body["salary_cap"] == 140_588_000
    assert body["computed_at"] == COMPUTED_AT.isoformat()
    assert body["features"]["pts_pg"] == 24.3


def test_valuation_endpoint_falls_back_live_when_unpublished(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "predict_from_features",
        lambda features: {"value_pct": 20.0, "lo_pct": 15.0, "hi_pct": 25.0, "model_version": "test"},
    )
    monkeypatch.setattr(valuation_module, "attribute_prediction", lambda features: None)
    client = _client(FakeDB())  # no published rows at all

    response = client.get("/players/1630217/valuation?season=2024-25")

    assert response.status_code == 200
    body = response.json()
    assert body["value_pct"] == 20.0
    assert body["computed_at"] is None


class PublishFakeDB:
    """Just enough session for build_season_rows: one player, one season, one salary."""

    def __init__(self):
        self.player = Player(player_id=1, full_name="Test Player", position="SG")
        self.season_row = PlayerSeason(
            player_id=1, season="2024-25", age=27, gp=70, minutes=2100,
            box={"PTS": 1400, "REB": 280, "AST": 350, "STL": 70, "BLK": 20, "TOV": 140, "FG3M": 180},
            advanced={"TS_PCT": 0.58, "USG_PCT": 0.24, "BPM": 1.5},
        )
        self.salary = PlayerSalary(player_id=1, season="2024-25", salary=14_058_800)
        self.cap = CapConstants(season="2024-25", salary_cap=140_588_000)

    def scalars(self, stmt):
        sql = str(stmt)
        if "player_salaries" in sql:
            return FakeScalarResult([self.salary])
        if "players." in sql and "player_seasons" not in sql:
            return FakeScalarResult([self.player])
        if "player_seasons.player_id IN" in sql:
            return FakeScalarResult([])  # no previous seasons
        if "player_seasons" in sql:
            return FakeScalarResult([self.season_row])
        return FakeScalarResult([])

    def get(self, model, key):
        if model is CapConstants and key == "2024-25":
            return self.cap
        return None


def test_publish_build_season_rows(monkeypatch):
    monkeypatch.setattr(
        publish_valuations,
        "predict_many_from_features",
        lambda rows: [
            {"value_pct": 18.0, "lo_pct": 13.0, "hi_pct": 23.0, "model_version": "test"}
            for _ in rows
        ],
    )

    values = publish_valuations.build_season_rows(PublishFakeDB(), "2024-25", COMPUTED_AT)

    assert len(values) == 1
    row = values[0]
    assert row["player_id"] == 1
    assert row["season"] == "2024-25"
    assert row["value_pct"] == 18.0
    assert row["actual_pct"] == 10.0  # 14,058,800 / 140,588,000
    assert row["gap_pct"] == 8.0
    assert row["qualified"] is True  # 70 gp, 2100 minutes
    assert row["verdict_label"] == "Significant bargain"
    assert row["stats"]["pts_pg"] == 20.0
    assert row["features"]["age"] == 27
    assert row["computed_at"] == COMPUTED_AT


def test_publish_percentiles():
    pool = [{"pts_pg": float(i)} for i in range(25)]
    publish_valuations.annotate_percentiles(pool)
    assert pool[0]["pctl"]["pts_pg"] == 2
    assert pool[24]["pctl"]["pts_pg"] == 98
