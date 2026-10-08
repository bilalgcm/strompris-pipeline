"""Self-healing price refresh.

GitHub Actions treats scheduled workflows as best effort, and runs are often
delayed by hours or skipped. So the API also checks, at most every 10 minutes,
whether prices are missing, and fetches them from hvakosterstrommen.no itself.
The fetch runs in a background thread so no visitor waits for it.

The GitHub workflow stays as a backup and still stores forecasts nightly.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta

import requests

from api.freshness import OSLO, find_stale_areas

log = logging.getLogger("strompris")

BASE_URL = "https://www.hvakosterstrommen.no/api/v1"
PUBLISH_HOUR = 13  # day-ahead prices are usually on hvakosterstrommen.no by 13-14 Oslo time
CHECK_INTERVAL = 600  # seconds between checks, so we don't query on every request
HTTP_TIMEOUT = 10  # seconds per request

UPSERT_SQL = """
    INSERT INTO prices (price_area, time_start, nok_per_kwh, eur_per_kwh, exr)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (price_area, time_start)
    DO UPDATE SET
        nok_per_kwh = EXCLUDED.nok_per_kwh,
        eur_per_kwh = EXCLUDED.eur_per_kwh,
        exr         = EXCLUDED.exr;
"""


def fetch_day(day: date, area: str) -> list[dict]:
    """Fetch one day of spot prices. Raises on HTTP errors (404 = not published yet)."""
    url = f"{BASE_URL}/prices/{day.year}/{day.month:02d}-{day.day:02d}_{area}.json"
    response = requests.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def to_rows(prices: list[dict], area: str) -> list[tuple]:
    """Turn the hvakosterstrommen.no JSON into rows for UPSERT_SQL."""
    return [
        (area, datetime.fromisoformat(p["time_start"]), p["NOK_per_kWh"], p["EUR_per_kWh"], p["EXR"])
        for p in prices
    ]


def days_to_fetch(now: datetime) -> list[date]:
    """Today always, tomorrow only once prices are likely published."""
    today = now.astimezone(OSLO).date()
    if now.astimezone(OSLO).hour >= PUBLISH_HOUR:
        return [today, today + timedelta(days=1)]
    return [today]


class PriceRefresher:
    """Decides when to fetch missing prices, and makes sure only one fetch runs at a time.

    The database and HTTP calls are passed in, so the logic can be tested with fakes.
    """

    def __init__(
        self,
        get_latest: Callable[[], dict],
        fetch: Callable[[date, str], list[dict]],
        save: Callable[[list[tuple]], None],
        clock: Callable[[], float] = time.monotonic,
        interval: float = CHECK_INTERVAL,
    ):
        self.get_latest = get_latest
        self.fetch = fetch
        self.save = save
        self.clock = clock
        self.interval = interval
        self._lock = threading.Lock()
        self._last_check = None

    def due(self) -> bool:
        return self._last_check is None or self.clock() - self._last_check >= self.interval

    def refresh(self, now: datetime) -> dict:
        """Fetch and store prices for stale areas. Returns {(area, day): result} for logging and tests.

        Returns an empty dict if a check ran recently or another thread is already refreshing.
        """
        if not self.due() or not self._lock.acquire(blocking=False):
            return {}
        try:
            self._last_check = self.clock()
            stale = find_stale_areas(self.get_latest(), now, deadline_hour=PUBLISH_HOUR)
            results = {}
            for area in stale:
                for day in days_to_fetch(now):
                    try:
                        rows = to_rows(self.fetch(day, area), area)
                        self.save(rows)
                        results[(area, day)] = len(rows)
                    except Exception as e:  # one failing area must not stop the others
                        results[(area, day)] = f"{type(e).__name__}"
            if results:
                log.info("Price refresh: %s", ", ".join(f"{a} {d}: {r}" for (a, d), r in results.items()))
            return results
        except Exception:
            log.exception("Price refresh failed")
            return {}
        finally:
            self._lock.release()

    def refresh_in_background(self) -> None:
        """Start a refresh in a daemon thread if one is due. Never blocks the request."""
        if self.due() and not self._lock.locked():
            threading.Thread(target=self.refresh, args=(datetime.now(OSLO),), daemon=True).start()
