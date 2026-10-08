"""Data-quality checks for stored spot prices.

Runs as the last step of the nightly GitHub Actions workflow. Exits with code 1
when something is wrong, so the run turns red and GitHub sends an email.

Environment variables:
    DATABASE_URL     Postgres connection string (required)
    CHECK_TOMORROW   "true" (default) or "false". The 12:30 UTC run sets "false",
                     because tomorrow's prices may not be published yet.
"""

import os
import sys
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
AREAS = ["NO1", "NO2", "NO3", "NO4", "NO5"]

# Sanity bounds in NOK/kWh. Wide on purpose: they catch unit bugs (øre instead of
# kroner) and garbage values, not real price spikes. Negative prices do happen.
MIN_PRICE, MAX_PRICE = -5.0, 50.0


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Start and end of an Oslo calendar day, returned in UTC.

    Working in UTC matters: subtracting two Europe/Oslo datetimes in Python uses
    wall-clock time and ignores DST, so a 25-hour day would look like 24 hours.
    """
    start = datetime.combine(day, datetime.min.time(), tzinfo=OSLO)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=OSLO)
    return start.astimezone(UTC), end.astimezone(UTC)


def days_to_check(today: date, check_tomorrow: bool) -> list[date]:
    return [today, today + timedelta(days=1)] if check_tomorrow else [today]


def check_day(day: date, rows: list[tuple[datetime, float | None]]) -> list[str]:
    """Validate one day of (time_start, nok_per_kwh) rows and return a list of problems.

    Works for DST days (23 or 25 hours) and for both hourly and 15-minute data.
    """
    if not rows:
        return ["no rows"]

    rows = sorted(rows, key=lambda r: r[0])
    times = [r[0].astimezone(UTC) for r in rows]
    problems = []

    steps = {b - a for a, b in pairwise(times)}
    step = min(steps) if steps else timedelta(hours=1)
    if len(steps) > 1:
        problems.append(f"uneven spacing: {sorted(str(s) for s in steps)}")

    start, end = day_bounds(day)
    expected = int((end - start) / step)
    if len(rows) != expected:
        problems.append(f"expected {expected} intervals of {step}, got {len(rows)}")

    nulls = sum(1 for _, price in rows if price is None)
    if nulls:
        problems.append(f"{nulls} null prices")

    out_of_range = [
        price for _, price in rows
        if price is not None and not MIN_PRICE <= float(price) <= MAX_PRICE
    ]
    if out_of_range:
        problems.append(f"{len(out_of_range)} prices outside {MIN_PRICE}..{MAX_PRICE} NOK/kWh")

    return problems


def main() -> int:
    import psycopg  # imported here so the tests don't need a database driver

    check_tomorrow = os.environ.get("CHECK_TOMORROW", "true").lower() == "true"
    today = datetime.now(OSLO).date()
    failures = 0

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for area in AREAS:
            for day in days_to_check(today, check_tomorrow):
                start, end = day_bounds(day)
                cur.execute(
                    "SELECT time_start, nok_per_kwh FROM prices "
                    "WHERE price_area = %s AND time_start >= %s AND time_start < %s;",
                    (area, start, end),
                )
                problems = check_day(day, cur.fetchall())
                status = "OK" if not problems else "FEIL: " + "; ".join(problems)
                print(f"{area} {day}: {status}")
                failures += bool(problems)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
