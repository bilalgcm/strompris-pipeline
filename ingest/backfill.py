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
    end = date.today()
    start = end - timedelta(days=DAYS_BACK)
    print(f"Henter priser for {PRICE_AREA} fra {start} til {end}...\n")
    backfill(start, end, PRICE_AREA)
