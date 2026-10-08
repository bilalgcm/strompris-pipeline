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
MODEL_PATH = "model/model.joblib"


if __name__ == "__main__":
    df = build_features()
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(df[FEATURES], df[TARGET])
    joblib.dump(model, MODEL_PATH)
    print(f"Modell trent paa {len(df)} rader ({df['time_start'].min():%Y-%m-%d} til {df['time_start'].max():%Y-%m-%d}), "
          f"{len(FEATURES)} features, lagret til {MODEL_PATH}")
