# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Norwegian electricity-price platform: ingest hourly spot prices (all five zones NO1–NO5) and Oslo weather, store ~4 years of history in PostgreSQL, forecast the first day without published prices with a scikit-learn model, and serve everything (plus LLM Q&A/advice in Norwegian) through a FastAPI app with a vanilla-JS landing page. Deployed on Fly.io against a Neon-managed Postgres.

## Commands

All Python commands assume the venv is active: `source .venv/bin/activate`.

```bash
# Database (local dev only — prod is Neon)
docker compose up -d                       # starts Postgres on :5432 (strom/strom/strompris)

# Ingestion — MUST run from inside ingest/ (see "Working directory" below)
cd ingest && python fetch_prices.py        # today's prices, NO1 only
cd ingest && python fetch_weather.py       # backfills Oslo weather 2022-09-01 → today (archive API; lags a few days)
cd ingest && python fetch_weather.py recent 92   # last N days (max 92) via the forecast API; the nightly job uses 7
cd ingest && python backfill_all.py        # last 30 days, all five zones
cd ingest && python backfill.py NO2 2022-09-01   # one zone from a date to today (default: NO1, last 7 days)
cd ingest && python fetch_household.py     # Elhub household consumption, last 16 days (or: ... 2026-01-01 to backfill)
cd ingest && python profile_check.py NO1 2026-09 1.32   # household profile vs. an invoice's average spot price

# Migrations (from repo ROOT, uses DATABASE_URL)
python db/migrate.py up 001                # and: down 001

# Model — run from the repo ROOT as `python model/<script>.py` (Python puts model/ on the path,
# so the flat imports work, and save_model.py's relative path model/model.joblib resolves correctly)
python model/baseline.py                   # print naive-baseline MAE the model must beat
python model/train.py                      # compare baseline vs with/without weather (eval only, no save)
python model/save_model.py                 # retrain shared (NO1) + NO2 + NO4 as mean/low/high (9 files) + interval_offsets.json
python model/export_data.py                # read-only export of prices + weather to model/data/*.parquet (gitignored)
python model/backtest.py [months]          # monthly walk-forward backtest, all zones, from the exported files

# API (run from repo ROOT — loads model/model.joblib and api/landing.html by relative path)
python -m uvicorn api.main:app --reload    # http://127.0.0.1:8000  (/docs for OpenAPI)

# Dashboard
python -m streamlit run dashboard/app.py   # http://localhost:8501

# Lint and tests (same as CI)
ruff check .
python -m pytest -q
```

CI (`.github/workflows/ci.yml`) runs `ruff check .`, `pytest`, then a Docker build on every push/PR to `main`. Tests live in `tests/` and cover the pure logic (`api/freshness.py`, `api/refresh.py`, `api/forecasting.py`, `api/prompts.py`, `api/costs.py`, `api/holidays.py`, `api/appliances.py`, `api/comparison.py`, `ingest/quality.py`, `ingest/fetch_household.py`); they need no database, model or API key.

## Working directory matters

Scripts in `ingest/` and `model/` use **flat imports** (`from store import save_prices`, `from features import build_features`, `from baseline import ...`) rather than package imports. Ingest scripts are run with `cd ingest` first; model scripts are run from the root as `python model/<script>.py`. `tests/conftest.py` puts `model/` on the path so tests can import them the same way. The API, by contrast, must run from the repo root because `api/main.py` reads `model/model.joblib` and `api/landing.html` via root-relative paths.

## Database

Connection comes from env, with a local fallback baked into every module:
- `DATABASE_URL` — full libpq conn string (used in prod / CI / GitHub Actions, pointing at Neon).
- `DB_HOST` — only consulted by `api/main.py` (set to `db` inside docker-compose); other modules ignore it.
- Fallback when neither is set: `host=localhost port=5432 dbname=strompris user=strom password=strom`.

The three original tables have no migration file and are assumed to exist (they do on Neon). New tables come as numbered migrations in `db/migrations/` (`NNN_name.up.sql` / `.down.sql`, idempotent, one transaction each), run with `db/migrate.py`:
- `household_consumption(price_area, time_start, quantity_kwh, metering_points, elhub_updated)` — PK `(price_area, time_start)`, upserted. Hourly use of all households per price area from Elhub open data (`CONSUMPTION_PER_GROUP_MBA_HOUR`, group `household`). `quantity_kwh / metering_points` = average kWh per home. Migration 001.

