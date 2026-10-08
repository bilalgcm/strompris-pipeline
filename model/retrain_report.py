"""How did the live models do last month? Written before the monthly retrain replaces them.

The report goes into the retrain pull request, so you can decide whether to merge.
For each price area, on the last complete month (data the live models were not trained on,
as long as they were retrained about a month ago):
    model_ore     mean absolute error of the live forecast, oere/kWh
    naive_ore     same for "same as yesterday"; the model should beat this
    coverage_pct  share of real prices inside the calibrated 80 % band; should be near 80

Usage (from the repo root, with DATABASE_URL set):
    python model/retrain_report.py > retrain_report.md
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from backtest import last_complete_months
from features import build_features
from save_model import ALL_AREAS, FEATURES, OFFSETS_PATH, model_path, owner


def month_report(test: pd.DataFrame, mean: np.ndarray, low: np.ndarray, high: np.ndarray, offset: float) -> dict:
    """Scores for one area and month. `low`/`high` are the raw band; `offset` is the calibration margin."""
    price = test["price"].to_numpy()
    lo = np.minimum(np.minimum(low, high) - offset, mean)
    hi = np.maximum(np.maximum(low, high) + offset, mean)
    return {
        "hours": len(test),
        "model_ore": round(float(np.abs(price - mean).mean() * 100), 1),
        "naive_ore": round(float(np.abs(price - test["lag_24h"].to_numpy()).mean() * 100), 1),
        "coverage_pct": round(float(((price >= lo) & (price <= hi)).mean() * 100), 1),
    }


def markdown_table(rows: dict[str, dict]) -> str:
    """Plain markdown table, so we don't need the extra `tabulate` package that pandas uses."""
    columns = list(next(iter(rows.values())))
    lines = ["| area | " + " | ".join(columns) + " |", "|---" * (len(columns) + 1) + "|"]
    lines += [f"| {area} | " + " | ".join(str(r[c]) for c in columns) + " |" for area, r in rows.items()]
    return "\n".join(lines)


def main() -> None:
    offsets = json.loads(Path(OFFSETS_PATH).read_text())
    rows = {}
    month = None
    for area in ALL_AREAS:
        df = build_features(area)
        start = last_complete_months(df["time_start"], 1)[0]
        month = start.strftime("%Y-%m")
        end = start + pd.offsets.MonthBegin(1)
        test = df[(df["time_start"] >= start) & (df["time_start"] < end)]
        preds = {kind: joblib.load(model_path(owner(area), kind)).predict(test[FEATURES]) for kind in ("mean", "low", "high")}
        rows[area] = month_report(test, preds["mean"], preds["low"], preds["high"], offsets[area])

    print(f"## Live models in {month} (before this retrain)\n")
    print(markdown_table(rows))
    beaten = sum(r["model_ore"] < r["naive_ore"] for r in rows.values())
    print(f"\nThe model beat \"same as yesterday\" in {beaten} of {len(rows)} areas.")


if __name__ == "__main__":
    main()
