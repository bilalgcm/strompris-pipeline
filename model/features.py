import psycopg
import pandas as pd

DB_CONN = "host=localhost port=5432 dbname=strompris user=strom password=strom"


def load_prices(area="NO1"):
    """Pull all hourly prices for an area out of Postgres into a DataFrame."""
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT time_start, nok_per_kwh FROM prices WHERE price_area = %s ORDER BY time_start;",
                (area,),
            )
            rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["time_start", "price"])
    df["time_start"] = pd.to_datetime(df["time_start"], utc=True)
    df["price"] = df["price"].astype(float)
    return df


def build_features(area="NO1"):
    """Turn the raw price series into a table of features + a target."""
    df = load_prices(area)
    local = df["time_start"].dt.tz_convert("Europe/Oslo")

    df["hour"] = local.dt.hour
    df["dayofweek"] = local.dt.dayofweek          # 0 = Monday, 6 = Sunday
    df["month"] = local.dt.month
    df["is_weekend"] = (local.dt.dayofweek >= 5).astype(int)
    df["lag_24h"] = df["price"].shift(24)         # price one day earlier
    df["lag_168h"] = df["price"].shift(168)       # price one week earlier

    df = df.dropna().reset_index(drop=True)        # drop the first week (no lags yet)
    return df


if __name__ == "__main__":
    df = build_features()
    print("Shape:", df.shape)
    print("Columns:", list(df.columns))
    print("\nFirst rows:")
    print(df.head().to_string())
    print("\nPrice summary:")
    print(df["price"].describe().round(3))
