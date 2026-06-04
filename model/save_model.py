import joblib
from sklearn.ensemble import HistGradientBoostingRegressor

from features import build_features

FEATURES = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h"]
TARGET = "price"
MODEL_PATH = "model/model.joblib"


if __name__ == "__main__":
    df = build_features()
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(df[FEATURES], df[TARGET])
    joblib.dump(model, MODEL_PATH)
    print(f"Modell trent paa {len(df)} rader, lagret til {MODEL_PATH}")
