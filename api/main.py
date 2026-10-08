import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import joblib
import pandas as pd
import psycopg
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from api.forecasting import (
    build_feature_rows,
    forecast_hours,
    oslo_midnight,
    oslo_today,
)
from api.freshness import AREAS, find_stale_areas
from api.prompts import price_context
from api.refresh import UPSERT_SQL, PriceRefresher, fetch_day

load_dotenv()

DB_CONN = os.environ.get(
    "DATABASE_URL",
    f"host={os.environ.get('DB_HOST', 'localhost')} port=5432 dbname=strompris user=strom password=strom"
)
OSLO = ZoneInfo("Europe/Oslo")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("strompris")
FEATURES = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h", "temperature", "temp_24h"]
MODEL = joblib.load("model/model.joblib")
LLM = anthropic.Anthropic()

LANDING_HTML = Path("api/landing.html").read_text()

app = FastAPI(title="Strompris API")


@app.get("/", response_class=HTMLResponse)
def landing():
    return LANDING_HTML


def run_query(sql, params):
    with psycopg.connect(DB_CONN) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def latest_price_per_area():
    rows = run_query("SELECT price_area, max(time_start) FROM prices GROUP BY price_area;", ())
    return {area: ts for area, ts in rows}


def save_price_rows(rows):
    with psycopg.connect(DB_CONN) as conn, conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)


# Fills in missing prices when the GitHub cron is late. See api/refresh.py.
REFRESHER = PriceRefresher(get_latest=latest_price_per_area, fetch=fetch_day, save=save_price_rows)


# --- Per-area response cache -------------------------------------------------
# /forecast and /summary are expensive (model.predict + Open-Meteo, and a Claude
# call for /summary) and get hit on every landing-page load. We cache per area
# and invalidate when the data token changes (new price data arrived, or the
# Oslo day rolled over), with a time-based backstop so we never serve stale
# content on a quiet day. Cache is per-process; on a single Fly machine that is
# the whole app. It survives suspend/resume and self-invalidates on day change.
CACHE_MAX_AGE = 6 * 3600  # seconds — refresh even if the data token is unchanged
_cache_lock = threading.Lock()
_forecast_cache: dict = {}
_summary_cache: dict = {}


def _data_token(area):
    """Cheap validity token: changes when new price data lands or the Oslo day rolls over."""
    rows = run_query("SELECT max(time_start) FROM prices WHERE price_area = %s;", (area,))
    latest = rows[0][0] if rows else None
    return (datetime.now(OSLO).date(), latest)


def cached(cache, area, compute):
    """Return cached value for `area`, recomputing when the token changes or the
    entry is older than CACHE_MAX_AGE. Thread-safe (endpoints run in a threadpool)."""
    REFRESHER.refresh_in_background()
    token = _data_token(area)
    now = time.monotonic()
    with _cache_lock:
        entry = cache.get(area)
        if entry is not None:
            cached_token, cached_at, value = entry
            if cached_token == token and now - cached_at < CACHE_MAX_AGE:
                return value
    value = compute()
    with _cache_lock:
        cache[area] = (token, now, value)
    return value


@app.get("/health")
def health():
    """Report data freshness. Always HTTP 200; status lives in the body so Fly
    autostart / uptime monitors never flap. status is one of ok | stale | error."""
    now = datetime.now(OSLO)
    try:
        latest_price = latest_price_per_area()
        forecast_rows = run_query("SELECT max(time_start) FROM forecasts;", ())
        latest_forecast = forecast_rows[0][0] if forecast_rows else None
    except Exception:
        log.exception("Health check failed")
        return {"status": "error", "checked_at": now.isoformat()}

    stale_areas = find_stale_areas(latest_price, now)

    return {
        "status": "stale" if stale_areas else "ok",
        "stale_areas": stale_areas,
        "latest_price": {
            area: (latest_price[area].isoformat() if latest_price.get(area) else None)
            for area in AREAS
        },
        "latest_forecast": latest_forecast.isoformat() if latest_forecast else None,
        "checked_at": now.isoformat(),
    }


