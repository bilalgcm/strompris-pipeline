"""Every expected number here is calculated by hand, so the tests check the rules, not the code."""

from datetime import UTC, datetime

import pytest

from api.costs import (
    Nettleie,
    is_day_rate,
    norgespris_cost,
    spot_cost,
    support_per_kwh,
)
from api.freshness import OSLO

THURSDAY_NOON = datetime(2026, 10, 8, 12, tzinfo=OSLO)
THURSDAY_NIGHT = datetime(2026, 10, 8, 23, tzinfo=OSLO)
SATURDAY_NOON = datetime(2026, 10, 10, 12, tzinfo=OSLO)


# --- Elvia day/night -------------------------------------------------------

@pytest.mark.parametrize("ts, expected", [
    (datetime(2026, 10, 8, 5, 59, tzinfo=OSLO), False),   # before 06:00
    (datetime(2026, 10, 8, 6, 0, tzinfo=OSLO), True),     # day starts 06:00
    (datetime(2026, 10, 8, 21, 59, tzinfo=OSLO), True),   # still day
    (datetime(2026, 10, 8, 22, 0, tzinfo=OSLO), False),   # night from 22:00
    (SATURDAY_NOON, False),                                # weekend
    (datetime(2026, 10, 11, 12, tzinfo=OSLO), False),     # Sunday
    (datetime(2026, 5, 14, 12, tzinfo=OSLO), False),      # Kristi himmelfart, a Thursday
    (datetime(2026, 4, 3, 12, tzinfo=OSLO), False),       # langfredag
])
def test_day_rate(ts, expected):
    assert is_day_rate(ts) is expected


def test_day_rate_uses_oslo_time_across_spring_dst():
    # Monday 30 March 2026, first weekday after clocks go forward (UTC+2)
    assert is_day_rate(datetime(2026, 3, 30, 4, 0, tzinfo=UTC))       # 06:00 Oslo
    assert not is_day_rate(datetime(2026, 3, 30, 3, 59, tzinfo=UTC))  # 05:59 Oslo


# --- stroemstoette ---------------------------------------------------------

def test_no_support_at_or_below_threshold():
    assert support_per_kwh(0.77, "NO1") == 0
    assert support_per_kwh(0.50, "NO1") == 0


def test_support_above_threshold_includes_vat():
    # 0.9 * (1.00 - 0.77) = 0.207, plus 25 % VAT = 0.25875
    assert support_per_kwh(1.00, "NO1") == pytest.approx(0.25875)


def test_support_in_no4_has_no_vat():
    assert support_per_kwh(1.00, "NO4") == pytest.approx(0.207)


# --- spot ------------------------------------------------------------------

def test_spot_above_threshold_weekday_day():
    # 1.00 + 0.25 VAT - 0.25875 support + 0.364 nettleie = 1.35525
    cost = spot_cost(1.00, THURSDAY_NOON, "NO1")
    assert cost.vat == pytest.approx(0.25)
    assert cost.support == pytest.approx(-0.25875)
    assert cost.nettleie == pytest.approx(0.364)
    assert cost.total == pytest.approx(1.35525)


def test_spot_below_threshold_at_night():
    # 0.50 + 0.125 VAT + 0.264 nettleie = 0.889
    assert spot_cost(0.50, THURSDAY_NIGHT, "NO1").total == pytest.approx(0.889)


def test_spot_with_markup():
    # (0.50 + 0.05) * 1.25 + 0.364 = 1.0515
    assert spot_cost(0.50, THURSDAY_NOON, "NO1", markup=0.05).total == pytest.approx(1.0515)


def test_markup_does_not_change_support():
    plain = spot_cost(1.50, THURSDAY_NOON, "NO1")
    with_markup = spot_cost(1.50, THURSDAY_NOON, "NO1", markup=0.05)
    assert with_markup.support == plain.support


def test_spot_in_no4_without_vat():
    # 1.00 - 0.207 + 0.364 = 1.157
    cost = spot_cost(1.00, THURSDAY_NOON, "NO4")
    assert cost.vat == 0
    assert cost.total == pytest.approx(1.157)


def test_negative_spot_price():
    # -0.10 * 1.25 + 0.264 = 0.139, no support
    cost = spot_cost(-0.10, SATURDAY_NOON, "NO1")
    assert cost.support == 0
    assert cost.total == pytest.approx(0.139)


def test_very_high_price_support_covers_most_of_the_top():
    # 3.00 * 1.25 = 3.75; support 0.9 * 2.23 * 1.25 = 2.50875; + 0.364 = 1.60525
    assert spot_cost(3.00, THURSDAY_NOON, "NO1").total == pytest.approx(1.60525)


# --- Norgespris ------------------------------------------------------------

def test_norgespris_day_and_night():
    # 0.40 * 1.25 = 0.50, + nettleie
    assert norgespris_cost(THURSDAY_NOON, "NO1").total == pytest.approx(0.864)
    assert norgespris_cost(THURSDAY_NIGHT, "NO1").total == pytest.approx(0.764)


def test_norgespris_has_no_support_but_keeps_markup():
    # (0.40 + 0.04) * 1.25 + 0.364 = 0.914
    cost = norgespris_cost(THURSDAY_NOON, "NO1", markup=0.04)
    assert cost.support == 0
    assert cost.total == pytest.approx(0.914)


def test_norgespris_in_no4_is_40_ore():
    assert norgespris_cost(THURSDAY_NIGHT, "NO4").total == pytest.approx(0.40 + 0.264)


def test_spot_and_norgespris_break_even_below_threshold():
    # Without support, spot equals Norgespris when spot is exactly 0.40
    assert spot_cost(0.40, THURSDAY_NOON, "NO1").total == pytest.approx(norgespris_cost(THURSDAY_NOON, "NO1").total)


# --- own nettleie ----------------------------------------------------------

def test_custom_nettleie():
    own = Nettleie(day=0.50, night=0.30, name="egendefinert")
    assert spot_cost(0.50, THURSDAY_NOON, "NO1", nettleie=own).total == pytest.approx(0.625 + 0.50)
    assert spot_cost(0.50, SATURDAY_NOON, "NO1", nettleie=own).total == pytest.approx(0.625 + 0.30)


def test_as_dict_rounds_to_four_decimals():
    # Exact halves like 0.25875 are stored as 0.258749999... in binary floating point,
    # so round() gives 0.2587. A 0.0001 kr difference doesn't matter for display.
    d = spot_cost(1.00, THURSDAY_NOON, "NO1").as_dict()
    assert set(d) == {"energy", "markup", "vat", "support", "nettleie", "total"}
    assert d["total"] == pytest.approx(1.35525, abs=0.0001)
    assert all(round(v, 4) == v for v in d.values())
