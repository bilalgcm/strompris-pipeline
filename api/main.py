from datetime import date, timedelta

import psycopg
from fastapi import FastAPI, Query

DB_CONN = "host=localhost port=5432 dbname=strompris user=strom password=strom"

app = FastAPI(title="Strompris API")


def run_query(sql, params):
    """Open a connection, run one query, return all rows."""
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/prices")
def get_prices(
    area: str = "NO1",
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = None,
):
    if to is None:
        to = date.today()
    if frm is None:
        frm = to - timedelta(days=7)
    rows = run_query(
        """
        SELECT time_start, nok_per_kwh
        FROM prices
        WHERE price_area = %s
          AND time_start >= %s
          AND time_start < %s
        ORDER BY time_start;
        """,
        (area, frm, to + timedelta(days=1)),
    )
    return [
        {"time_start": ts.isoformat(), "nok_per_kwh": float(nok)}
        for ts, nok in rows
    ]


@app.get("/stats")
def get_stats(
    area: str = "NO1",
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = None,
):
    if to is None:
        to = date.today()
    if frm is None:
        frm = to - timedelta(days=30)
    count, avg, mn, mx = run_query(
        """
        SELECT count(*),
               round(avg(nok_per_kwh), 3),
               round(min(nok_per_kwh), 3),
               round(max(nok_per_kwh), 3)
        FROM prices
        WHERE price_area = %s
          AND time_start >= %s
          AND time_start < %s;
        """,
        (area, frm, to + timedelta(days=1)),
    )[0]
    return {
        "area": area,
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "hours": count,
        "avg_nok_per_kwh": float(avg) if avg is not None else None,
        "min_nok_per_kwh": float(mn) if mn is not None else None,
        "max_nok_per_kwh": float(mx) if mx is not None else None,
    }


@app.get("/prices/by-hour")
def prices_by_hour(area: str = "NO1"):
    rows = run_query(
        """
        SELECT date_part('hour', time_start AT TIME ZONE 'Europe/Oslo') AS hour,
               round(avg(nok_per_kwh), 3) AS avg_price
        FROM prices
        WHERE price_area = %s
        GROUP BY hour
        ORDER BY hour;
        """,
        (area,),
    )
    return [
        {"hour": int(h), "avg_nok_per_kwh": float(p)}
        for h, p in rows
    ]
