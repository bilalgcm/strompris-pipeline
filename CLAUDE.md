# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Norwegian electricity-price platform: ingest hourly spot prices (all five zones NO1–NO5) and Oslo weather, store ~4 years of history in PostgreSQL, forecast the next 24h with a scikit-learn model, and serve everything (plus LLM Q&A/advice in Norwegian) through a FastAPI app with a vanilla-JS landing page. Deployed on Fly.io against a Neon-managed Postgres.

## Commands

All Python commands assume the venv is active: `source .venv/bin/activate`.

```bash
# Database (local dev only — prod is Neon)
docker compose up -d                       # starts Postgres on :5432 (strom/strom/strompris)

# Ingestion — MUST run from inside ingest/ (see "Working directory" below)
cd ingest && python fetch_prices.py        # today's prices, NO1 only
cd ingest && python fetch_weather.py       # backfills Oslo weather 2022-09-01 → today
cd ingest && python backfill_all.py        # last 30 days, all five zones
cd ingest && python backfill.py            # single-zone historical backfill

# Model — MUST run from inside model/
cd model && python baseline.py             # print naive-baseline MAE the model must beat
cd model && python train.py                # compare baseline vs with/without weather (eval only, no save)
cd model && python save_model.py           # retrain on all data + write model/model.joblib

# API (run from repo ROOT — loads model/model.joblib and api/landing.html by relative path)
python -m uvicorn api.main:app --reload    # http://127.0.0.1:8000  (/docs for OpenAPI)

# Dashboard
python -m streamlit run dashboard/app.py   # http://localhost:8501

# Lint (same as CI)
ruff check .
```

There is no test suite. CI (`.github/workflows/ci.yml`) runs `ruff check .` then a Docker build on every push/PR to `main`.

## Working directory matters

Scripts in `ingest/` and `model/` use **flat imports** (`from store import save_prices`, `from features import build_features`, `from baseline import ...`) rather than package imports. They only resolve when the current directory is that folder — always `cd ingest` / `cd model` first. The API, by contrast, must run from the repo root because `api/main.py` reads `model/model.joblib` and `api/landing.html` via root-relative paths.

## Database

Connection comes from env, with a local fallback baked into every module:
- `DATABASE_URL` — full libpq conn string (used in prod / CI / GitHub Actions, pointing at Neon).
- `DB_HOST` — only consulted by `api/main.py` (set to `db` inside docker-compose); other modules ignore it.
- Fallback when neither is set: `host=localhost port=5432 dbname=strompris user=strom password=strom`.

**There is no schema/migration file.** Three tables are assumed to already exist and must be created by hand (or they exist on Neon):
- `prices(price_area, time_start, nok_per_kwh, eur_per_kwh, exr)` — PK `(price_area, time_start)`, upserted.
- `weather(location, time_start, temperature)` — PK `(location, time_start)`, upserted; only `location='oslo'` is used.
- `forecasts(price_area, time_start, forecast_nok_per_kwh)` — PK `(price_area, time_start)`, written nightly for accuracy grading.

## Model architecture

`HistGradientBoostingRegressor` predicting `nok_per_kwh`. The feature list

```
["hour", "dayofweek", "month", "is_weekend", "lag_24h", "lag_168h", "temperature", "temp_24h"]
```

is **duplicated** in `model/save_model.py`, `model/train.py`, and `api/main.py` — keep all three in sync when changing features. Features are built two different ways that must agree:
- **Training** (`model/features.py`): a SQL join of `prices` + `weather` on `time_start`, then pandas lag/calendar columns, converting UTC → `Europe/Oslo` for calendar fields.
- **Serving** (`api/main.py::forecast`): reconstructs the same 8 features per future hour in Python, pulling recent prices/temps from the DB and future temps live from Open-Meteo.

The model is **trained on NO1 only** but served for every zone via `?area=NO1..NO5`. The train/test split cutoff lives in `model/baseline.py` (`CUTOFF`).

## Nightly pipeline

`.github/workflows/fetch-prices.yml` (cron 20:00 UTC / ~22:00 Oslo, or manual `workflow_dispatch`) runs the whole update as inline `python -c` scripts against Neon: fetch today+tomorrow prices for all five zones, refresh the last few days of weather, then **save forecasts by HTTP-calling the live `https://strompris-pipeline.fly.dev/forecast` endpoint** (not by importing the model). The `/accuracy` endpoint later joins those stored `forecasts` against actual `prices`.

## Deployment

Push to `main` → `.github/workflows/fly-deploy.yml` runs `flyctl deploy --remote-only`. The `Dockerfile` ships **only** `api/` + `model/model.joblib` and the installed deps — ingestion and training code are intentionally not in the image (ingestion runs from GitHub Actions, not the deployed container). `model/model.joblib` is force-tracked in git via a `.gitignore` negation (`!model/model.joblib`) despite the global `*.joblib` ignore; commit a freshly trained model to ship it.

## LLM endpoints

`/summary` and `/ask` call Anthropic (`claude-haiku-4-5-20251001`) and require `ANTHROPIC_API_KEY` in `.env`. All prompts and responses are in Norwegian and intentionally use ASCII spellings (`oe`/`aa`) in the source strings.

## Conventions

- Lint rules and intentional ignores are in `ruff.toml` (e.g. `DTZ011` because the app only ever runs in one timezone, `B008` for FastAPI `Query()` defaults).
- Timestamps are stored and compared in UTC; convert to `Europe/Oslo` only for display and calendar features.
