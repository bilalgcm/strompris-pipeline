from datetime import date, datetime, timedelta
import os
import os
from zoneinfo import ZoneInfo

import anthropic
import joblib
import pandas as pd
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Query

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_CONN = f"host={DB_HOST} port=5432 dbname=strompris user=strom password=strom"
OSLO = ZoneInfo("Europe/Oslo")
FEATURES = ["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h"]
MODEL = joblib.load("model/model.joblib")
LLM = anthropic.Anthropic()

app = FastAPI(title="Strompris API")


def run_query(sql, params):
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
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


@app.get("/forecast")
def forecast(area: str = "NO1"):
    rows = run_query(
        "SELECT time_start, nok_per_kwh FROM prices WHERE price_area = %s ORDER BY time_start DESC LIMIT 200;",
        (area,),
    )
    known = {ts: float(p) for ts, p in rows}
    latest = max(known)

    future, times = [], []
    for h in range(1, 25):
        t = latest + timedelta(hours=h)
        local = t.astimezone(OSLO)
        future.append({
            "hour": local.hour,
            "dayofweek": local.weekday(),
            "month": local.month,
            "is_weekend": 1 if local.weekday() >= 5 else 0,
            "lag_24h": known.get(t - timedelta(hours=24)),
            "lag_168h": known.get(t - timedelta(hours=168)),
        })
        times.append(t)

    preds = MODEL.predict(pd.DataFrame(future)[FEATURES])
    return [
        {"time_start": t.isoformat(), "forecast_nok_per_kwh": round(float(p), 4)}
        for t, p in zip(times, preds)
    ]


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
