import psycopg
from fastapi import FastAPI

DB_CONN = "host=localhost port=5432 dbname=strompris user=strom password=strom"

app = FastAPI(title="Strompris API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/prices")
def get_prices(area: str = "NO1"):
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT time_start, nok_per_kwh
                FROM prices
                WHERE price_area = %s
                ORDER BY time_start;
                """,
                (area,),
            )
            rows = cur.fetchall()
    return [
        {"time_start": ts.isoformat(), "nok_per_kwh": float(nok)}
        for ts, nok in rows
    ]
