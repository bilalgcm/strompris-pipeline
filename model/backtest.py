"""Honest backtest of the price model: month by month, all five price areas.

For each of the last N complete months, train on everything before that month and
forecast every hour in it. That mirrors the live site: when a day is forecast,
the previous day's prices are already published, so lag_24h and lag_168h are real.
One small optimism remains: temperature is the measured value, while the live
site uses Open-Meteo's forecast.

Compared side by side:
    naive_24h     same price as the same hour yesterday
    naive_168h    same price as the same hour last week
    model_no1     the old live setup (until Oct 2026): 8 features, trained on NO1, used everywhere
    model_v2      the live setup since Oct 2026: plus a summary of the previous day, trained on NO1
    model_v2_zone same features as model_v2, but one model per area (live for ZONE_MODELS since Oct 2026)
    low / high    80 % prediction interval from quantile models (10th and 90th percentile),
                  using the live routing. Scored on coverage, width and pinball loss.
    low_cal / high_cal  the same band, widened (or narrowed) by an offset measured on the
                  3 months before each test month (split conformal prediction)

Usage (from the repo root, after `python model/export_data.py`):
    python model/backtest.py            # last 12 months
    python model/backtest.py 6          # last 6 months

Prints summary tables and writes every forecast to model/data/backtest.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from features import add_features
from intervals import CAL_MONTHS, Q_HIGH, Q_LOW, conformal_offset
from save_model import ZONE_MODELS
from sklearn.ensemble import HistGradientBoostingRegressor

DATA_DIR = Path(__file__).parent / "data"
FEATURES = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h", "temperature", "temp_24h"]
# Candidate for 7b: the same plus a summary of the previous day (see features.add_previous_day)
FEATURES_V2 = FEATURES + ["prev_day_mean", "prev_day_min", "prev_day_max", "prev_day_last"]
AREAS = ["NO1", "NO2", "NO3", "NO4", "NO5"]
METHODS = ["naive_24h", "naive_168h", "model_no1", "model_v2", "model_v2_zone"]
EVENING_DROP = 0.30  # previous day's 23:00 price at least 30 % below its daily mean
MIN_TRAIN_HOURS = 24 * 90  # don't train a per-area model on less than ~3 months of history


def data_coverage(prices: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Hours and date range per price area, plus how many of them have a temperature.

    Rows without temperature are dropped by add_features, so this shows what the
    backtest can actually use.
    """
    with_temp = prices["time_start"].isin(set(weather["time_start"]))
    out = prices.assign(with_temp=with_temp).groupby("price_area").agg(
        hours=("time_start", "size"),
        first=("time_start", "min"),
        last=("time_start", "max"),
        hours_with_temperature=("with_temp", "sum"),
    )
    out["first"] = out["first"].dt.tz_convert("Europe/Oslo").dt.date
    out["last"] = out["last"].dt.tz_convert("Europe/Oslo").dt.date
    return out


def last_complete_months(times: pd.Series, n: int) -> list[pd.Timestamp]:
    """Start (Oslo time) of the last n months that are fully inside the data."""
    local = times.dt.tz_convert("Europe/Oslo")
    first_full = (local.min() + pd.offsets.MonthBegin(0)).normalize()  # first month start at or after the data starts
    last_start = local.max().normalize().replace(day=1)  # start of the month the data ends in (may be incomplete)
    months = pd.date_range(first_full, last_start, freq="MS", tz="Europe/Oslo")[:-1]  # drop the incomplete last month
    return list(months[-n:])


def mark_evening_drop(df: pd.DataFrame) -> pd.DataFrame:
    """Flag hours whose previous day ended much cheaper than it averaged.

    Tests the hypothesis from 9-10 Oct 2026: lag_24h only shows the same hour yesterday,
    so the model can't see that prices fell sharply late the evening before.
    """
    local = df["time_start"].dt.tz_convert("Europe/Oslo")
    day = local.dt.date
    daily_mean = df.groupby(day)["price"].transform("mean")
    last_price = df.groupby(day)["price"].transform("last")
    dropped = (last_price < (1 - EVENING_DROP) * daily_mean)
    prev = pd.Series(dropped.groupby(day).first())
    prev.index = pd.to_datetime(prev.index) + pd.Timedelta(days=1)
    df = df.copy()
    df["evening_drop_before"] = pd.to_datetime(day).map(prev).fillna(False).astype(bool)
    return df


