"""What everyday things cost right now, and how much you save by waiting for the cheapest hours.

Consumption values are typical estimates, not measurements, and the page says so.
Energy is assumed to be spread evenly over the run time, which is a simplification:
a dishwasher uses most of its power while heating water.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Appliance:
    key: str
    name: str  # shown on the page
    kwh: float  # energy per use
    hours: int  # how long it runs, in whole hours
    shiftable: bool  # can you reasonably choose when to run it?
    note: str  # how we got the number, shown on the page


APPLIANCES = [
    Appliance("dishwasher", "Oppvaskmaskin", 1.0, 2, True, "ca. 1 kWh per vask, normalprogram"),
    Appliance("washer", "Vaskemaskin, 40 grader", 0.8, 2, True, "ca. 0,8 kWh per vask"),
    Appliance("dryer", "Tørketrommel", 2.0, 2, True, "ca. 2 kWh, varmepumpetrommel"),
    Appliance("ev", "Lade elbil 20 kWh", 20.0, 3, True, "ca. 100-130 km, lader på 7,4 kW"),
    # 90 liters (9 l/min) heated from 10 to 38 degrees: 90 * 28 * 1.163 Wh = 2.9 kWh
    Appliance("shower", "Dusj, 10 minutter", 3.0, 1, False, "ca. 3 kWh med elektrisk varmtvannsbereder"),
]


def current_index(times: list[datetime], now: datetime) -> int | None:
    """Index of the hour that contains `now`, or None if `now` is outside the data. Hourly data."""
    for i, t in enumerate(times):
        if t <= now < t + timedelta(hours=1):
            return i
    return None


def window_cost(totals: list[float], start: int, hours: int, kwh: float) -> float | None:
    """Cost in kr of using `kwh` evenly over `hours` hours from `start`. None if the data runs out."""
    if start < 0 or start + hours > len(totals):
        return None
    return kwh / hours * sum(totals[start:start + hours])


def cheapest_start(totals: list[float], earliest: int, hours: int) -> int | None:
    """Start index of the cheapest window of `hours` hours, at or after `earliest`. Ties go to the earliest."""
    best, best_sum = None, None
    for start in range(earliest, len(totals) - hours + 1):
        s = sum(totals[start:start + hours])
        if best_sum is None or s < best_sum - 1e-12:
            best, best_sum = start, s
    return best


def appliance_report(times: list[datetime], totals: list[float], now_index: int, appliance: Appliance) -> dict:
    """Cost now, and for shiftable appliances the cheapest start and the saving. All in kr."""
    now_cost = window_cost(totals, now_index, appliance.hours, appliance.kwh)
    report = {
        "key": appliance.key,
        "name": appliance.name,
        "kwh": appliance.kwh,
        "hours": appliance.hours,
        "note": appliance.note,
        "now_cost": round(now_cost, 2) if now_cost is not None else None,
        "best_start": None,
        "best_cost": None,
        "saving": None,
    }
    if not appliance.shiftable or now_cost is None:
        return report

    best = cheapest_start(totals, now_index, appliance.hours)
    best_cost = window_cost(totals, best, appliance.hours, appliance.kwh)
    report.update(
        best_start=times[best].isoformat(),
        best_cost=round(best_cost, 2),
        saving=round(now_cost - best_cost, 2),
    )
    return report
