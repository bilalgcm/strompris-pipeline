import pandas as pd
from sklearn.metrics import mean_absolute_error

from features import build_features

CUTOFF = "2025-06-03"


def split_by_time(df, cutoff):
    """Train on everything before the cutoff, test on everything after."""
    cutoff_ts = pd.Timestamp(cutoff, tz="UTC")
    train = df[df["time_start"] < cutoff_ts]
    test = df[df["time_start"] >= cutoff_ts]
    return train, test


if __name__ == "__main__":
    df = build_features()
    train, test = split_by_time(df, CUTOFF)
    print(f"Train: {len(train)} rader (foer {CUTOFF})")
    print(f"Test:  {len(test)} rader (fra {CUTOFF} og frem)\n")

    mae_yesterday = mean_absolute_error(test["price"], test["lag_24h"])
    mae_lastweek = mean_absolute_error(test["price"], test["lag_168h"])

    print("Naiv baseline - feil paa testsettet (MAE):")
    print(f"  samme som i gaar    (24t):  {mae_yesterday:.3f} kr/kWh  ({mae_yesterday * 100:.1f} oere)")
    print(f"  samme som forrige uke (168t): {mae_lastweek:.3f} kr/kWh  ({mae_lastweek * 100:.1f} oere)")

    best = min(mae_yesterday, mae_lastweek)
    print(f"\nBaren en modell maa slaa: {best:.3f} kr/kWh")
