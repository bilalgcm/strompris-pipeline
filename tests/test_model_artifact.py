"""Guards that keep training, serving and the saved model in sync.

If api/forecasting.py FEATURES changes without retraining, the live /forecast would crash
with a feature mismatch. These tests make CI fail first instead.
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
import save_model
from features import add_features

from api.forecasting import FEATURES, ZONE_MODELS, build_feature_rows, model_path

ROOT = Path(__file__).resolve().parent.parent
ALL_AREAS = ["NO1", "NO2", "NO3", "NO4", "NO5"]


def test_training_and_serving_use_the_same_feature_list():
    assert save_model.FEATURES == FEATURES


def test_training_and_serving_agree_on_which_areas_have_their_own_model():
    assert tuple(save_model.ZONE_MODELS) == ZONE_MODELS


@pytest.mark.parametrize("area", ALL_AREAS)
def test_training_and_serving_agree_on_model_files(area):
    # save_model only writes files for the shared area and ZONE_MODELS; every area must map to one of them
    trained = {save_model.model_path(a) for a in (save_model.SHARED_AREA, *save_model.ZONE_MODELS)}
    assert model_path(area) in trained


def test_model_routing():
    assert model_path("NO1") == "model/model.joblib"
    assert model_path("NO2") == "model/model_NO2.joblib"
    assert model_path("NO3") == "model/model.joblib"
    assert model_path("NO4") == "model/model_NO4.joblib"
    assert model_path("NO5") == "model/model.joblib"


@pytest.mark.parametrize("path", sorted({model_path(a) for a in ALL_AREAS}))
def test_every_saved_model_exists_and_uses_these_features(path):
    model = joblib.load(ROOT / path)
    assert list(model.feature_names_in_) == FEATURES


@pytest.mark.parametrize("start", ["2026-10-01", "2026-10-20"])  # second one crosses the 25 Oct DST change
def test_serving_computes_the_same_features_as_training(start):
    rng = np.random.default_rng(0)
    t = pd.date_range(start, periods=24 * 12, freq="h", tz="Europe/Oslo").tz_convert("UTC")
    prices = pd.DataFrame({"time_start": t, "price": rng.random(len(t)).round(4)})
    weather = pd.DataFrame({"time_start": t, "temperature": rng.normal(5, 3, len(t)).round(1)})

    trained = add_features(prices, weather).set_index("time_start")

    known_prices = {ts.to_pydatetime(): p for ts, p in zip(prices["time_start"], prices["price"], strict=True)}
    known_temps = {ts.to_pydatetime(): v for ts, v in zip(weather["time_start"], weather["temperature"], strict=True)}
    last_day = list(trained.index[-48:])  # hours that have a full history in both
    served = build_feature_rows([ts.to_pydatetime() for ts in last_day], known_prices, known_temps)

    for ts, row in zip(last_day, served, strict=True):
        for name in FEATURES:
            assert row[name] == pytest.approx(trained.loc[ts, name]), f"{name} differs at {ts}"
