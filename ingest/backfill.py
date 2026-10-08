"""Backfill prices for one price area.

Usage (from inside ingest/):
    python backfill.py                       # NO1, last 7 days
    python backfill.py NO2 2022-09-01        # one area from a start date until today

Safe to rerun: rows are upserted. Sleeps 0.4 s between days to be polite to the free API,
so four years takes about 10 minutes per area.
"""

import sys
import time
from datetime import date, timedelta

import requests
from fetch_prices import fetch_prices
from store import save_prices

PRICE_AREA = "NO1"
DAYS_BACK = 7


def daterange(start: date, end: date):
    """Yield each date from start to end, inclusive."""
    for n in range((end - start).days + 1):
        yield start + timedelta(days=n)


def backfill(start: date, end: date, area: str):
    total = 0
    for day in daterange(start, end):
        try:
            prices = fetch_prices(day, area)
            saved = save_prices(prices, area)
            total += saved
            print(f"  {day}  ->  {saved} timer")
        except requests.HTTPError as e:
            print(f"  {day}  ->  hoppet over ({e.response.status_code})")
        time.sleep(0.4)  # be polite to a free API
    print(f"\nFerdig. {total} rader lagret eller oppdatert.")


if __name__ == "__main__":
    area = sys.argv[1] if len(sys.argv) > 1 else PRICE_AREA
    end = date.today()
    start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else end - timedelta(days=DAYS_BACK)
    print(f"Henter priser for {area} fra {start} til {end}...\n")
    backfill(start, end, area)
