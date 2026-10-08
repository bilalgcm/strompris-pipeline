from datetime import date, datetime, timedelta

from api.freshness import OSLO
from api.prompts import day_name, price_context

TODAY = date(2026, 10, 8)


def prices_for(day, key="nok_per_kwh", value=1.0):
    start = datetime.combine(day, datetime.min.time(), tzinfo=OSLO)
    return [{"time_start": (start + timedelta(hours=h)).isoformat(), key: value} for h in range(24)]


def test_day_name():
    assert day_name(date(2026, 10, 10)) == "loerdag 10.10."


def test_without_tomorrow_says_not_published():
    text = price_context(TODAY, prices_for(TODAY), prices_for(TODAY + timedelta(days=1), "forecast_nok_per_kwh"))
    assert "Faktiske priser i dag (torsdag 8.10.)" in text
    assert "ikke publisert" in text
    assert "Prognose (usikker, fra ML-modell) for fredag 9.10." in text


def test_with_tomorrow_includes_real_prices_and_labels_forecast_day():
    actual = prices_for(TODAY) + prices_for(TODAY + timedelta(days=1), value=2.0)
    forecast = prices_for(TODAY + timedelta(days=2), "forecast_nok_per_kwh")
    text = price_context(TODAY, actual, forecast)
    assert "Faktiske priser i morgen (fredag 9.10.), allerede publisert" in text
    assert "2.00 kr/kWh" in text
    assert "ikke publisert" not in text
    assert "for loerdag 10.10." in text


def test_prices_are_split_by_oslo_date_not_utc():
    # 00:00 Oslo on Oct 9 is 22:00 UTC on Oct 8; it must count as tomorrow
    actual = [{"time_start": "2026-10-08T22:00:00+00:00", "nok_per_kwh": 3.0}]
    text = price_context(TODAY, actual, [])
    assert "i morgen (fredag 9.10.)" in text
    assert "kl 00:00: 3.00" in text
