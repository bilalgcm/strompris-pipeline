import requests
from datetime import date

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

    print(f"Strompriser for {PRICE_AREA} den {today.isoformat()}:\n")
    for hour in prices:
        start = hour["time_start"][11:16]   # grabs "HH:MM" out of the timestamp
        nok = hour["NOK_per_kWh"]
        print(f"  {start}  {nok:.2f} kr/kWh")

    values = [h["NOK_per_kWh"] for h in prices]
    print(f"\n  Snitt:  {sum(values) / len(values):.2f} kr/kWh")
    print(f"  Lavest: {min(values):.2f}  |  Hoyest: {max(values):.2f}")


if __name__ == "__main__":
    main()
