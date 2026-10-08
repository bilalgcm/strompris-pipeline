from datetime import UTC, date, datetime, timedelta

from api.forecasting import (
    build_feature_rows,
    forecast_hours,
    oslo_midnight,
    oslo_today,
)
from api.freshness import OSLO


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=OSLO)


def test_oslo_today_differs_from_utc_just_after_midnight():
    # 00:30 Oslo on Oct 9 is still Oct 8 in UTC, which is what date.today() gave on Fly
    now = at(2026, 10, 9, 0, 30)
    assert now.astimezone(UTC).date() == date(2026, 10, 8)
    assert oslo_today(now) == date(2026, 10, 9)


def test_oslo_midnight_is_utc_22_in_summer_time():
    assert oslo_midnight(date(2026, 10, 9)) == datetime(2026, 10, 8, 22, tzinfo=UTC)


def test_before_publication_forecast_is_tomorrow():
    # Newest stored price is today 23:00 -> forecast all of tomorrow
    hours = forecast_hours(at(2026, 10, 8, 23))
    assert len(hours) == 24
    assert hours[0].astimezone(OSLO) == at(2026, 10, 9, 0)
    assert hours[-1].astimezone(OSLO) == at(2026, 10, 9, 23)


def test_after_publication_forecast_is_day_after_tomorrow():
    # Tomorrow's prices are stored -> forecast starts after them, never overlaps known prices
    latest = at(2026, 10, 9, 23)
    hours = forecast_hours(latest)
    assert hours[0].astimezone(OSLO) == at(2026, 10, 10, 0)
    assert all(t > latest for t in hours)


def test_works_with_utc_timestamps_from_database():
    hours = forecast_hours(datetime(2026, 10, 8, 21, tzinfo=UTC))  # = 23:00 Oslo
    assert hours[0].astimezone(OSLO) == at(2026, 10, 9, 0)
    assert len(hours) == 24


def test_dst_day_gets_25_hours():
    hours = forecast_hours(at(2026, 10, 24, 23))  # Oct 25 2026: clocks go back
    assert len(hours) == 25
    assert hours[-1].astimezone(OSLO) == at(2026, 10, 25, 23)


def test_spring_dst_day_gets_23_hours():
    assert len(forecast_hours(at(2026, 3, 28, 23))) == 23


def test_incomplete_day_also_forecasts_the_gap():
    # Only data until 15:00 -> forecast 16:00 today through tomorrow 23:00
    hours = forecast_hours(at(2026, 10, 8, 15))
    assert hours[0].astimezone(OSLO) == at(2026, 10, 8, 16)
    assert hours[-1].astimezone(OSLO) == at(2026, 10, 9, 23)
    assert len(hours) == 32


def test_features_use_real_lags_and_calendar():
    latest = at(2026, 10, 9, 23).astimezone(UTC)
    hours = forecast_hours(latest)
    first = hours[0]  # Saturday Oct 10, 00:00 Oslo
    known_prices = {first - timedelta(hours=24): 1.5, first - timedelta(hours=168): 0.9}
    known_temps = {first: 7.0, first - timedelta(hours=24): 8.5}

    row = build_feature_rows([first], known_prices, known_temps)[0]
    assert row == {
        "hour": 0, "dayofweek": 5, "month": 10, "is_weekend": 1,
        "lag_24h": 1.5, "lag_168h": 0.9, "temperature": 7.0, "temp_24h": 8.5,
        # Only two prices are known, so the previous day is incomplete
        "prev_day_mean": None, "prev_day_min": None, "prev_day_max": None, "prev_day_last": None,
    }


def test_lag_24h_is_always_a_known_price_after_publication():
    # The whole point of the change: every lag_24h comes from stored prices
    latest = at(2026, 10, 9, 23).astimezone(UTC)
    known = {latest - timedelta(hours=h): 1.0 for h in range(200)}
    rows = build_feature_rows(forecast_hours(latest), known, {})
    assert all(r["lag_24h"] is not None for r in rows)
    assert all(r["lag_168h"] is not None for r in rows)


def test_missing_values_become_none():
    row = build_feature_rows([at(2026, 10, 10, 12).astimezone(UTC)], {}, {})[0]
    assert row["lag_24h"] is None and row["temperature"] is None
