import numpy as np

from scoutiq.model import predict
from scoutiq.model.features import FEATURE_COLS
from scoutiq.models import PlayerSeason


class _ConstantModel:
    def __init__(self, value):
        self.value = value

    def predict(self, rows):
        return np.full(len(rows), self.value)


class _DriverModel:
    def predict(self, rows):
        return (rows["pts_pg"].fillna(0) * 0.01 + rows["age"].fillna(0) * 0.001).to_numpy()


def test_prev_season_label_crosses_century_suffix():
    assert predict.prev_season_label("2025-26") == "2024-25"
    assert predict.prev_season_label("2000-01") == "1999-00"


def test_build_features_adds_lags_and_trajectory():
    current = PlayerSeason(
        player_id=1, season="2025-26", gp=70, minutes=2100,
        box={"PTS": 1400}, advanced={"TS_PCT": 0.6, "BPM": 2.0, "WS": 6.0},
    )
    previous = PlayerSeason(
        player_id=1, season="2024-25", gp=60, minutes=1500,
        box={"PTS": 900}, advanced={"TS_PCT": 0.55, "BPM": 1.0, "WS": 4.0},
    )

    features = predict.build_features_from_season(current, None, prev=previous)

    assert features["lag_gp"] == 60
    assert features["lag_minutes"] == 1500
    assert features["lag_pts_pg"] == 15
    assert features["d_pts_pg"] == 5
    assert features["gp_2yr"] == 130


def test_attribution_reports_grouped_occlusion(monkeypatch):
    medians = {column: 0.0 for column in FEATURE_COLS}
    monkeypatch.setattr(
        predict,
        "load_artifact",
        lambda: {"model": _DriverModel(), "feature_medians": medians},
    )

    result = predict.attribute_prediction({"pts_pg": 20.0, "age": 25.0})
    by_group = {row["group"]: row["delta_pct"] for row in result}

    assert by_group["scoring"] == 20.0
    assert by_group["age"] == 2.5
    assert by_group["availability"] == 0.0


def test_v0_artifact_keeps_fixed_interval_fallback(monkeypatch):
    monkeypatch.setattr(
        predict,
        "load_artifact",
        lambda: {
            "model": _ConstantModel(0.2),
            "qhat_80": 0.05,
            "version": "v0-gbm-conformal",
        },
    )

    result = predict.predict_many_from_features([{}])[0]

    assert result == {
        "value_pct": 20.0,
        "lo_pct": 15.0,
        "hi_pct": 25.0,
        "model_version": "v0-gbm-conformal",
    }