def fit(train: pd.DataFrame, features: list[str] = FEATURES, quantile: float | None = None) -> HistGradientBoostingRegressor:
    """Mean-error model by default; with `quantile`, a model for that percentile (e.g. 0.1)."""
    kwargs = {"loss": "quantile", "quantile": quantile} if quantile is not None else {}
    return HistGradientBoostingRegressor(random_state=0, **kwargs).fit(train[features], train["price"])


def pinball(y: pd.Series, f: pd.Series, q: float) -> float:
    """Standard score for a quantile forecast (lower is better), in oere/kWh."""
    diff = y - f
    return float(np.maximum(q * diff, (q - 1) * diff).mean() * 100)


def interval_table(results: pd.DataFrame, by: str, low: str = "low", high: str = "high") -> pd.DataFrame:
    """How honest and how useful the 80 % interval is, per group.

    coverage_pct  share of real prices inside [low, high]; should be close to 80
    width_ore     average width of the interval; narrower is more useful
    pinball_*     quantile scores for the low and high edge; lower is better
    crossed_pct   hours where the raw low edge came out above the high edge (they get swapped)
    """
    rows = {}
    for key, g in results.groupby(by):
        rows[key] = {
            "coverage_pct": ((g["price"] >= g[low]) & (g["price"] <= g[high])).mean() * 100,
            "width_ore": (g[high] - g[low]).mean() * 100,
            "pinball_low": pinball(g["price"], g["low_raw"], Q_LOW),
            "pinball_high": pinball(g["price"], g["high_raw"], Q_HIGH),
            "crossed_pct": (g["low_raw"] > g["high_raw"]).mean() * 100,
        }
    return pd.DataFrame(rows).T.round(1)


def run(prices: pd.DataFrame, weather: pd.DataFrame, n_months: int) -> pd.DataFrame:
    by_area = {a: mark_evening_drop(add_features(prices[prices["price_area"] == a][["time_start", "price"]], weather))
               for a in AREAS if (prices["price_area"] == a).any()}
    months = last_complete_months(by_area["NO1"]["time_start"], n_months)
    results, skipped = [], []

    for start in months:
        end = start + pd.offsets.MonthBegin(1)
        no1 = by_area["NO1"]
        model_no1 = fit(no1[no1["time_start"] < start])
        model_v2 = fit(no1[no1["time_start"] < start], FEATURES_V2)
        # Interval models follow the live routing: own models for ZONE_MODELS, the shared NO1 model for the rest
        shared_low = fit(no1[no1["time_start"] < start], FEATURES_V2, Q_LOW)
        shared_high = fit(no1[no1["time_start"] < start], FEATURES_V2, Q_HIGH)
        # Calibration: models trained before the calibration window, scored on that window
        cal_start = start - pd.DateOffset(months=CAL_MONTHS)
        cal_shared = (fit(no1[no1["time_start"] < cal_start], FEATURES_V2, Q_LOW),
                      fit(no1[no1["time_start"] < cal_start], FEATURES_V2, Q_HIGH))
        for area, df in by_area.items():
            train = df[df["time_start"] < start]
            test = df[(df["time_start"] >= start) & (df["time_start"] < end)].copy()
            if test.empty:
                skipped.append(f"{area} {start:%Y-%m}: ingen timer aa teste (mangler pris eller temperatur)")
                continue
            if area != "NO1" and len(train) < MIN_TRAIN_HOURS:
                skipped.append(f"{area} {start:%Y-%m}: bare {len(train)} timer historikk, trenger {MIN_TRAIN_HOURS}")
                continue
            test["area"] = area
            test["test_month"] = start.strftime("%Y-%m")  # not "month": that's a model feature
            test["naive_24h"] = test["lag_24h"]
            test["naive_168h"] = test["lag_168h"]
            test["model_no1"] = model_no1.predict(test[FEATURES])
            test["model_v2"] = model_v2.predict(test[FEATURES_V2])
            # For NO1 the per-zone model is the same model, so reuse its forecast
            test["model_v2_zone"] = (test["model_v2"] if area == "NO1"
                                     else fit(train, FEATURES_V2).predict(test[FEATURES_V2]))
            if area in ZONE_MODELS:
                low_model, high_model = fit(train, FEATURES_V2, Q_LOW), fit(train, FEATURES_V2, Q_HIGH)
                before_cal = df[df["time_start"] < cal_start]
                cal_low_model, cal_high_model = fit(before_cal, FEATURES_V2, Q_LOW), fit(before_cal, FEATURES_V2, Q_HIGH)
            else:
                low_model, high_model = shared_low, shared_high
                cal_low_model, cal_high_model = cal_shared
            test["low_raw"] = low_model.predict(test[FEATURES_V2])
            test["high_raw"] = high_model.predict(test[FEATURES_V2])
            test["low"] = test[["low_raw", "high_raw"]].min(axis=1)
            test["high"] = test[["low_raw", "high_raw"]].max(axis=1)

            # Offset measured on this area's calibration window, applied to the final band
            cal = df[(df["time_start"] >= cal_start) & (df["time_start"] < start)]
            cal_lo, cal_hi = cal_low_model.predict(cal[FEATURES_V2]), cal_high_model.predict(cal[FEATURES_V2])
            offset = conformal_offset(cal["price"], pd.Series(np.minimum(cal_lo, cal_hi), index=cal.index),
                                      pd.Series(np.maximum(cal_lo, cal_hi), index=cal.index))
            test["offset"] = offset
            test["low_cal"] = test["low"] - offset
            test["high_cal"] = test["high"] + offset
            results.append(test)
        print(f"  {start:%Y-%m} ferdig")

    if skipped:
        print(f"\nHoppet over {len(skipped)} omraade-maaneder:")
        for line in skipped:
            print("  " + line)
    if not results:
        raise SystemExit("Ingen maaneder kunne testes. Sjekk dekningen over.")
    return pd.concat(results, ignore_index=True)


