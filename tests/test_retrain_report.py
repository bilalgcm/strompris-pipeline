import numpy as np
import pandas as pd
import pytest
from retrain_report import markdown_table, month_report


def test_month_report_by_hand():
    test = pd.DataFrame({"price": [1.0, 2.0, 1.0, 1.0], "lag_24h": [1.2, 1.5, 1.0, 1.1]})
    mean = np.array([1.1, 1.8, 1.0, 1.0])
    low = np.array([0.9, 1.9, 0.8, 1.2])
    high = np.array([1.2, 2.1, 0.95, 1.3])  # raw bands of hours 3 and 4 miss the price 1.0
    r = month_report(test, mean, low, high, offset=0.0)
    assert r["hours"] == 4
    assert r["model_ore"] == pytest.approx((10 + 20 + 0 + 0) / 4)
    assert r["naive_ore"] == pytest.approx((20 + 50 + 0 + 10) / 4)
    # Hour 3: the band is widened to include the forecast (1.0), so it covers the price.
    # Hour 4: band widened down to the forecast 1.0, which covers it too. Hours 1 and 2 are inside.
    assert r["coverage_pct"] == 100.0


def test_month_report_offset_widens_the_band():
    test = pd.DataFrame({"price": [1.5], "lag_24h": [1.0]})
    one = np.array([1.0])
    assert month_report(test, one, one - 0.1, one + 0.1, offset=0.0)["coverage_pct"] == 0.0
    assert month_report(test, one, one - 0.1, one + 0.1, offset=0.5)["coverage_pct"] == 100.0


def test_markdown_table():
    table = markdown_table({"NO1": {"model_ore": 15.7, "naive_ore": 19.2}})
    assert table.splitlines() == [
        "| area | model_ore | naive_ore |",
        "|---|---|---|",
        "| NO1 | 15.7 | 19.2 |",
    ]
