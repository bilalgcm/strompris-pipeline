from datetime import UTC, datetime

from api.freshness import AREAS, OSLO, find_stale_areas


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=OSLO)


def all_areas(ts):
    return {area: ts for area in AREAS}


def test_ok_in_the_morning_when_today_is_covered():
    assert find_stale_areas(all_areas(at(2026, 10, 8, 23)), at(2026, 10, 8, 9)) == []


def test_stale_when_today_is_missing():
    assert find_stale_areas(all_areas(at(2026, 10, 7, 23)), at(2026, 10, 8, 9)) == AREAS


def test_tomorrow_not_required_before_deadline():
    assert find_stale_areas(all_areas(at(2026, 10, 8, 23)), at(2026, 10, 8, 15, 59)) == []


def test_tomorrow_required_from_deadline():
    assert find_stale_areas(all_areas(at(2026, 10, 8, 23)), at(2026, 10, 8, 16)) == AREAS


def test_tomorrow_covered_after_deadline():
    assert find_stale_areas(all_areas(at(2026, 10, 9, 23)), at(2026, 10, 8, 17)) == []


def test_15_minute_data_counts_as_covered():
    assert find_stale_areas(all_areas(at(2026, 10, 9, 23, 45)), at(2026, 10, 8, 17)) == []


def test_reports_only_the_failing_area():
    latest = all_areas(at(2026, 10, 9, 23))
    latest["NO4"] = at(2026, 10, 8, 23)
    assert find_stale_areas(latest, at(2026, 10, 8, 17)) == ["NO4"]


def test_missing_area_is_stale():
    latest = all_areas(at(2026, 10, 8, 23))
    del latest["NO3"]
    assert find_stale_areas(latest, at(2026, 10, 8, 9)) == ["NO3"]


def test_utc_timestamps_from_the_database_work():
    # Postgres returns timestamptz values in UTC. 21:00 UTC is 23:00 Oslo in summer time.
    latest = all_areas(datetime(2026, 10, 8, 21, tzinfo=UTC))
    assert find_stale_areas(latest, at(2026, 10, 8, 9)) == []
