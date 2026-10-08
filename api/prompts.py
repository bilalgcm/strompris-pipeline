"""Builds the price data that /summary and /ask send to the LLM.

Facts like "cheapest hour" and "how much you save" are computed here, in code,
and handed to the LLM as given. Letting the model scan 48 numbers itself led to
wrong minimums and inflated savings (it compared spot prices, not real bills).
"""

from datetime import date, datetime, timedelta

from api.freshness import OSLO

WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "loerdag", "soendag"]


def day_name(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day}.{day.month}."


def kr(value: float) -> str:
    """Norwegian number format: 1,24"""
    return f"{value:.2f}".replace(".", ",")


def _extremes(points: list[tuple[datetime, float]]) -> tuple[tuple[datetime, float], tuple[datetime, float]]:
    """(cheapest, most expensive) hour. Ties go to the earliest hour."""
    cheapest = min(points, key=lambda p: (p[1], p[0]))
    dearest = max(points, key=lambda p: (p[1], -p[0].timestamp()))
    return cheapest, dearest


def _hour(ts: datetime) -> str:
    return "kl " + ts.astimezone(OSLO).strftime("%H")


def day_facts(label: str, spot: list[tuple[datetime, float]], real: list[tuple[datetime, float]]) -> str:
    """One day's key numbers: spot min/max/avg, and the same for what a household actually pays."""
    (s_lo_t, s_lo), (s_hi_t, s_hi) = _extremes(spot)
    (r_lo_t, r_lo), (r_hi_t, r_hi) = _extremes(real)
    avg = sum(p for _, p in spot) / len(spot)
    saving = r_hi - r_lo
    pct = round(saving / r_hi * 100) if r_hi > 0 else 0
    return (
        f"{label}: spotpris lavest {_hour(s_lo_t)} ({kr(s_lo)} kr), hoeyest {_hour(s_hi_t)} ({kr(s_hi)} kr), "
        f"snitt {kr(avg)} kr per kWh eks. mva. "
        f"Det husholdningen faktisk betaler (inkl. mva, stroemstoette og nettleie): billigst {_hour(r_lo_t)} "
        f"({kr(r_lo)} kr), dyrest {_hour(r_hi_t)} ({kr(r_hi)} kr). "
        f"Aa flytte 1 kWh fra dyreste til billigste time sparer {kr(saving)} kr, altsaa {pct} % av regningen for den kWh-en."
    )


def price_facts(today: date, actual: list[dict], real: list[tuple[datetime, float]]) -> str:
    """FACTS block for today and, if published, tomorrow. `real` is (hour, real price) from api/costs.py."""
    lines = []
    for day, word in ((today, "I dag"), (today + timedelta(days=1), "I morgen")):
        spot = [(datetime.fromisoformat(p["time_start"]), p["nok_per_kwh"]) for p in actual
                if datetime.fromisoformat(p["time_start"]).astimezone(OSLO).date() == day]
        real_day = [(t, v) for t, v in real if t.astimezone(OSLO).date() == day]
        if spot and real_day:
            lines.append("- " + day_facts(f"{word} ({day_name(day)})", spot, real_day))
    if len(lines) == 1:
        lines.append("- Morgendagens priser er ikke publisert ennaa (kommer vanligvis rundt kl 13).")
    return "\n".join(lines)


def format_prices(prices: list[dict], key: str) -> str:
    lines = []
    for p in prices:
        ts = datetime.fromisoformat(p["time_start"]).astimezone(OSLO)
        lines.append(f"  kl {ts.strftime('%H:%M')}: {p[key]:.2f} kr/kWh")
    return "\n".join(lines)


def price_context(today: date, actual: list[dict], forecast: list[dict]) -> str:
    """Today's and (if published) tomorrow's real prices, then the forecast with its real dates.

    `actual` holds prices for today and tomorrow; they are split by Oslo date here.
    """
    tomorrow = today + timedelta(days=1)

    def on(day, prices):
        return [p for p in prices if datetime.fromisoformat(p["time_start"]).astimezone(OSLO).date() == day]

    parts = [f"Faktiske priser i dag ({day_name(today)}):\n{format_prices(on(today, actual), 'nok_per_kwh')}"]

    tomorrow_prices = on(tomorrow, actual)
    if tomorrow_prices:
        parts.append(f"Faktiske priser i morgen ({day_name(tomorrow)}), allerede publisert:\n"
                     f"{format_prices(tomorrow_prices, 'nok_per_kwh')}")
    else:
        parts.append("Morgendagens priser er ikke publisert ennaa (kommer vanligvis rundt kl 13).")

    if forecast:
        days = sorted({datetime.fromisoformat(p["time_start"]).astimezone(OSLO).date() for p in forecast})
        label = " og ".join(day_name(d) for d in days)
        parts.append(f"Prognose (usikker, fra ML-modell) for {label}:\n"
                     f"{format_prices(forecast, 'forecast_nok_per_kwh')}")

    return "\n\n".join(parts)
