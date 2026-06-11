import time
from datetime import date, timedelta

import requests

from fetch_prices import fetch_prices
from store import save_prices

AREAS = ["NO1", "NO2", "NO3", "NO4", "NO5"]
DAYS_BACK = 30


def daterange(start, end):
    for n in range((end - start).days + 1):
        yield start + timedelta(days=n)


if __name__ == "__main__":
    end = date.today()
    start = end - timedelta(days=DAYS_BACK)
    for area in AREAS:
        print(f"\n{area}:")
        for day in daterange(start, end):
            try:
                prices = fetch_prices(day, area)
                save_prices(prices, area)
                print(f"  {day} -> {len(prices)} timer")
            except requests.HTTPError as e:
                print(f"  {day} -> hoppet over ({e.response.status_code})")
            time.sleep(0.3)
    print("\nFerdig!")
