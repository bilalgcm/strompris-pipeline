from sklearn.linear_model import LinearRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from features import build_features
from baseline import split_by_time, CUTOFF

FEATURES = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h"]
TARGET = "price"


def evaluate(model, X_train, y_train, X_test, y_test):
    """Fit on the past, predict the future, return the MAE."""
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    return mean_absolute_error(y_test, pred)


if __name__ == "__main__":
    df = build_features()
    train, test = split_by_time(df, CUTOFF)
    X_train, y_train = train[FEATURES], train[TARGET]
    X_test, y_test = test[FEATURES], test[TARGET]

    baseline = mean_absolute_error(y_test, test["lag_24h"])
    linreg = evaluate(LinearRegression(), X_train, y_train, X_test, y_test)
    tree = evaluate(HistGradientBoostingRegressor(random_state=0), X_train, y_train, X_test, y_test)

    print("MAE paa testsettet (lavere = bedre):\n")
    print(f"  Baseline (samme som i gaar):  {baseline:.3f} kr/kWh")
    print(f"  Lineaer regresjon:            {linreg:.3f} kr/kWh   ({(baseline - linreg) / baseline * 100:+.1f}% vs baseline)")
    print(f"  Gradient boosting:            {tree:.3f} kr/kWh   ({(baseline - tree) / baseline * 100:+.1f}% vs baseline)")
