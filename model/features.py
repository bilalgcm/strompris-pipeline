import os

import pandas as pd
import psycopg

DB_CONN = os.environ.get(
    "DATABASE_URL",
    "host=localhost port=5432 dbname=strompris user=strom password=strom",
)


def load_prices(area="NO1"):
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


def load_weather(location="oslo"):
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT time_start, temperature FROM weather WHERE location = %s ORDER BY time_start;",
                (location,),
            )
            rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["time_start", "temperature"])
    df["time_start"] = pd.to_datetime(df["time_start"], utc=True)
    df["temperature"] = df["temperature"].astype(float)
    return df


def add_features(prices, weather):
    """Add the model's features to one price area's hourly prices. Pure: no database.

    prices:  columns time_start (UTC), price
    weather: columns time_start (UTC), temperature

    Lags are looked up by timestamp (t - 24h, t - 168h), not by counting rows,
    so a missing hour in the data can't shift every later lag by one hour.
    """
    df = pd.merge(prices.sort_values("time_start"), weather, on="time_start", how="left")

    local = df["time_start"].dt.tz_convert("Europe/Oslo")
    df["hour"] = local.dt.hour
    df["dayofweek"] = local.dt.dayofweek
    df["month"] = local.dt.month
    df["is_weekend"] = (local.dt.dayofweek >= 5).astype(int)

    price_at = df.set_index("time_start")["price"]
    temp_at = df.set_index("time_start")["temperature"]
    df["lag_24h"] = (df["time_start"] - pd.Timedelta(hours=24)).map(price_at)
    df["lag_168h"] = (df["time_start"] - pd.Timedelta(hours=168)).map(price_at)
    df["temp_24h"] = (df["time_start"] - pd.Timedelta(hours=24)).map(temp_at)

    return df.dropna().reset_index(drop=True)


def build_features(area="NO1"):
    return add_features(load_prices(area), load_weather())


if __name__ == "__main__":
    df = build_features()
    print("Shape:", df.shape)
    print("Columns:", list(df.columns))
    print("\nFirst rows:")
    print(df.head().to_string())
    print("\nTemperature summary:")
    print(df["temperature"].describe().round(1))
