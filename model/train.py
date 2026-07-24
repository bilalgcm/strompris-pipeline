from baseline import CUTOFF, split_by_time
from features import build_features
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

FEATURES_OLD = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h"]
FEATURES_NEW = FEATURES_OLD + ["temperature", "temp_24h"]
TARGET = "price"


def evaluate(model, X_train, y_train, X_test, y_test):
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    return mean_absolute_error(y_test, pred)


if __name__ == "__main__":
    df = build_features()
    train, test = split_by_time(df, CUTOFF)
    y_train, y_test = train[TARGET], test[TARGET]

    baseline = mean_absolute_error(y_test, test["lag_24h"])

    tree_old = evaluate(
        HistGradientBoostingRegressor(random_state=0),
        train[FEATURES_OLD], y_train, test[FEATURES_OLD], y_test,
    )
    tree_new = evaluate(
        HistGradientBoostingRegressor(random_state=0),
        train[FEATURES_NEW], y_train, test[FEATURES_NEW], y_test,
    )

    print("MAE paa testsettet (lavere = bedre):\n")
    print(f"  Baseline (samme som i gaar):    {baseline:.4f} kr/kWh")
    print(f"  Gradient boosting (uten vaer):   {tree_old:.4f} kr/kWh")
    print(f"  Gradient boosting (med vaer):    {tree_new:.4f} kr/kWh")

    diff = tree_old - tree_new
    if tree_new < tree_old:
        print(f"\n  Vaerdata forbedret modellen med {diff:.4f} kr/kWh ({diff / tree_old * 100:.1f}%)")
    else:
        print(f"\n  Vaerdata hjalp ikke ({-diff:.4f} kr/kWh daarligere)")
