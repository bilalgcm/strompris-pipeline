import os
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

load_dotenv()

DB_CONN = os.environ.get(
    "DATABASE_URL",
    f"host={os.environ.get('DB_HOST', 'localhost')} port=5432 dbname=strompris user=strom password=strom"
)
OSLO = ZoneInfo("Europe/Oslo")
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/prices")
def get_prices(area: str = "NO1", frm: date | None = Query(default=None, alias="from"), to: date | None = None):
    if to is None:
        to = date.today()
    if frm is None:
        frm = to - timedelta(days=7)
    rows = run_query(
        "SELECT time_start, nok_per_kwh FROM prices WHERE price_area = %s AND time_start >= %s AND time_start < %s ORDER BY time_start;",
        (area, frm, to + timedelta(days=1)),
    )
    return [{"time_start": ts.isoformat(), "nok_per_kwh": float(nok)} for ts, nok in rows]


@app.get("/stats")
def get_stats(area: str = "NO1", frm: date | None = Query(default=None, alias="from"), to: date | None = None):
    if to is None:
        to = date.today()
    if frm is None:
        frm = to - timedelta(days=30)
    count, avg, mn, mx = run_query(
        "SELECT count(*), round(avg(nok_per_kwh),3), round(min(nok_per_kwh),3), round(max(nok_per_kwh),3) FROM prices WHERE price_area = %s AND time_start >= %s AND time_start < %s;",
        (area, frm, to + timedelta(days=1)),
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
    """Fetch next 48h of temperature forecasts from Open-Meteo."""
    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": 59.91, "longitude": 10.75,
            "hourly": "temperature_2m", "timezone": "UTC",
            "forecast_days": 3,
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
    rows = run_query(
        "SELECT time_start, nok_per_kwh FROM prices WHERE price_area = %s AND time_start <= NOW() ORDER BY time_start DESC LIMIT 200;",
        (area,),
    )
    known_prices = {ts: float(p) for ts, p in rows}
    latest = max(known_prices)

    # Get recent temperatures from DB
    temp_rows = run_query(
        "SELECT time_start, temperature FROM weather WHERE location = %s ORDER BY time_start DESC LIMIT 200;",
        ("oslo",),
    )
    known_temps = {ts: float(t) for ts, t in temp_rows}

    # Get forecast temperatures for future hours
    forecast_temps = fetch_forecast_temps()
    known_temps.update(forecast_temps)

    future, times = [], []
    for h in range(1, 25):
        t = latest + timedelta(hours=h)
        local = t.astimezone(OSLO)
        future.append({
            "hour": local.hour,
            "dayofweek": local.weekday(),
            "month": local.month,
            "is_weekend": 1 if local.weekday() >= 5 else 0,
            "lag_24h": known_prices.get(t - timedelta(hours=24)),
            "lag_168h": known_prices.get(t - timedelta(hours=168)),
            "temperature": known_temps.get(t),
            "temp_24h": known_temps.get(t - timedelta(hours=24)),
        })
        times.append(t)

    preds = MODEL.predict(pd.DataFrame(future)[FEATURES])
    return [
        {"time_start": t.isoformat(), "forecast_nok_per_kwh": round(float(p), 4)}
        for t, p in zip(times, preds)
    ]


@app.get("/ask")
def ask_question(q: str, area: str = "NO1"):
    """Answer a freeform question using real price data."""
    today_prices = get_prices(area=area, frm=date.today(), to=date.today())
    fcast = forecast(area=area)

    def fmt(prices, key):
        lines = []
        for p in prices:
            ts = datetime.fromisoformat(p["time_start"]).astimezone(OSLO)
            lines.append(f"  kl {ts.strftime('%H:%M')}: {p[key]:.2f} kr/kWh")
        return "\n".join(lines)

    prompt = f"""Prisdata for {area} i dag:
{fmt(today_prices, "nok_per_kwh")}

Prognose neste 24 timer:
{fmt(fcast, "forecast_nok_per_kwh")}

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
    today_prices = get_prices(area=area, frm=date.today(), to=date.today())
    fcast = forecast(area=area)

    def fmt(prices, key):
        lines = []
        for p in prices:
            ts = datetime.fromisoformat(p["time_start"]).astimezone(OSLO)
            lines.append(f"  kl {ts.strftime('%H:%M')}  {p[key]:.2f} kr/kWh")
        return "\n".join(lines)

    prompt = f"""Her er stromprisene for prisomraade {area}.

Dagens faktiske priser:
{fmt(today_prices, "nok_per_kwh")}

Prognose neste 24 timer:
{fmt(fcast, "forecast_nok_per_kwh")}

Gi en kort, nyttig oppsummering paa norsk (3-5 setninger). Si naar stroemmen er billigst og dyrest i dag og i morgen, og gi et konkret tips om naar det loenner seg aa bruke stroem (f.eks. vaskemaskin, oppvaskmaskin)."""

    response = LLM.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="Du er en hjelpsom stromprisraadgiver for norske husholdninger. Gi korte, praktiske raad basert paa prisdata.",
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "area": area,
        "date": date.today().isoformat(),
        "summary": response.content[0].text,
    }
