"""Freshness logic for /health.

Kept free of database and model imports so it can be tested on its own.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
AREAS = ["NO1", "NO2", "NO3", "NO4", "NO5"]
TOMORROW_DEADLINE_HOUR = 16  # tomorrow's prices must be stored by 16:00 Oslo time


def find_stale_areas(latest_price: dict, now: datetime) -> list[str]:
    """Return the price areas whose newest stored price doesn't cover the required day.

    Today must always be covered. From 16:00 Oslo time, tomorrow must be covered too.
    A day counts as covered once we have its last interval (23:00 with hourly data,
    23:45 with 15-minute data), so we compare against midnight minus one hour.
    """
    now = now.astimezone(OSLO)
    today_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=OSLO)
    days_ahead = 2 if now.hour >= TOMORROW_DEADLINE_HOUR else 1
    required = today_start + timedelta(days=days_ahead) - timedelta(hours=1)

    return [
        area for area in AREAS
        if latest_price.get(area) is None or latest_price[area].astimezone(OSLO) < required
    ]