@app.get("/prices")
def get_prices(area: str = "NO1", frm: date | None = Query(default=None, alias="from"), to: date | None = None):
    REFRESHER.refresh_in_background()
    if to is None:
        to = oslo_today()
    if frm is None:
        frm = to - timedelta(days=7)
    rows = run_query(
        "SELECT time_start, nok_per_kwh FROM prices WHERE price_area = %s AND time_start >= %s AND time_start < %s ORDER BY time_start;",
        (area, oslo_midnight(frm), oslo_midnight(to + timedelta(days=1))),
    )
    return [{"time_start": ts.isoformat(), "nok_per_kwh": float(nok)} for ts, nok in rows]


@app.get("/stats")
def get_stats(area: str = "NO1", frm: date | None = Query(default=None, alias="from"), to: date | None = None):
    if to is None:
        to = oslo_today()
    if frm is None:
        frm = to - timedelta(days=30)
    count, avg, mn, mx = run_query(
        "SELECT count(*), round(avg(nok_per_kwh),3), round(min(nok_per_kwh),3), round(max(nok_per_kwh),3) FROM prices WHERE price_area = %s AND time_start >= %s AND time_start < %s;",
        (area, oslo_midnight(frm), oslo_midnight(to + timedelta(days=1))),
    )[0]
    return {
        "area": area, "from": frm.isoformat(), "to": to.isoformat(), "hours": count,
        "avg_nok_per_kwh": float(avg) if avg is not None else None,
        "min_nok_per_kwh": float(mn) if mn is not None else None,
        "max_nok_per_kwh": float(mx) if mx is not None else None,
    }


@app.get("/prices/by-hour")
def prices_by_hour(area: str = "NO1"):
    rows = run_query(
        "SELECT date_part('hour', time_start AT TIME ZONE 'Europe/Oslo') AS hour, round(avg(nok_per_kwh),3) FROM prices WHERE price_area = %s GROUP BY hour ORDER BY hour;",
        (area,),
    )
    return [{"hour": int(h), "avg_nok_per_kwh": float(p)} for h, p in rows]


def fetch_forecast_temps():
    """Fetch temperature forecasts from Open-Meteo, keyed by UTC hour."""
    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": 59.91, "longitude": 10.75,
            "hourly": "temperature_2m", "timezone": "UTC",
            "forecast_days": 4,  # counted in UTC days; 4 covers the day after tomorrow at any hour
        })
        resp.raise_for_status()
        data = resp.json()
        return {
            datetime.fromisoformat(t).replace(tzinfo=timezone.utc): temp
            for t, temp in zip(data["hourly"]["time"], data["hourly"]["temperature_2m"])
            if temp is not None
        }
    except Exception:
        return {}


@app.get("/forecast")
def forecast(area: str = "NO1"):
    return cached(_forecast_cache, area, lambda: _compute_forecast(area))


def _compute_forecast(area):
    """Forecast every hour after the newest stored price (see api/forecasting.py).

    Before ~13:00 that is tomorrow; after tomorrow's prices are published it is the
    day after tomorrow. We never "forecast" hours whose real price is already known.
    """
    rows = run_query(
        "SELECT time_start, nok_per_kwh FROM prices WHERE price_area = %s ORDER BY time_start DESC LIMIT 200;",
        (area,),
    )
    known_prices = {ts: float(p) for ts, p in rows}
    latest = max(known_prices)

    # Recent temperatures from the DB, overridden by Open-Meteo's forecast for future hours
    temp_rows = run_query(
        "SELECT time_start, temperature FROM weather WHERE location = %s ORDER BY time_start DESC LIMIT 200;",
        ("oslo",),
    )
    known_temps = {ts: float(t) for ts, t in temp_rows}
    known_temps.update(fetch_forecast_temps())

    hours = forecast_hours(latest)
    features = pd.DataFrame(build_feature_rows(hours, known_prices, known_temps), dtype=float)
    preds = MODEL.predict(features[FEATURES])
    return [
        {"time_start": t.isoformat(), "forecast_nok_per_kwh": round(float(p), 4)}
        for t, p in zip(hours, preds)
    ]


