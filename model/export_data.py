"""Export prices and weather from the database to local files for offline backtesting.

Usage (from the repo root, with DATABASE_URL set):
    python model/export_data.py

Writes model/data/prices.parquet and model/data/weather.parquet (a few MB, ignored by git).
Read-only: it only runs SELECT queries.
"""

import os
from pathlib import Path

import pandas as pd
import psycopg

DATA_DIR = Path(__file__).parent / "data"


def export(sql: str, columns: list[str], float_columns: list[str], filename: str) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(sql).fetchall()
    df = pd.DataFrame(rows, columns=columns)
    df["time_start"] = pd.to_datetime(df["time_start"], utc=True)
    df[float_columns] = df[float_columns].astype(float)
    DATA_DIR.mkdir(exist_ok=True)
    df.to_parquet(DATA_DIR / filename, index=False)
    print(f"{filename}: {len(df)} rader, {df['time_start'].min():%Y-%m-%d} til {df['time_start'].max():%Y-%m-%d}")


if __name__ == "__main__":
    export(
        "SELECT price_area, time_start, nok_per_kwh FROM prices ORDER BY price_area, time_start;",
        ["price_area", "time_start", "price"],
        ["price"],
        "prices.parquet",
    )
    export(
        "SELECT time_start, temperature FROM weather WHERE location = 'oslo' ORDER BY time_start;",
        ["time_start", "temperature"],
        ["temperature"],
        "weather.parquet",
    )
