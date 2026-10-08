from datetime import date, datetime

import requests

from api.freshness import AREAS, OSLO
from api.refresh import PriceRefresher, days_to_fetch, to_rows


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=OSLO)


def fake_day(day, area):
    """A tiny but valid hvakosterstrommen.no response."""
    return [{
        "NOK_per_kWh": 1.23, "EUR_per_kWh": 0.105, "EXR": 11.7,
        "time_start": f"{day.isoformat()}T00:00:00+02:00",
        "time_end": f"{day.isoformat()}T01:00:00+02:00",
    }]


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_refresher(latest, fetch=fake_day, clock=None):
    saved = []
    refresher = PriceRefresher(
        get_latest=lambda: latest,
        fetch=fetch,
        save=saved.extend,
        clock=clock or FakeClock(),
        interval=600,
    )
    return refresher, saved


def covered_until(ts):
    return {area: ts for area in AREAS}


def test_days_to_fetch_before_and_after_publication():
    assert days_to_fetch(at(2026, 10, 8, 12, 59)) == [date(2026, 10, 8)]
    assert days_to_fetch(at(2026, 10, 8, 13)) == [date(2026, 10, 8), date(2026, 10, 9)]


def test_to_rows_parses_api_response():
    (area, ts, nok, eur, exr), = to_rows(fake_day(date(2026, 10, 9), "NO1"), "NO1")
    assert area == "NO1"
    assert ts == at(2026, 10, 9, 0)
    assert (nok, eur, exr) == (1.23, 0.105, 11.7)


def test_does_nothing_when_data_is_fresh():
    refresher, saved = make_refresher(covered_until(at(2026, 10, 9, 23)))
    assert refresher.refresh(at(2026, 10, 8, 18)) == {}
    assert saved == []


def test_fetches_tomorrow_for_all_areas_after_publication():
    # This is the real situation found on 2026-10-08: tomorrow missing at 18:19.
    refresher, saved = make_refresher(covered_until(at(2026, 10, 8, 23)))
    results = refresher.refresh(at(2026, 10, 8, 18))
    assert {area for area, _ in results} == set(AREAS)
    assert results[("NO1", date(2026, 10, 9))] == 1
    assert len(saved) == len(AREAS) * 2  # today (harmless upsert) + tomorrow


def test_only_stale_area_is_fetched():
    latest = covered_until(at(2026, 10, 9, 23))
    latest["NO4"] = at(2026, 10, 8, 23)
    refresher, _ = make_refresher(latest)
    results = refresher.refresh(at(2026, 10, 8, 18))
    assert {area for area, _ in results} == {"NO4"}


def test_tomorrow_not_fetched_before_publication():
    refresher, _ = make_refresher(covered_until(at(2026, 10, 8, 23)))
    assert refresher.refresh(at(2026, 10, 8, 12)) == {}


def test_not_published_yet_is_handled_and_others_continue():
    def fetch(day, area):
        if day == date(2026, 10, 9):
            raise requests.HTTPError("404 Not Found")
        return fake_day(day, area)

    refresher, saved = make_refresher(covered_until(at(2026, 10, 8, 23)), fetch=fetch)
    results = refresher.refresh(at(2026, 10, 8, 13, 5))
    assert results[("NO1", date(2026, 10, 9))] == "HTTPError"
    assert results[("NO1", date(2026, 10, 8))] == 1
    assert len(saved) == len(AREAS)  # only today's rows got saved


def test_waits_for_interval_between_checks():
    clock = FakeClock()
    refresher, _ = make_refresher(covered_until(at(2026, 10, 8, 23)), clock=clock)
    assert refresher.refresh(at(2026, 10, 8, 18)) != {}
    clock.t = 599
    assert refresher.refresh(at(2026, 10, 8, 18)) == {}
    clock.t = 600
    assert refresher.refresh(at(2026, 10, 8, 18)) != {}


def test_skips_when_another_refresh_is_running():
    refresher, _ = make_refresher(covered_until(at(2026, 10, 8, 23)))
    refresher._lock.acquire()
    try:
        assert refresher.refresh(at(2026, 10, 8, 18)) == {}
    finally:
        refresher._lock.release()


def test_database_error_is_caught_and_lock_released():
    def broken():
        raise RuntimeError("database down")

    refresher = PriceRefresher(get_latest=broken, fetch=fake_day, save=lambda rows: None)
    assert refresher.refresh(at(2026, 10, 8, 18)) == {}
    assert not refresher._lock.locked()
