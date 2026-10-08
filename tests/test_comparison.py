"""Hand-calculated checks for spot vs. Norgespris over a month."""

from datetime import UTC, datetime, timedelta

import pytest

from api.comparison import (
    Hour,
    compare,
    complete_months,
    hours_in_month,
    month_bounds,
    spread_monthly_kwh,
)
from api.costs import markup_from_invoice
from api.freshness import OSLO

T0 = datetime(2026, 9, 1, 0, tzinfo=OSLO)


def hours(*pairs):
    """Build Hour objects from (kwh, spot) pairs, one hour apart."""
    return [Hour(T0 + timedelta(hours=i), kwh, spot) for i, (kwh, spot) in enumerate(pairs)]


def test_spread_keeps_total_and_shape():
    profile = [(T0, 1.0), (T0 + timedelta(hours=1), 3.0)]
    spread = spread_monthly_kwh(100, profile)
    assert [kwh for _, kwh in spread] == [25.0, 75.0]


def test_spread_rejects_empty_profile():
    with pytest.raises(ValueError):
        spread_monthly_kwh(100, [(T0, 0.0)])


def test_cheap_hours_spot_wins():
    # 10 kWh at 0.20: spot 10 * 0.20 * 1.25 = 2.50, Norgespris 10 * 0.40 * 1.25 = 5.00
    r = compare(hours((10, 0.20)), "NO1")
    assert r["spot_cost"] == 2.50
    assert r["norgespris_cost"] == 5.00
    assert r["norgespris_saves"] == -2.50


def test_expensive_hours_norgespris_wins_even_with_support():
    # 10 kWh at 1.77: spot 10 * 1.77 * 1.25 = 22.125, support 10 * 0.9 * 1.00 * 1.25 = 11.25 -> 10.875
    r = compare(hours((10, 1.77)), "NO1")
    assert r["stromstotte"] == 11.25
    assert r["spot_cost"] == pytest.approx(10.88, abs=0.01)
    assert r["norgespris_cost"] == 5.00


def test_support_is_per_hour_not_from_the_average():
    # Average spot is 0.77 (no support if you used the average), but the 1.27 hour gets support:
    # 0.9 * 0.50 * 1.25 * 10 = 5.625
    r = compare(hours((10, 0.27), (10, 1.27)), "NO1")
    assert r["avg_spot_excl_vat"] == 0.77
    assert r["stromstotte"] == pytest.approx(5.63, abs=0.01)


def test_markup_applies_to_both():
    # markup 0.0312: spot (0.20 + 0.0312) * 1.25 * 10 = 2.89, Norgespris (0.40 + 0.0312) * 1.25 * 10 = 5.39
    r = compare(hours((10, 0.20)), "NO1", markup=0.0312)
    assert r["spot_cost"] == 2.89
    assert r["norgespris_cost"] == 5.39


def test_no4_has_no_vat():
    r = compare(hours((10, 0.20)), "NO4")
    assert r["spot_cost"] == 2.00 and r["norgespris_cost"] == 4.00


def test_monthly_cap_splits_the_hour_that_crosses_it():
    # 4,000 kWh then 2,000 kWh at 2.00. Only 1,000 kWh of the second hour is under the cap.
    # Support: 5,000 * 0.9 * 1.23 * 1.25 = 6,918.75
    # Norgespris: 5,000 * 0.40 * 1.25 + 1,000 * 2.00 * 1.25 = 2,500 + 2,500 = 5,000
    r = compare(hours((4000, 2.00), (2000, 2.00)), "NO1")
    assert r["stromstotte"] == 6918.75
    assert r["norgespris_cost"] == 5000.00
    assert r["spot_cost"] == 6000 * 2.00 * 1.25 - 6918.75


def test_cap_is_applied_in_time_order_even_if_input_is_shuffled():
    a = compare(hours((4000, 2.00), (2000, 0.10)), "NO1")
    b = compare(list(reversed(hours((4000, 2.00), (2000, 0.10)))), "NO1")
    assert a == b


def test_weighted_average_matches_invoice_style():
    # Like an invoice: 1 kWh at 1.00 and 3 kWh at 2.00 -> (1 + 6) / 4 = 1.75
    assert compare(hours((1, 1.00), (3, 2.00)), "NO1")["avg_spot_excl_vat"] == 1.75


def test_zero_consumption():
    r = compare([], "NO1")
    assert r["kwh"] == 0 and r["avg_spot_excl_vat"] is None


# --- months ----------------------------------------------------------------




def test_month_bounds_in_utc():
    start, end = month_bounds("2026-09")
    assert start == datetime(2026, 8, 31, 22, tzinfo=UTC)  # 1 Sept 00:00 Oslo
    assert end == datetime(2026, 9, 30, 22, tzinfo=UTC)


def test_december_rolls_over_to_next_year():
    _, end = month_bounds("2026-12")
    assert end == datetime(2026, 12, 31, 23, tzinfo=UTC)  # 1 Jan 2027 00:00 Oslo (winter time)


@pytest.mark.parametrize("month, hours", [("2026-09", 720), ("2026-01", 744), ("2026-03", 743), ("2026-10", 745)])
def test_hours_in_month_including_dst(month, hours):
    assert hours_in_month(month) == hours


def test_complete_months_newest_first():
    counts = {"2026-08": 744, "2026-09": 720, "2026-10": 190, "2026-07": 700}
    assert complete_months(counts) == ["2026-09", "2026-08"]


def test_markup_from_invoice():
    # Telemark Kraft: 3.9 oere incl. VAT = 0.0312 kr excl. VAT. In NO4 there is no VAT.
    assert markup_from_invoice(3.9, "NO1") == pytest.approx(0.0312)
    assert markup_from_invoice(3.9, "NO4") == pytest.approx(0.039)
