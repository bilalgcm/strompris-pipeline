"""Check the Elhub household profile against a real invoice.

Your invoice shows the average spot price you paid, weighted by when you used power.
If the NO1 household profile is realistic, applying it to the same month's hourly
prices should give an average close to that number.

Usage (from inside ingest/):
    python profile_check.py NO1 2026-09 1.32
"""

import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg

OSLO = ZoneInfo("Europe/Oslo")

SQL = """
    SELECT p.time_start, p.nok_per_kwh, h.quantity_kwh / h.metering_points AS kwh_per_home
    FROM prices p
    JOIN household_consumption h ON h.price_area = p.price_area AND h.time_start = p.time_start
    WHERE p.price_area = %s AND p.time_start >= %s AND p.time_start < %s
    ORDER BY p.time_start;
"""


def month_bounds(month: str) -> tuple[datetime, datetime]:
    first = date.fromisoformat(month + "-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return datetime.combine(first, datetime.min.time(), OSLO), datetime.combine(nxt, datetime.min.time(), OSLO)


def main() -> None:
    area, month, expected = sys.argv[1], sys.argv[2], float(sys.argv[3])
    start, end = month_bounds(month)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(SQL, (area, start, end)).fetchall()

    hours_in_month = int((end - start).total_seconds() // 3600)
    kwh = sum(float(r[2]) for r in rows)
    weighted = sum(float(r[1]) * float(r[2]) for r in rows) / kwh
    flat = sum(float(r[1]) for r in rows) / len(rows)

    print(f"{area} {month}: {len(rows)} of {hours_in_month} hours have both price and consumption")
    print(f"  Average spot, plain average of hours:      {flat:.4f} kr/kWh")
    print(f"  Average spot, weighted by household use:   {weighted:.4f} kr/kWh")
    print(f"  Your invoice:                              {expected:.4f} kr/kWh")
    print(f"  Difference (weighted vs invoice):          {(weighted - expected) / expected * 100:+.1f} %")


if __name__ == "__main__":
    main()
