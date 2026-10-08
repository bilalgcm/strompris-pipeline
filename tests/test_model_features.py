"""Tests for the pure parts of model/: feature building and backtest helpers."""

import pandas as pd
import pytest
from backtest import data_coverage, last_complete_months, mae_table, mark_evening_drop
from features import add_features


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
        "naive_24h": [1.1, 1.8], "naive_168h": [1.0, 2.0], "model_no1": [0.9, 2.3], "model_zone": [1.0, 2.1],
    })
    table = mae_table(results, "area")
    assert table.loc["NO1"].tolist() == pytest.approx([15.0, 0.0, 20.0, 5.0])


def test_data_coverage_counts_hours_with_temperature():
    no1 = hourly("2026-09-01", [1.0] * 48).assign(price_area="NO1")
    no2 = hourly("2026-09-02", [1.0] * 24).assign(price_area="NO2")
    weather = pd.DataFrame({"time_start": no1["time_start"].iloc[:30], "temperature": 5.0})
    cov = data_coverage(pd.concat([no1, no2]), weather)
    assert cov.loc["NO1", "hours"] == 48 and cov.loc["NO1", "hours_with_temperature"] == 30
    assert cov.loc["NO2", "hours"] == 24 and cov.loc["NO2", "hours_with_temperature"] == 6
