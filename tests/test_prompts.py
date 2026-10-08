from datetime import date, datetime, timedelta

from api.freshness import OSLO
from api.prompts import day_facts, day_name, kr, price_context, price_facts

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


# --- facts computed in code ------------------------------------------------



def hourly(day, values):
    start = datetime.combine(day, datetime.min.time(), tzinfo=OSLO)
    return [(start + timedelta(hours=h), v) for h, v in enumerate(values)]


def test_kr_uses_comma():
    assert kr(1.236) == "1,24"


def test_day_facts_finds_the_real_extremes():
    # The bug from 8 Oct: the cheapest hour was 23:00 (1.24), not 02-04 (1.28)
    spot = hourly(TODAY, [1.28, 1.66, 1.40, 1.24])
    real = hourly(TODAY, [1.30, 1.58, 1.40, 1.29])
    text = day_facts("I dag", spot, real)
    assert "spotpris lavest kl 03 (1,24 kr)" in text
    assert "hoeyest kl 01 (1,66 kr)" in text
    assert "snitt 1,40 kr" in text


def test_day_facts_saving_is_on_the_real_bill_not_spot():
    # Spot halves (1.66 -> 0.83, -50 %), but the real bill only drops 1.58 -> 1.29: 0.29 kr, 18 %
    spot = hourly(TODAY, [1.66, 0.83])
    real = hourly(TODAY, [1.58, 1.29])
    text = day_facts("I dag", spot, real)
    assert "sparer 0,29 kr, altsaa 18 %" in text


def test_ties_go_to_the_earliest_hour():
    text = day_facts("I dag", hourly(TODAY, [1.0, 1.0]), hourly(TODAY, [1.0, 1.0]))
    assert "lavest kl 00" in text and "hoeyest kl 00" in text


def test_price_facts_with_and_without_tomorrow():
    tomorrow = TODAY + timedelta(days=1)
    today_prices = prices_for(TODAY)
    real_today = hourly(TODAY, [1.0] * 24)

    only_today = price_facts(TODAY, today_prices, real_today)
    assert only_today.startswith("- I dag (torsdag 8.10.)")
    assert "ikke publisert" in only_today

    both = price_facts(TODAY, today_prices + prices_for(tomorrow, value=0.5),
                       real_today + hourly(tomorrow, [0.8] * 24))
    assert "- I morgen (fredag 9.10.)" in both
    assert "ikke publisert" not in both


def test_forecast_lines_show_the_interval():
    forecast = [{"time_start": "2026-10-10T00:00:00+02:00", "forecast_nok_per_kwh": 0.95,
                 "low_nok_per_kwh": 0.8, "high_nok_per_kwh": 1.15}]
    text = price_context(TODAY, prices_for(TODAY), forecast)
    assert "kl 00:00: 0.95 kr/kWh (80 % sannsynlig mellom 0.80 og 1.15)" in text