def mae_table(results: pd.DataFrame, by: str) -> pd.DataFrame:
    """Mean absolute error in oere/kWh per group and method."""
    return (results[METHODS].sub(results["price"], axis=0).abs() * 100).groupby(results[by]).mean().round(1)


def bias_table(results: pd.DataFrame, by: str) -> pd.DataFrame:
    """Mean error in oere/kWh: positive = forecasts too high."""
    return (results[METHODS].sub(results["price"], axis=0) * 100).groupby(results[by]).mean().round(1)


def main() -> None:
    n_months = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    prices = pd.read_parquet(DATA_DIR / "prices.parquet")
    weather = pd.read_parquet(DATA_DIR / "weather.parquet")

    print("Datadekning:")
    print(data_coverage(prices, weather).to_string())
    last_weather = weather["time_start"].max()
    if last_weather < prices["time_start"].max() - pd.Timedelta(days=7):
        print(f"\nADVARSEL: temperatur mangler etter {last_weather:%Y-%m-%d}. Timer uten temperatur blir ikke testet.")

    print(f"\nBacktest over {n_months} maaneder ...")
    results = run(prices, weather, n_months)

    print("\nMAE per prisomraade (oere/kWh, lavere er bedre):")
    print(mae_table(results, "area").to_string())
    print("\nMAE per maaned, NO1:")
    print(mae_table(results[results["area"] == "NO1"], "test_month").to_string())

    early = results[results["hour"] < 6]
    print("\nNatt etter kraftig kveldsfall (kl 00-05), alle omraader:")
    print("MAE:");  print(mae_table(early, "evening_drop_before").to_string())
    print("Skjevhet (positiv = for hoyt):");  print(bias_table(early, "evening_drop_before").to_string())
    print(f"Timer med kveldsfall dagen foer: {early['evening_drop_before'].sum()} av {len(early)}")

    print(f"\n{int((Q_HIGH - Q_LOW) * 100)} % prediksjonsintervall per prisomraade (dekning boer vaere naer 80):")
    print("Ukalibrert:")
    print(interval_table(results, "area").to_string())
    print(f"Kalibrert (siste {CAL_MONTHS} maaneder foer hver testmaaned):")
    print(interval_table(results, "area", "low_cal", "high_cal").drop(columns=["pinball_low", "pinball_high", "crossed_pct"]).to_string())
    print("\nPer maaned, alle omraader, kalibrert:")
    print(interval_table(results, "test_month", "low_cal", "high_cal").drop(
        columns=["pinball_low", "pinball_high", "crossed_pct"]).to_string())
    print("\nGjennomsnittlig utvidelse per omraade (oere/kWh):")
    print((results.groupby("area")["offset"].mean() * 100).round(1).to_string())

    out = DATA_DIR / "backtest.csv"
    results[["time_start", "area", "test_month", "price", *METHODS, "low", "high", "low_cal", "high_cal",
             "evening_drop_before"]].to_csv(
        out, index=False)
    print(f"\nAlle prognoser lagret i {out}")


if __name__ == "__main__":
    main()
