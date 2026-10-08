"""Fetch hourly household electricity use per price area from Elhub's open data.

Usage (from inside ingest/, like the other ingest scripts):
    python fetch_household.py                    # last 16 days (nightly)
    python fetch_household.py 2026-01-01         # backfill from a date until today

Elhub corrects values for about two weeks after the hour (see lastUpdatedTime),
so the nightly run re-fetches 16 days and upserts. No API key is needed.
"""

import os
import sys
from datetime import date, datetime, timedelta

import requests

API_URL = "https://api.elhub.no/energy-data/v0/price-areas"
DATASET = "CONSUMPTION_PER_GROUP_MBA_HOUR"
GROUP = "household"
CHUNK_DAYS = 7  # keep each response small
NIGHTLY_DAYS = 16

UPSERT_SQL = """
    INSERT INTO household_consumption (price_area, time_start, quantity_kwh, metering_points, elhub_updated)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (price_area, time_start) DO UPDATE SET
        quantity_kwh    = EXCLUDED.quantity_kwh,
        metering_points = EXCLUDED.metering_points,
        elhub_updated   = EXCLUDED.elhub_updated;
"""


def parse_household(payload: dict) -> list[tuple]:
    """Pick the household rows out of an Elhub response.

    The response has one entry per price area (plus an aggregate with id "*" and
    an empty list). Each entry lists hourly values for every consumer group.
    """
    rows = []
    for area in payload.get("data", []):
        for v in area.get("attributes", {}).get("consumptionPerGroupMbaHour", []):
            if v.get("consumptionGroup") != GROUP:
                continue
            rows.append((
                v["priceArea"],
                datetime.fromisoformat(v["startTime"]),
                float(v["quantityKwh"]),
                int(v["meteringPointCount"]),
                datetime.fromisoformat(v["lastUpdatedTime"]),
            ))
    return rows


def date_chunks(start: date, end: date, days: int = CHUNK_DAYS) -> list[tuple[date, date]]:
    """Split [start, end) into pieces of at most `days` days."""
    chunks, current = [], start
    while current < end:
        nxt = min(current + timedelta(days=days), end)
        chunks.append((current, nxt))
        current = nxt
    return chunks


def fetch(start: date, end: date) -> dict:
    """One request. endDate is exclusive: 2026-08-01 to 2026-08-02 returns 1 August."""
    response = requests.get(
        API_URL,
        params={"dataset": DATASET, "startDate": start.isoformat(), "endDate": end.isoformat()},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def save(rows: list[tuple]) -> None:
    import psycopg  # imported here so the tests don't need a database driver

    db = os.environ.get("DATABASE_URL", "host=localhost port=5432 dbname=strompris user=strom password=strom")
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)


def main() -> None:
    today = date.today()
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else today - timedelta(days=NIGHTLY_DAYS)
    total = 0
    for chunk_start, chunk_end in date_chunks(start, today + timedelta(days=1)):
        rows = parse_household(fetch(chunk_start, chunk_end))
        save(rows)
        total += len(rows)
        print(f"Husholdning {chunk_start} - {chunk_end}: {len(rows)} rader")
    print(f"Totalt {total} rader lagret")


if __name__ == "__main__":
    main()
