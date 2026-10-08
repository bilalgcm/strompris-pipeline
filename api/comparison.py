"""Spot (with stroemstoette) vs. Norgespris for one month of real or estimated consumption.

Input is a list of hours with kWh used and the spot price. Nettleie is left out:
it's the same on both options, so it can't change which one is cheaper.

Both schemes cover only the first 5,000 kWh in a month (MONTHLY_CAP_KWH):
- spot: kWh above the cap get no stroemstoette
- Norgespris: kWh above the cap are billed at the ordinary spot price
The cap is applied in time order, so it is the last hours of a big month that fall outside it.
"""

from dataclasses import dataclass
from datetime import date, datetime

from api.costs import MONTHLY_CAP_KWH, NORGESPRIS, support_per_kwh, vat_factor
from api.forecasting import oslo_midnight


@dataclass(frozen=True)
class Hour:
    time_start: datetime
    kwh: float
    spot: float  # kr/kWh excl. VAT


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """Start and end of an Oslo calendar month ("2026-09"), as UTC datetimes."""
    first = date.fromisoformat(month + "-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return oslo_midnight(first), oslo_midnight(nxt)


def hours_in_month(month: str) -> int:
    """743 in March and 745 in October because of DST, otherwise days * 24."""
    start, end = month_bounds(month)
    return int((end - start).total_seconds() // 3600)


def complete_months(hours_per_month: dict[str, int]) -> list[str]:
    """Months where every hour has data, newest first. Input: {"2026-09": 720, ...}."""
    return sorted((m for m, n in hours_per_month.items() if n == hours_in_month(m)), reverse=True)


def spread_monthly_kwh(total_kwh: float, profile: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """Spread a month's kWh over its hours in proportion to a consumption profile.

    `profile` holds (hour, any positive weight), e.g. average kWh per household
    from Elhub. Only the shape matters; the result always sums to total_kwh.
    """
    weight_sum = sum(w for _, w in profile)
    if weight_sum <= 0:
        raise ValueError("profile has no consumption")
    return [(t, total_kwh * w / weight_sum) for t, w in profile]


def compare(hours: list[Hour], area: str, markup: float = 0.0) -> dict:
    """Energy cost of the same consumption on spot and on Norgespris, in kr incl. VAT."""
    vat = vat_factor(area)
    used = spot_cost = support = norgespris_cost = weighted_spot = 0.0

    for h in sorted(hours, key=lambda h: h.time_start):
        covered = max(0.0, min(h.kwh, MONTHLY_CAP_KWH - used))  # kWh still under the monthly cap
        uncovered = h.kwh - covered
        used += h.kwh

        hour_support = covered * support_per_kwh(h.spot, area)
        spot_cost += h.kwh * (h.spot + markup) * vat - hour_support
        support += hour_support
        norgespris_cost += covered * (NORGESPRIS + markup) * vat + uncovered * (h.spot + markup) * vat
        weighted_spot += h.kwh * h.spot

    return {
        "kwh": round(used, 2),
        "spot_cost": round(spot_cost, 2),
        "stromstotte": round(support, 2),
        "norgespris_cost": round(norgespris_cost, 2),
        "norgespris_saves": round(spot_cost - norgespris_cost, 2),  # negative = spot was cheaper
        "avg_spot_excl_vat": round(weighted_spot / used, 4) if used else None,  # what your invoice shows, excl. VAT
    }
