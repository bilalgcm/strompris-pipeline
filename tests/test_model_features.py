"""Tests for the pure parts of model/: feature building and backtest helpers."""

import numpy as np
import pandas as pd
import pytest
from backtest import (
    data_coverage,
    interval_table,
    last_complete_months,
    mae_table,
    mark_evening_drop,
    pinball,
)
from features import add_features, add_previous_day
from intervals import conformal_offset


def hourly(start, prices, tz="UTC"):
    t = pd.date_range(start, periods=len(prices), freq="h", tz=tz).tz_convert("UTC")
    return pd.DataFrame({"time_start": t, "price": prices})


def weather_for(prices):
    return pd.DataFrame({"time_start": prices["time_start"], "temperature": 5.0})


def test_lags_are_looked_up_by_time():
    prices = hourly("2026-09-01", [float(i) for i in range(24 * 8)])
    df = add_features(prices, weather_for(prices))
    row = df.iloc[0]  # first row with a full week of history
    assert row["lag_24h"] == row["price"] - 24
    assert row["lag_168h"] == row["price"] - 168


def test_a_missing_hour_does_not_shift_later_lags():
    # With row-based shift(24), dropping one hour would make every later lag_24h point
    # 25 hours back. Looking up by timestamp keeps them right.
    prices = hourly("2026-09-01", [float(i) for i in range(24 * 9)]).drop(index=170)
    df = add_features(prices, weather_for(prices))
    assert (df["price"] - df["lag_24h"] == 24).all()


def test_calendar_features_use_oslo_time():
    prices = hourly("2026-09-01", [1.0] * (24 * 8), tz="Europe/Oslo")  # starts at Oslo midnight
    df = add_features(prices, weather_for(prices))
    first = df.iloc[0]  # one week later
    # time_start is UTC; 2026-09-07 22:00 UTC is Tuesday 8 Sept 00:00 in Oslo
    assert first["time_start"] == pd.Timestamp("2026-09-07 22:00", tz="UTC")
    assert (first["hour"], first["dayofweek"], first["month"], first["is_weekend"]) == (0, 1, 9, 0)


def test_last_complete_months_skips_the_running_month():
    times = hourly("2026-05-15", [1.0] * 24 * 147)["time_start"]  # 15 May to 9 Oct
    months = last_complete_months(times, 3)
    assert [m.strftime("%Y-%m") for m in months] == ["2026-07", "2026-08", "2026-09"]


def test_last_complete_months_skips_a_partial_first_month():
    times = hourly("2026-05-15", [1.0] * 24 * 147)["time_start"]
    assert last_complete_months(times, 12)[0].strftime("%Y-%m") == "2026-06"


def test_evening_drop_flags_the_next_day():
    # Day 1 averages ~1.0 but ends at 0.4 (< 70 % of the mean); day 2 is flat.
    day1 = [1.0] * 23 + [0.4]
    df = hourly("2026-10-09", day1 + [1.0] * 24, tz="Europe/Oslo")
    flagged = mark_evening_drop(df)
    assert not flagged["evening_drop_before"].iloc[:24].any()
    assert flagged["evening_drop_before"].iloc[24:].all()


def test_mae_table_in_ore():
    results = pd.DataFrame({
        "area": ["NO1", "NO1"], "price": [1.0, 2.0],
        "naive_24h": [1.1, 1.8], "naive_168h": [1.0, 2.0], "model_no1": [0.9, 2.3], "model_v2": [1.0, 2.1],
        "model_v2_zone": [1.0, 2.0],
    })
    table = mae_table(results, "area")
    assert table.loc["NO1"].tolist() == pytest.approx([15.0, 0.0, 20.0, 5.0, 0.0])


def test_data_coverage_counts_hours_with_temperature():
    no1 = hourly("2026-09-01", [1.0] * 48).assign(price_area="NO1")
    no2 = hourly("2026-09-02", [1.0] * 24).assign(price_area="NO2")
    weather = pd.DataFrame({"time_start": no1["time_start"].iloc[:30], "temperature": 5.0})
    cov = data_coverage(pd.concat([no1, no2]), weather)
    assert cov.loc["NO1", "hours"] == 48 and cov.loc["NO1", "hours_with_temperature"] == 30
    assert cov.loc["NO2", "hours"] == 24 and cov.loc["NO2", "hours_with_temperature"] == 6


