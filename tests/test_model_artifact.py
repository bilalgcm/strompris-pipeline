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

from api.forecasting import FEATURES, build_feature_rows

MODEL_PATH = Path(__file__).resolve().parent.parent / "model" / "model.joblib"


def test_training_and_serving_use_the_same_feature_list():
    assert save_model.FEATURES == FEATURES


def test_saved_model_was_trained_on_these_features():
    model = joblib.load(MODEL_PATH)
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
