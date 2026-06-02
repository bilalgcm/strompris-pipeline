from datetime import datetime
import psycopg

DB_CONN = "host=localhost port=5432 dbname=strompris user=strom password=strom"

UPSERT_SQL = """
    INSERT INTO prices (price_area, time_start, nok_per_kwh, eur_per_kwh, exr)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (price_area, time_start)
    DO UPDATE SET
        nok_per_kwh = EXCLUDED.nok_per_kwh,
        eur_per_kwh = EXCLUDED.eur_per_kwh,
        exr         = EXCLUDED.exr;
"""


def save_prices(prices, area):
    """Insert (or update) one day of hourly prices into Postgres."""
    rows = [
        (
            area,
            datetime.fromisoformat(hour["time_start"]),
            hour["NOK_per_kWh"],
            hour["EUR_per_kWh"],
            hour["EXR"],
        )
        for hour in prices
    ]
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
    return len(rows)
