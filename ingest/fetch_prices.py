from datetime import date

import requests
from store import save_prices

PRICE_AREA = "NO1" # NO1 = Oslo (ostlandet)
BASE_URL = "https://www.hvakosterstrommen.no/api/v1"

def fetch_prices(day: date, area: str):
    """Fetch one day of hourly spot prices for a price area."""
    url = f"{BASE_URL}/prices/{day.year}/{day.month:02d}-{day.day:02d}_{area}.json"
    response = requests.get(url)
    response.raise_for_status()  # crash loudly if the request failed
    return response.json()


def main():
    today = date.today()
    prices = fetch_prices(today, PRICE_AREA)
    saved = save_prices(prices, PRICE_AREA)
    print(f"Lagret {saved} timer med priser for {PRICE_AREA} ({today.isoformat()}).")

if __name__ == "__main__":
    main()