Original tables:
- `prices(price_area, time_start, nok_per_kwh, eur_per_kwh, exr)` — PK `(price_area, time_start)`, upserted.
- `weather(location, time_start, temperature)` — PK `(location, time_start)`, upserted; only `location='oslo'` is used.
- `forecasts(price_area, time_start, forecast_nok_per_kwh)` — PK `(price_area, time_start)`, written nightly for accuracy grading.

## Model architecture

`HistGradientBoostingRegressor` predicting `nok_per_kwh`, with 12 features: calendar (`hour`, `dayofweek`, `month`, `is_weekend`), lags (`lag_24h`, `lag_168h`), weather (`temperature`, `temp_24h`) and a summary of the previous Oslo day (`prev_day_mean/min/max/last`, added Oct 2026 after the backtest: NO1 MAE 15.7 vs 17.9 oere, and the bias after sharp evening price drops roughly halved).

**Prediction intervals:** every model comes in three kinds (`api/forecasting.py::KINDS`): the forecast (`mean`) and the 10th and 90th percentile (`low`, `high`, trained with `loss="quantile"`), giving an 80 % interval. Files: `model/model.joblib`, `model/model_low.joblib`, `model/model_high.joblib`, `model/model_NO2.joblib`, `model/model_NO2_low.joblib`, and so on (9 files). `/forecast` returns `low_nok_per_kwh` / `high_nok_per_kwh`, ordered so that low <= forecast <= high (`ordered_interval`). Raw quantile models covered only ~70 % in the backtest, so the band is **calibrated** (split conformal prediction, `model/intervals.py::conformal_offset`): `save_model.py` trains low/high models on data up to 3 months before the newest hour, measures per area how far outside the band real prices fell in those 3 months, and writes the margin to `model/interval_offsets.json`; the API widens (or narrows) the band by it (`calibrated_interval`). The backtest reports raw and calibrated coverage (should be near 80 %), width and pinball loss.

**Per-zone models (since Oct 2026):** NO2 and NO4 have their own models (`model/model_NO2.joblib`, `model/model_NO4.joblib`), trained on their own history; NO1, NO3 and NO5 use the shared NO1-trained `model/model.joblib`. Chosen by the backtest with a rule fixed beforehand (own model only if 5 %+ better over 12 months). `api/forecasting.py::model_path` routes areas to files; `ZONE_MODELS` is defined there and in `model/save_model.py`, which trains all three models in one run.

The list lives in `api/forecasting.py::FEATURES` and `model/save_model.py::FEATURES`. `tests/test_model_artifact.py` checks that the two match (and that both agree on `ZONE_MODELS`), that **every** model file exists and was trained on exactly those names, and that serving computes the same values as training (including across DST). **Changing features or zones means retraining (`python model/save_model.py`) and committing all `model/*.joblib` files and `model/interval_offsets.json` in the same push**, or CI fails. Features are built two ways that must agree:
- **Training** (`model/features.py`): `add_features` (pure, used by training and the backtest) joins prices and weather on `time_start`, adds calendar fields in `Europe/Oslo`, and looks lags up **by timestamp** (t - 24h, t - 168h), so gaps in the data can't shift them. It also adds `prev_day_mean/min/max/last` (summary of the previous Oslo day, NaN if that day has fewer than 23 hours).
- **Serving** (`api/main.py::_compute_forecast` + `api/forecasting.py`): reconstructs the same 12 features per future hour in Python, pulling recent prices/temps from the DB and future temps live from Open-Meteo. The forecast window starts after the newest stored price and runs to the end of the next Oslo day (`forecast_hours`), so it never covers hours whose real price is already published: before ~13:00 that is tomorrow, after publication the day after tomorrow.

The shared model is trained on NO1 and serves NO1, NO3 and NO5; NO2 and NO4 use their own models (see above). The train/test split cutoff lives in `model/baseline.py` (`CUTOFF`).

## Nightly pipeline

