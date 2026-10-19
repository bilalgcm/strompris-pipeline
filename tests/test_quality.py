from datetime import UTC, date, datetime, timedelta

from api.freshness import OSLO
from api.freshness import TOMORROW_DEADLINE_HOUR as API_DEADLINE
from ingest.quality import (
    TOMORROW_DEADLINE_HOUR,
    check_day,
    check_weather,
    day_bounds,
    days_to_check,
)

DAY = date(2026, 10, 8)


def make_day(day, step_minutes=60, price=1.0):
    """Build a complete, valid day of rows with the given resolution."""
    start, end = day_bounds(day)
    step = timedelta(minutes=step_minutes)
    rows, t = [], start
    while t < end:
        rows.append((t, price))
        t += step
    return rows


def test_normal_hourly_day_passes():
    assert check_day(DAY, make_day(DAY)) == []


def test_normal_15_minute_day_passes():
    assert len(make_day(DAY, 15)) == 96
    assert check_day(DAY, make_day(DAY, 15)) == []


def test_dst_days_have_23_and_25_hours():
    spring, autumn = date(2026, 3, 29), date(2026, 10, 25)
    assert len(make_day(spring)) == 23
    assert len(make_day(autumn)) == 25
    assert check_day(spring, make_day(spring)) == []
    assert check_day(autumn, make_day(autumn)) == []


def test_missing_hour_is_reported():
    rows = make_day(DAY)
    del rows[10]
    problems = check_day(DAY, rows)
    assert any("expected 24" in p for p in problems)
    assert any("uneven spacing" in p for p in problems)


def test_empty_day_is_reported():
    assert check_day(DAY, []) == ["no rows"]


def test_null_price_is_reported():
    rows = make_day(DAY)
    rows[0] = (rows[0][0], None)
    assert any("null" in p for p in check_day(DAY, rows))


def test_price_in_ore_instead_of_kroner_is_reported():
    rows = make_day(DAY)
    rows[1] = (rows[1][0], 178.0)
    assert any("outside" in p for p in check_day(DAY, rows))


def test_negative_prices_are_allowed():
    assert check_day(DAY, make_day(DAY, price=-0.05)) == []


def oslo(*args):
    return datetime(*args, tzinfo=OSLO)


def test_days_to_check_only_today_before_deadline():
    assert days_to_check(oslo(2026, 10, 8, 14, 30)) == [DAY]
    assert days_to_check(oslo(2026, 10, 8, 15, 59)) == [DAY]


def test_days_to_check_includes_tomorrow_from_deadline():
    assert days_to_check(oslo(2026, 10, 8, 16, 0)) == [DAY, date(2026, 10, 9)]
    assert days_to_check(oslo(2026, 10, 8, 19, 32)) == [DAY, date(2026, 10, 9)]


def test_late_evening_run_after_midnight_checks_only_the_new_day():
    # The real failure: the 20:17 UTC run started at 22:28 UTC on 18 Oct, which is
    # 00:28 on 19 Oct in Oslo. It must check 19 Oct only, not the unpublished 20 Oct.
    assert days_to_check(datetime(2026, 10, 18, 22, 28, tzinfo=UTC)) == [date(2026, 10, 19)]


def test_days_to_check_uses_oslo_time_not_utc():
    # 15:30 UTC is 17:30 Oslo in October (UTC+2): past the deadline
    assert days_to_check(datetime(2026, 10, 8, 15, 30, tzinfo=UTC)) == [DAY, date(2026, 10, 9)]
    # 14:30 UTC is 15:30 Oslo in winter (UTC+1): before the deadline
    assert days_to_check(datetime(2026, 11, 8, 14, 30, tzinfo=UTC)) == [date(2026, 11, 8)]


def test_days_to_check_on_dst_day():
    autumn = date(2026, 10, 25)  # 25 hours
    assert days_to_check(oslo(2026, 10, 25, 17)) == [autumn, date(2026, 10, 26)]


def test_deadline_matches_health_endpoint():
    assert TOMORROW_DEADLINE_HOUR == API_DEADLINE


# --- weather ---------------------------------------------------------------

def test_weather_ok_when_yesterday_is_covered():
    # Yesterday (7 Oct) ends 23:00 Oslo = 21:00 UTC
    assert check_weather(datetime(2026, 10, 7, 21, tzinfo=UTC), DAY) == []


def test_weather_stale_like_july_2026():
    problems = check_weather(datetime(2026, 7, 24, 0, tzinfo=UTC), DAY)
    assert problems and "2026-07-24" in problems[0]


def test_weather_missing_entirely():
    assert check_weather(None, DAY) == ["no weather rows"]
