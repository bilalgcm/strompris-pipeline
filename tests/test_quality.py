from datetime import date, timedelta

from ingest.quality import check_day, day_bounds, days_to_check

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


def test_days_to_check():
    assert days_to_check(DAY, check_tomorrow=False) == [DAY]
    assert days_to_check(DAY, check_tomorrow=True) == [DAY, date(2026, 10, 9)]
