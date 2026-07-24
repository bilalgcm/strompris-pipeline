import joblib
from features import build_features
from sklearn.ensemble import HistGradientBoostingRegressor

FEATURES = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h", "temperature", "temp_24h"]
TARGET = "price"
MODEL_PATH = "model/model.joblib"


if __name__ == "__main__":
    df = build_features()
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(df[FEATURES], df[TARGET])
    joblib.dump(model, MODEL_PATH)
    print(f"Modell trent paa {len(df)} rader med vaerdata, lagret til {MODEL_PATH}")
