import os
import sys
from datetime import date, datetime, timezone

import psycopg
import requests

DB_CONN = os.environ.get(
    "DATABASE_URL",
    "host=localhost port=5432 dbname=strompris user=strom password=strom",
)

OSLO_LAT = 59.91
OSLO_LON = 10.75
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(start_date, end_date):
    """Fetch hourly temperatures for Oslo from Open-Meteo's historical archive.

    For backfilling older periods only. The archive lags a few days behind and
    answers 400 Bad Request when end_date is too recent, which is what silently
    broke the nightly job from 24 July 2026. Use fetch_recent_weather for recent days.
    """
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


def fetch_recent_weather(past_days=7, now=None):
    """Fetch the last `past_days` days of hourly temperatures (up to 92) from the forecast API.

    Returns only hours that have already started, so forecast values for later
    today are never stored as if they had been measured.
    """
    response = requests.get(FORECAST_URL, params={
        "latitude": OSLO_LAT,
        "longitude": OSLO_LON,
        "hourly": "temperature_2m",
        "timezone": "UTC",
        "past_days": past_days,
        "forecast_days": 1,
    }, timeout=30)
    response.raise_for_status()
    return only_past(response.json(), now or datetime.now(timezone.utc))


def only_past(data, now):
    """Keep (time, temperature) pairs for hours that have started. Times are UTC strings like 2026-10-08T21:00."""
    times, temps = [], []
    for t, temp in zip(data["hourly"]["time"], data["hourly"]["temperature_2m"]):
        if datetime.fromisoformat(t).replace(tzinfo=timezone.utc) <= now:
            times.append(t)
            temps.append(temp)
    return times, temps


def save_weather(times, temps, location="oslo"):
    """Upsert hourly temperatures into Postgres."""
    rows = [
        (location, datetime.fromisoformat(t).replace(tzinfo=timezone.utc), round(temp, 1))
        for t, temp in zip(times, temps)
        if temp is not None
    ]
    with psycopg.connect(DB_CONN) as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO weather (location, time_start, temperature)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (location, time_start)
                   DO UPDATE SET temperature = EXCLUDED.temperature;""",
            rows,
        )
    return len(rows)


if __name__ == "__main__":
    # python fetch_weather.py              -> full backfill from 2022 (archive)
    # python fetch_weather.py recent 92    -> last N days (forecast API), max 92
    if len(sys.argv) > 1 and sys.argv[1] == "recent":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        times, temps = fetch_recent_weather(days)
        print(f"Henter vaerdata for Oslo, siste {days} dager...")
    else:
        start = "2022-09-01"
        end = date.today().isoformat()
        print(f"Henter vaerdata for Oslo fra {start} til {end}...")
        times, temps = fetch_weather(start, end)
    saved = save_weather(times, temps)
    print(f"Lagret {saved} timer med temperaturdata.")
