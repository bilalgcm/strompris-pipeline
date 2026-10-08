"""Pure helpers for dates and the forecast window.

Kept free of database, model and HTTP imports so they can be tested on their own.
All timestamps are UTC-aware datetimes, like the ones Postgres returns.
"""

from datetime import UTC, date, datetime, timedelta

from api.freshness import OSLO

# The live model's inputs, in order. Must match model/save_model.py (a test checks this,
# and that the saved model/model.joblib was trained on exactly these names).
FEATURES = [
    "hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h", "temperature", "temp_24h",
    "prev_day_mean", "prev_day_min", "prev_day_max", "prev_day_last",
]
MIN_HOURS_PER_DAY = 23  # same rule as model/features.py: fewer hours = incomplete day

# Areas with their own model. Chosen by the Oct 2026 backtest with a rule fixed in advance:
# own model only if it beats the shared NO1-trained model by 5 % or more over 12 months.
# NO2: 17.2 vs 18.2 oere, NO4: 14.6 vs 16.9. (NO3 was 15 % worse with its own model.)
# Must match model/save_model.py ZONE_MODELS (checked by tests/test_model_artifact.py).
ZONE_MODELS = ("NO2", "NO4")

# Each model comes in three kinds: the forecast itself ("mean") and the 10th and 90th
# percentile ("low", "high"), which give an 80 % prediction interval. See model/backtest.py.
KINDS = ("mean", "low", "high")


def model_path(area: str, kind: str = "mean") -> str:
    """Which model file serves an area: its own if it has one, otherwise the shared model.

    model/model.joblib, model/model_low.joblib, model/model_NO2.joblib, model/model_NO2_high.joblib, ...
    """
    name = "model" + (f"_{area}" if area in ZONE_MODELS else "") + ("" if kind == "mean" else f"_{kind}")
    return f"model/{name}.joblib"


OFFSETS_PATH = "model/interval_offsets.json"  # written by model/save_model.py


def calibrated_interval(point: float, low: float, high: float, offset: float) -> tuple[float, float]:
    """Widen the raw quantile band by the area's calibration offset, then order it.

    Raw quantile models covered only ~70 % in the backtest; the offset (split conformal
    prediction, measured on the last 3 months) brings the band back to ~80 %.
    A negative offset narrows the band; if it would narrow past zero width, the band
    collapses to the forecast instead of flipping inside out.
    """
    low, high = min(low, high) - offset, max(low, high) + offset
    if low > high:
        low = high = point
    return ordered_interval(point, low, high)


def ordered_interval(point: float, low: float, high: float) -> tuple[float, float]:
    """Make sure low <= point <= high.

    Three separately trained models can disagree slightly: the low model can come out above
    the high one, or the forecast can fall just outside the band. The band is widened to
    contain all three rather than showing something impossible.
    """
    return min(point, low, high), max(point, low, high)


def oslo_today(now: datetime | None = None) -> date:
    """Today's date in Oslo. date.today() on Fly is UTC, which is wrong 00:00-02:00 Oslo time."""
    return (now or datetime.now(OSLO)).astimezone(OSLO).date()


def oslo_midnight(day: date) -> datetime:
    """Start of an Oslo calendar day, as a UTC datetime.

    Passing a plain date to Postgres compares it against UTC midnight, which is
    01:00 or 02:00 Oslo time, so date ranges have to be converted first.
    """
    return datetime.combine(day, datetime.min.time(), tzinfo=OSLO).astimezone(UTC)


def forecast_hours(latest: datetime) -> list[datetime]:
    """Every hour after the newest known price, up to the end of the next Oslo day.

    With a complete day stored (latest = 23:00 Oslo) this is exactly the next
    calendar day: 24 hours, or 23/25 on DST days. If the newest day is incomplete,
    the gap is forecast too, so we never return fewer than 24 hours.
    """
    latest = latest.astimezone(UTC)
    # Use calendar days, not "+24 hours": on a 23-hour DST day, +24h lands in the day after.
    last_day = latest.astimezone(OSLO).date() + timedelta(days=1)
    end = oslo_midnight(last_day + timedelta(days=1))
    hours, t = [], latest + timedelta(hours=1)
    while t < end:
        hours.append(t)
        t += timedelta(hours=1)
    return hours


def previous_day_summary(known_prices: dict, day: date) -> dict | None:
    """Mean, min, max and last price of one Oslo day, or None if the day is incomplete.

    Mirrors model/features.py::add_previous_day, so serving and training agree.
    """
    start, end = oslo_midnight(day), oslo_midnight(day + timedelta(days=1))
    points = sorted((t, p) for t, p in known_prices.items() if start <= t.astimezone(UTC) < end)
    if len(points) < MIN_HOURS_PER_DAY:
        return None
    prices = [p for _, p in points]
    return {"mean": sum(prices) / len(prices), "min": min(prices), "max": max(prices), "last": prices[-1]}


def build_feature_rows(hours: list[datetime], known_prices: dict, known_temps: dict) -> list[dict]:
    """Build the model's features (FEATURES) for each forecast hour, the same way model/features.py does.

    Lags are counted in UTC hours, which matches training (looked up by timestamp).
    The previous-day summary uses the Oslo day before each hour's own day.
    Missing values become None; HistGradientBoostingRegressor handles them natively.
    """
    summaries: dict[date, dict | None] = {}
    rows = []
    for t in hours:
        local = t.astimezone(OSLO)
        rows.append({
            "hour": local.hour,
            "dayofweek": local.weekday(),
            "month": local.month,
            "is_weekend": 1 if local.weekday() >= 5 else 0,
            "lag_24h": known_prices.get(t - timedelta(hours=24)),
            "lag_168h": known_prices.get(t - timedelta(hours=168)),
            "temperature": known_temps.get(t),
            "temp_24h": known_temps.get(t - timedelta(hours=24)),
        })
        prev_day = local.date() - timedelta(days=1)
        if prev_day not in summaries:
            summaries[prev_day] = previous_day_summary(known_prices, prev_day)
        summary = summaries[prev_day] or {}
        for key in ("mean", "min", "max", "last"):
            rows[-1][f"prev_day_{key}"] = summary.get(key)
    return rows
