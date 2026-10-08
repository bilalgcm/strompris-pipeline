"""Builds the price data block that /summary and /ask send to the LLM."""

from datetime import date, datetime, timedelta

from api.freshness import OSLO

WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "loerdag", "soendag"]


def day_name(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day}.{day.month}."


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