# --- previous-day summary (7b) ---------------------------------------------

def test_previous_day_summary():
    # Day 1 (Oslo): 23 hours at 1.0, then 0.4 at 23:00. Day 2 rows get day 1's summary.
    df = hourly("2026-10-09", [1.0] * 23 + [0.4] + [2.0] * 24, tz="Europe/Oslo")
    out = add_previous_day(df.copy())
    day2 = out.iloc[24]
    assert day2["prev_day_last"] == 0.4
    assert day2["prev_day_min"] == 0.4 and day2["prev_day_max"] == 1.0
    assert day2["prev_day_mean"] == pytest.approx((23 * 1.0 + 0.4) / 24)


def test_previous_day_is_empty_for_the_first_day():
    df = hourly("2026-10-09", [1.0] * 48, tz="Europe/Oslo")
    out = add_previous_day(df.copy())
    assert out["prev_day_mean"].iloc[:24].isna().all()
    assert out["prev_day_mean"].iloc[24:].notna().all()


def test_incomplete_previous_day_gives_nan():
    df = hourly("2026-10-09", [1.0] * 48, tz="Europe/Oslo").drop(index=[3, 4])  # day 1 has 22 hours
    out = add_previous_day(df.copy())
    assert out["prev_day_mean"].iloc[22:].isna().all()


def test_spring_dst_day_with_23_hours_counts_as_complete():
    df = hourly("2026-03-29", [1.0] * (23 + 24), tz="Europe/Oslo")  # 29 March has 23 hours
    out = add_previous_day(df.copy())
    assert out["prev_day_mean"].iloc[23:].notna().all()


# --- prediction intervals --------------------------------------------------

def test_pinball_loss_by_hand():
    # q = 0.1. Real 1.0, forecast 0.8: under-forecast costs 0.1 * 0.2 = 0.02.
    # Real 1.0, forecast 1.2: over-forecast costs 0.9 * 0.2 = 0.18. Mean 0.10 kr = 10 oere.
    y = pd.Series([1.0, 1.0])
    f = pd.Series([0.8, 1.2])
    assert pinball(y, f, 0.1) == pytest.approx(10.0)


def test_interval_table():
    results = pd.DataFrame({
        "area": ["NO1"] * 4,
        "price":    [1.0, 1.0, 1.0, 1.0],
        "low_raw":  [0.9, 0.9, 1.1, 1.2],
        "high_raw": [1.1, 1.3, 1.3, 0.8],   # last one crossed: low above high
    })
    results["low"] = results[["low_raw", "high_raw"]].min(axis=1)
    results["high"] = results[["low_raw", "high_raw"]].max(axis=1)
    row = interval_table(results, "area").loc["NO1"]
    # Inside: rows 1, 2 and 4 (0.8-1.2 after swapping). Row 3 starts above the price.
    assert row["coverage_pct"] == 75.0
    assert row["width_ore"] == pytest.approx((20 + 40 + 20 + 40) / 4)
    assert row["crossed_pct"] == 25.0


def test_conformal_offset_by_hand():
    # Three prices inside a +-0.1 band (score -0.1), one 0.05 above it (score +0.05).
    # n = 4, k = ceil(5 * 0.8) = 4 -> the 4th smallest score: widen by 0.05.
    y = pd.Series([1.0, 1.0, 1.0, 1.0])
    low = pd.Series([0.9, 0.9, 0.9, 0.85])
    high = pd.Series([1.1, 1.1, 1.1, 0.95])
    assert conformal_offset(y, low, high) == pytest.approx(0.05)


def test_conformal_offset_narrows_a_band_that_is_too_wide():
    y = pd.Series([1.0] * 10)
    assert conformal_offset(y, y - 0.5, y + 0.5) == pytest.approx(-0.5)


def test_calibrated_band_reaches_the_target_on_new_data():
    # A band of +-0.5 around zero catches only ~38 % of standard normal values.
    # Calibrated on one sample, it should catch close to 80 % of a fresh sample.
    rng = np.random.default_rng(0)
    cal, new = pd.Series(rng.normal(size=5000)), pd.Series(rng.normal(size=5000))
    half = pd.Series(0.5, index=cal.index)
    offset = conformal_offset(cal, -half, half)
    coverage = ((new >= -0.5 - offset) & (new <= 0.5 + offset)).mean()
    assert 0.78 < coverage < 0.82
