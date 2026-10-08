"""What a household actually pays per kWh, hour by hour.

The prices we store are spot prices excluding VAT. A household pays:

    spot + supplier markup, plus VAT       (energy part, to the supplier)
    minus stroemstoette                    (90 % of spot above the threshold, plus VAT)
    plus nettleie energiledd               (to the grid company, VAT and taxes included)

With Norgespris the energy part is replaced by a fixed price (settled through
the grid bill) and stroemstoette does not apply. The supplier markup still applies.

Fixed monthly costs (kapasitetsledd, supplier's monthly fee) are left out on
purpose: they don't depend on when or how much you use in a given hour, so they
don't change "what does this hour cost" or "which option is cheaper per kWh".

The monthly 5,000 kWh caps for stroemstoette and Norgespris only matter when
summing a month of real consumption, which is phase 3 (Elhub upload).

All rates below are for 2026 and must be checked every January.
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from api.freshness import OSLO
from api.holidays import is_holiday

VAT_RATE = 0.25
NO_VAT_AREAS = {"NO4"}  # households in Nord-Norge pay no VAT on electricity. NO4 is an approximation.

# Stroemstoette 2026: 90 % of the hourly spot price above 77 oere/kWh excl. VAT
SUPPORT_THRESHOLD = 0.77  # kr/kWh excl. VAT
SUPPORT_RATE = 0.90

# Norgespris 2026: 40 oere/kWh excl. VAT (50 oere incl. VAT), binding to 31.12.2026
NORGESPRIS = 0.40  # kr/kWh excl. VAT

# Elvia standard tariff for private households, 2026. Includes VAT, elavgift and Enova fee.
# Day = weekdays 06:00-22:00. Night/weekend = all other hours, weekends and public holidays.
ELVIA_DAY = 0.3640  # kr/kWh
ELVIA_NIGHT = 0.2640  # kr/kWh
DAY_START, DAY_END = 6, 22


@dataclass(frozen=True)
class Nettleie:
    """Energiledd in kr/kWh, VAT and taxes included."""

    day: float = ELVIA_DAY
    night: float = ELVIA_NIGHT
    name: str = "Elvia"


@dataclass(frozen=True)
class Breakdown:
    """Price parts for one hour, in kr/kWh. total is what the household pays."""

    energy: float  # spot price, or the Norgespris price (excl. VAT)
    markup: float  # supplier's markup (excl. VAT)
    vat: float  # VAT on energy + markup
    support: float  # stroemstoette as a negative number (incl. VAT)
    nettleie: float  # grid energiledd (incl. VAT and taxes)
    total: float

    def as_dict(self, decimals: int = 4) -> dict:
        return {k: round(v, decimals) for k, v in asdict(self).items()}


def vat_factor(area: str) -> float:
    return 1.0 if area in NO_VAT_AREAS else 1 + VAT_RATE


def is_day_rate(ts: datetime) -> bool:
    """True if Elvia's day rate applies: a weekday that isn't a holiday, 06:00-22:00 Oslo time."""
    local = ts.astimezone(OSLO)
    if local.weekday() >= 5 or is_holiday(local.date()):
        return False
    return DAY_START <= local.hour < DAY_END


def nettleie_rate(ts: datetime, nettleie: Nettleie) -> float:
    return nettleie.day if is_day_rate(ts) else nettleie.night


def support_per_kwh(spot: float, area: str) -> float:
    """Stroemstoette per kWh for one hour, incl. VAT. Zero at or below the threshold."""
    return max(0.0, spot - SUPPORT_THRESHOLD) * SUPPORT_RATE * vat_factor(area)


def _breakdown(energy: float, support: float, ts: datetime, area: str, markup: float, nettleie: Nettleie) -> Breakdown:
    vat = (energy + markup) * (vat_factor(area) - 1)
    grid = nettleie_rate(ts, nettleie)
    total = energy + markup + vat - support + grid
    return Breakdown(energy=energy, markup=markup, vat=vat, support=-support if support else 0.0, nettleie=grid, total=total)


def spot_cost(spot: float, ts: datetime, area: str, markup: float = 0.0, nettleie: Nettleie = Nettleie()) -> Breakdown:
    """Real price per kWh on a spot agreement, with stroemstoette."""
    return _breakdown(spot, support_per_kwh(spot, area), ts, area, markup, nettleie)


def norgespris_cost(ts: datetime, area: str, markup: float = 0.0, nettleie: Nettleie = Nettleie()) -> Breakdown:
    """Real price per kWh on Norgespris. The spot price doesn't matter, only the nettleie hour."""
    return _breakdown(NORGESPRIS, 0.0, ts, area, markup, nettleie)