`.github/workflows/fetch-prices.yml` (cron 12:30, 14:45 and 20:17 UTC, or manual `workflow_dispatch`) runs the whole update as inline `python -c` scripts against Neon: fetch today+tomorrow prices for all five zones, refresh the last few days of weather, then **save forecasts by HTTP-calling the live `https://strompris-pipeline.fly.dev/forecast` endpoint** (not by importing the model). The `/accuracy` endpoint later joins those stored `forecasts` against actual `prices`. Then `ingest/quality.py` fails the run if stored prices are missing or invalid (the 12:30 run checks only today), or if Oslo weather doesn't cover all of yesterday. Weather comes from Open-Meteo's forecast API with `past_days=7`; the archive API rejects recent end dates with 400, which silently stopped weather updates from 24 July 2026 until this was fixed. The last step, `ingest/fetch_household.py`, re-fetches 16 days of Elhub household consumption, since Elhub corrects values for about two weeks.

GitHub runs scheduled workflows best effort (often hours late, sometimes skipped), so the API also self-heals: `api/refresh.py` checks at most every 10 minutes, on requests to `/prices`, `/forecast` and `/summary`, whether today's (or after 13:00, tomorrow's) prices are missing, and fetches them from hvakosterstrommen.no in a background thread. `/health` only observes and never triggers a fetch, so it still reveals pipeline problems.

## Deployment

Push to `main` → `.github/workflows/fly-deploy.yml` runs `flyctl deploy --remote-only`. The `Dockerfile` ships **only** `api/` + `model/*.joblib` + `model/interval_offsets.json` and the installed deps — ingestion and training code are intentionally not in the image. The one exception is the small self-healing fetch in `api/refresh.py`, which duplicates the URL and upsert from `ingest/` on purpose to keep that boundary. The model files are force-tracked in git via `.gitignore` negations (`!model/model.joblib`, `!model/model_*.joblib`) despite the global `*.joblib` ignore; commit freshly trained models to ship them.

## Household cost (`/cost`)

Stored prices are spot prices excl. VAT. `api/costs.py` turns them into what a household actually pays per kWh: spot + supplier markup + VAT (none in NO4) minus stroemstoette (90 % above 77 oere excl. VAT, plus VAT) plus nettleie energiledd, and the same with Norgespris (40 oere excl. VAT, no stroemstoette). Nettleie defaults to Elvia's 2026 standard tariff (day weekdays 06-22, night/weekend/holidays otherwise; `api/holidays.py`), overridable with `nettleie_day`/`nettleie_night`. `/cost/now` adds the real price this hour and, per appliance in `api/appliances.py` (typical consumption estimates), the cost now vs. the cheapest start until the last published hour, for spot and Norgespris separately. The landing page's first card renders it. `/compare` (with `/compare/months`) spreads a user's monthly kWh over that month's hours using the Elhub household profile and returns spot with hourly stroemstoette vs. Norgespris (`api/comparison.py`, 5,000 kWh monthly cap); it takes the supplier markup in oere incl. VAT, as invoices show it, and only accepts months where every hour has both price and household data. The second card renders it. Fixed monthly costs are deliberately left out. **All rates are for 2026 and must be updated every January**, together with their tests.

## LLM endpoints

`/summary` and `/ask` call Anthropic (`claude-haiku-4-5-20251001`) and require `ANTHROPIC_API_KEY` in `.env`. All prompts and responses are in Norwegian and intentionally use ASCII spellings (`oe`/`aa`) in the source strings. Key numbers (cheapest/most expensive hour, real-bill savings) are computed in `api/prompts.py::price_facts` and given to the model as a FAKTA block; never let the model derive min/max or percentages from raw prices (it got them wrong). The page renders LLM output with `renderLlmText`, which HTML-escapes everything and only allows `**bold**`. `/ask` limits questions to 300 characters.

## Conventions

- Lint rules and intentional ignores are in `ruff.toml` (e.g. `DTZ011` because the app only ever runs in one timezone, `B008` for FastAPI `Query()` defaults).
- Timestamps are stored and compared in UTC; convert to `Europe/Oslo` only for display and calendar features.
- Never use `date.today()` (UTC on Fly) or pass plain dates to SQL (compared against UTC midnight). Use `oslo_today()` and `oslo_midnight()` from `api/forecasting.py`.
