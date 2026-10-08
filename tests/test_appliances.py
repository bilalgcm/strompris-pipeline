"""Hand-calculated checks for 'what does it cost now' and 'when is it cheapest'."""

from datetime import datetime, timedelta

import pytest

from api.appliances import (
    APPLIANCES,
    Appliance,
    appliance_report,
    cheapest_start,
    current_index,
    window_cost,
)
from api.freshness import OSLO

START = datetime(2026, 10, 8, 0, tzinfo=OSLO)
TIMES = [START + timedelta(hours=h) for h in range(6)]
TOTALS = [1.0, 2.0, 0.5, 0.4, 3.0, 0.6]  # kr/kWh per hour

DISHWASHER = Appliance("dw", "Oppvaskmaskin", 1.0, 2, True, "")
SHOWER = Appliance("sh", "Dusj", 3.0, 1, False, "")


def test_current_index():
    assert current_index(TIMES, START + timedelta(hours=2, minutes=30)) == 2
    assert current_index(TIMES, START) == 0
    assert current_index(TIMES, START + timedelta(hours=6)) is None  # after the data
    assert current_index(TIMES, START - timedelta(minutes=1)) is None  # before the data


def test_window_cost_spreads_energy_evenly():
    # 1 kWh over 2 hours = 0.5 kWh * 1.0 + 0.5 kWh * 2.0 = 1.5 kr
    assert window_cost(TOTALS, 0, 2, 1.0) == pytest.approx(1.5)


def test_window_cost_returns_none_when_data_runs_out():
    assert window_cost(TOTALS, 5, 2, 1.0) is None


def test_cheapest_start():
    # 2-hour sums from index 0: 3.0, 2.5, 0.9, 3.4, 3.6 -> index 2
    assert cheapest_start(TOTALS, 0, 2) == 2


def test_cheapest_start_never_looks_back():
    # From index 3: sums 3.4, 3.6 -> index 3, even though index 2 was cheaper
    assert cheapest_start(TOTALS, 3, 2) == 3


def test_cheapest_start_ties_go_to_earliest():
    assert cheapest_start([1.0, 1.0, 1.0], 0, 1) == 0


def test_report_for_shiftable_appliance():
    # Now = 01:00: 0.5 * 2.0 + 0.5 * 0.5 = 1.25 kr. Best = 02:00: 0.5 * 0.5 + 0.5 * 0.4 = 0.45 kr.
    r = appliance_report(TIMES, TOTALS, 1, DISHWASHER)
    assert r["now_cost"] == 1.25
    assert r["best_start"] == TIMES[2].isoformat()
    assert r["best_cost"] == 0.45
    assert r["saving"] == 0.8


def test_report_when_now_is_already_cheapest():
    r = appliance_report(TIMES, TOTALS, 2, DISHWASHER)
    assert r["saving"] == 0
    assert r["best_start"] == TIMES[2].isoformat()


def test_report_for_appliance_that_cannot_be_shifted():
    r = appliance_report(TIMES, TOTALS, 0, SHOWER)
    assert r["now_cost"] == 3.0
    assert r["best_start"] is None and r["saving"] is None


def test_report_when_run_does_not_fit_in_known_prices():
    r = appliance_report(TIMES, TOTALS, 5, DISHWASHER)
    assert r["now_cost"] is None and r["saving"] is None


def test_shower_estimate_matches_the_physics():
    # 90 liters heated by 28 degrees: 90 * 28 * 1.163 Wh = 2.93 kWh
    shower = next(a for a in APPLIANCES if a.key == "shower")
    assert shower.kwh == pytest.approx(90 * 28 * 1.163 / 1000, abs=0.1)


def test_every_appliance_has_sane_values():
    for a in APPLIANCES:
        assert 0 < a.kwh <= 50 and 1 <= a.hours <= 8 and a.note
