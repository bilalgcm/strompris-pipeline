import json

import joblib
import numpy as np
import pandas as pd
from features import build_features
from intervals import CAL_MONTHS, Q_HIGH, Q_LOW, conformal_offset
from sklearn.ensemble import HistGradientBoostingRegressor

# Must match api/forecasting.py FEATURES (checked by tests/test_model_artifact.py).
# The previous-day summary was added after the backtest in Oct 2026: MAE 15.7 vs 17.9 oere on NO1.
FEATURES = [
    "hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h", "temperature", "temp_24h",
    "prev_day_mean", "prev_day_min", "prev_day_max", "prev_day_last",
]
TARGET = "price"

# The shared model is trained on NO1 and serves every area without its own model.
# Areas in ZONE_MODELS get a model trained on their own history (see the backtest, Oct 2026).
# Must match api/forecasting.py ZONE_MODELS.
SHARED_AREA = "NO1"
ZONE_MODELS = ("NO2", "NO4")


# Three models per area: the forecast, and the 10th / 90th percentile for an 80 % interval.
# Must match api/forecasting.py KINDS.
KINDS = {"mean": None, "low": Q_LOW, "high": Q_HIGH}
ALL_AREAS = ("NO1", "NO2", "NO3", "NO4", "NO5")
OFFSETS_PATH = "model/interval_offsets.json"


def model_path(area: str, kind: str = "mean") -> str:
    name = "model" + ("" if area == SHARED_AREA else f"_{area}") + ("" if kind == "mean" else f"_{kind}")
    return f"model/{name}.joblib"


def owner(area: str) -> str:
    """Which area's history trains the models that serve `area`."""
    return area if area in ZONE_MODELS else SHARED_AREA


def fit(df: pd.DataFrame, quantile: float | None = None) -> HistGradientBoostingRegressor:
    loss = {"loss": "quantile", "quantile": quantile} if quantile is not None else {}
    return HistGradientBoostingRegressor(random_state=0, **loss).fit(df[FEATURES], df[TARGET])


def train_and_save(area: str, df: pd.DataFrame) -> None:
    print(f"{area}: {len(df)} rader ({df['time_start'].min():%Y-%m-%d} til {df['time_start'].max():%Y-%m-%d})")
    for kind, quantile in KINDS.items():
        joblib.dump(fit(df, quantile), model_path(area, kind))
        print(f"  {kind:>4}: lagret til {model_path(area, kind)}")


def calibration_offsets(data: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Per-area margin for the 80 % band, the same way model/backtest.py measures it.

    Low/high models are trained on each owner's history up to CAL_MONTHS before the
    newest data, then scored on that last window for every area they serve.
    """
    offsets, models = {}, {}
    for area in ALL_AREAS:
        own, served = data[owner(area)], data[area]
        cal_start = served["time_start"].max() - pd.DateOffset(months=CAL_MONTHS)
        window = served[served["time_start"] >= cal_start]
        if owner(area) not in models:  # NO1, NO3 and NO5 share the same calibration models
            before = own[own["time_start"] < cal_start]
            models[owner(area)] = (fit(before, Q_LOW), fit(before, Q_HIGH))
        low_model, high_model = models[owner(area)]
        lo, hi = low_model.predict(window[FEATURES]), high_model.predict(window[FEATURES])
        offsets[area] = round(conformal_offset(
            window[TARGET], pd.Series(np.minimum(lo, hi), index=window.index),
            pd.Series(np.maximum(lo, hi), index=window.index)), 4)
        print(f"{area}: kalibrering {cal_start:%Y-%m-%d} til {served['time_start'].max():%Y-%m-%d}, "
              f"{len(window)} timer, utvidelse {offsets[area] * 100:+.1f} oere")
    return offsets


if __name__ == "__main__":
    data = {area: build_features(area) for area in ALL_AREAS}
    for area in (SHARED_AREA, *ZONE_MODELS):
        train_and_save(area, data[area])
    offsets = calibration_offsets(data)
    with open(OFFSETS_PATH, "w") as f:
        json.dump(offsets, f, indent=2)
    print(f"Kalibrering lagret til {OFFSETS_PATH}")
