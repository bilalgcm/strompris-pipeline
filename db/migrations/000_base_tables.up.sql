-- 000 up: the three original tables, so a fresh database (local Docker, a new Neon branch)
-- can be set up from scratch. They were first created by hand on Neon; IF NOT EXISTS makes
-- this a no-op there.

CREATE TABLE IF NOT EXISTS prices (
    price_area  TEXT        NOT NULL,
    time_start  TIMESTAMPTZ NOT NULL,
    nok_per_kwh NUMERIC     NOT NULL,  -- spot price excl. VAT
    eur_per_kwh NUMERIC,
    exr         NUMERIC,
    PRIMARY KEY (price_area, time_start)
);

CREATE TABLE IF NOT EXISTS weather (
    location    TEXT        NOT NULL,  -- only 'oslo' is used
    time_start  TIMESTAMPTZ NOT NULL,
    temperature NUMERIC,
    PRIMARY KEY (location, time_start)
);

CREATE TABLE IF NOT EXISTS forecasts (
    price_area           TEXT        NOT NULL,
    time_start           TIMESTAMPTZ NOT NULL,
    forecast_nok_per_kwh NUMERIC     NOT NULL,
    PRIMARY KEY (price_area, time_start)
);
