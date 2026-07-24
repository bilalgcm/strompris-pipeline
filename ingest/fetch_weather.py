import os
from datetime import date, datetime, timezone

import requests
import psycopg

DB_CONN = os.environ.get(
    "DATABASE_URL",
    "host=localhost port=5432 dbname=strompris user=strom password=strom",
)

OSLO_LAT = 59.91
OSLO_LON = 10.75
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather(start_date, end_date):
    """Fetch hourly temperatures for Oslo from Open-Meteo."""
    response = requests.get(ARCHIVE_URL, params={
        "latitude": OSLO_LAT,
        "longitude": OSLO_LON,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m",
        "timezone": "UTC",
    })
    response.raise_for_status()
    data = response.json()
    return data["hourly"]["time"], data["hourly"]["temperature_2m"]


def save_weather(times, temps, location="oslo"):
    """Upsert hourly temperatures into Postgres."""
    rows = [
        (location, datetime.fromisoformat(t).replace(tzinfo=timezone.utc), round(temp, 1))
        for t, temp in zip(times, temps)
        if temp is not None
    ]
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO weather (location, time_start, temperature)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (location, time_start)
                   DO UPDATE SET temperature = EXCLUDED.temperature;""",
                rows,
            )
    return len(rows)


if __name__ == "__main__":
    start = "2022-09-01"
    end = date.today().isoformat()
    print(f"Henter vaerdata for Oslo fra {start} til {end}...")
    times, temps = fetch_weather(start, end)
    saved = save_weather(times, temps)
    print(f"Lagret {saved} timer med temperaturdata.")
