import joblib
from features import build_features
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


def model_path(area: str) -> str:
    return "model/model.joblib" if area == SHARED_AREA else f"model/model_{area}.joblib"


def train_and_save(area: str) -> None:
    df = build_features(area)
    model = HistGradientBoostingRegressor(random_state=0).fit(df[FEATURES], df[TARGET])
    path = model_path(area)
    joblib.dump(model, path)
    print(f"{area}: trent paa {len(df)} rader ({df['time_start'].min():%Y-%m-%d} til "
          f"{df['time_start'].max():%Y-%m-%d}), {len(FEATURES)} features, lagret til {path}")


if __name__ == "__main__":
    for area in (SHARED_AREA, *ZONE_MODELS):
        train_and_save(area)