@app.get("/ask")
def ask_question(q: str, area: str = "NO1"):
    """Answer a freeform question using real price data."""
    today = oslo_today()
    actual = get_prices(area=area, frm=today, to=today + timedelta(days=1))
    context = price_context(today, actual, forecast(area=area))

    prompt = f"""Prisdata for {area}:

{context}

Spoersmaal fra bruker: {q}

Svar kort og nyttig paa norsk (maks 3-4 setninger). Hvis spoersmaalet handler om stroemforbruk, estimer wattforbruk for apparatet, regn ut kWh, og bruk faktiske timepriser fra dataen over til aa gi et konkret kostnadsestimat i kroner. Hvis spoersmaalet ikke handler om stroem, si hoeflig at du kun kan svare paa stroemrelaterte spoersmaal."""

    response = LLM.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="Du er en hjelpsom stroemassistent for norske husholdninger. Du har tilgang til faktiske timepriser og prognoser. Gi konkrete, nyttige svar basert paa reelle data.",
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "area": area,
        "question": q,
        "answer": response.content[0].text,
    }


@app.get("/accuracy")
def accuracy(area: str = "NO1", days: int = 7):
    """Compare stored forecasts against actual prices."""
    cutoff = (datetime.now(OSLO) - timedelta(days=days)).isoformat()
    rows = run_query(
        """
        SELECT f.time_start,
               f.forecast_nok_per_kwh,
               p.nok_per_kwh,
               abs(f.forecast_nok_per_kwh - p.nok_per_kwh) as error
        FROM forecasts f
        JOIN prices p ON f.price_area = p.price_area AND f.time_start = p.time_start
        WHERE f.price_area = %s
          AND f.time_start >= %s
        ORDER BY f.time_start;
        """,
        (area, cutoff),
    )
    if not rows:
        return {"area": area, "days": days, "message": "Ingen prognoser aa sammenligne ennaa. Data samles inn nattlig."}
    errors = [float(r[3]) for r in rows]
    actuals = [float(r[2]) for r in rows]
    mae = sum(errors) / len(errors)
    mean_price = sum(actuals) / len(actuals)
    accuracy = (1 - mae / mean_price) * 100 if mean_price > 0 else 0
    return {
        "area": area,
        "days": days,
        "hours_compared": len(rows),
        "mae_kr_per_kwh": round(mae, 4),
        "mae_ore": round(mae * 100, 1),
        "accuracy_pct": round(accuracy, 1),
        "worst_miss_kr": round(max(errors), 4),
        "best_hit_kr": round(min(errors), 4),
    }

@app.get("/summary")
def daily_summary(area: str = "NO1"):
    return cached(_summary_cache, area, lambda: _compute_summary(area))


def _compute_summary(area):
    today = oslo_today()
    actual = get_prices(area=area, frm=today, to=today + timedelta(days=1))
    context = price_context(today, actual, forecast(area=area))

    prompt = f"""Her er stroemprisene for prisomraade {area}.

{context}

Gi en kort, nyttig oppsummering paa norsk (3-5 setninger). Si naar stroemmen er billigst og dyrest i dag og i morgen. Bruk faktiske priser naar de finnes, og si tydelig fra naar du bygger paa prognosen. Gi et konkret tips om naar det loenner seg aa bruke stroem (f.eks. vaskemaskin, oppvaskmaskin)."""

    response = LLM.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="Du er en hjelpsom stromprisraadgiver for norske husholdninger. Gi korte, praktiske raad basert paa prisdata.",
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "area": area,
        "date": today.isoformat(),
        "summary": response.content[0].text,
    }
