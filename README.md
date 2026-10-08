# ⚡ Strømpris Pipeline

A live Norwegian electricity price platform: hourly prices for all five price areas, a backtested ML forecast with calibrated uncertainty, and tools that turn a spot price into what a household actually pays.

**[→ Live site](https://strompris-pipeline.fly.dev/)** · **[→ API docs](https://strompris-pipeline.fly.dev/docs)** · **[→ Forecast JSON](https://strompris-pipeline.fly.dev/forecast)**

![Dashboard](docs/dashboard.png)

## Why I built this

I started this as a summer project after my second year of software engineering at OsloMet. I wanted to own a whole system end to end, from ingestion and storage to modelling, serving and deployment, on data that matters to people in Norway.

The first version worked and got attention, but feedback showed a real gap: "1,24 kr/kWh" means very little to a normal person, because it isn't what they pay. In October 2026 I went back and rebuilt it around that question, and around a stricter standard: every feature is tested, every model change is measured before it ships, and silent failures are made loud.

## What it does

- **Shows what electricity actually costs you.** The spot price is converted to the real household price per kWh: VAT, strømstøtte (calculated hour by hour), Elvia's nettleie with day, night and holiday rates, and the supplier's markup. Spot and Norgespris side by side.
- **Answers "should I wait?"** Cost right now vs. at the cheapest time for a dishwasher, washing machine, dryer, EV charge and a shower, with savings in kroner on the real bill.
- **Answers "would Norgespris have been cheaper for me?"** Enter one month's kWh and markup from your invoice. Your consumption is spread over that month's hours using real household usage data from Elhub, and both options are calculated hour by hour, including the 5,000 kWh monthly cap.
- **Forecasts the first day without published prices**, with an 80 % prediction interval drawn as a band on the chart.
- **Explains it in Norwegian.** A daily summary and a question box powered by Claude Haiku. The key numbers are computed in code and handed to the model, so it can't miscount.

## Results

All numbers come from a monthly walk-forward backtest over 12 months (October 2025 to September 2026) on all five price areas. For each month the model is trained only on data from before that month.

| Price area | "Same as yesterday" | First model | **Current model** |
|---|---|---|---|
| NO1 | 19.2 | 17.9 | **15.7** |
| NO2 | 20.3 | 19.8 | **17.2** |
| NO3 | 19.6 | 18.1 | **16.7** |
| NO4 | 18.6 | 20.8 | **14.6** |
| NO5 | 14.4 | 14.6 | **13.2** |

*Mean absolute error in øre/kWh, lower is better.*

- **The current model beats the naive baseline in every area.** The first model had only ever been measured on NO1. The backtest showed it was actually worse than "same as yesterday" in NO4 and NO5.
- **A measured blind spot, fixed.** After evenings where prices fell sharply, the old model over-forecast the next night by 19 øre on average, because its only recent-price feature was the same hour yesterday. Adding a summary of the previous day cut that bias to 6 øre with the shared model and 3 øre with the per-area models.
- **Per-area models where they earn it.** NO2 and NO4 have their own models; the others share one trained on NO1. The rule was fixed before looking at the results: an own model only if it beats the shared one by 5 % or more.
- **Honest uncertainty.** Raw quantile models promised 80 % but covered only 64 to 78 % of real prices. Calibrated with split conformal prediction on the three months before each forecast, the band covers **78 to 80 %** in every area.

## How it works

```
hvakosterstrommen.no     Open-Meteo        Elhub open data
   (spot prices)       (temperature)    (household consumption)
         │                   │                   │
         └─────────┬─────────┴─────────┬─────────┘
                   ▼                   ▼
        GitHub Actions, 3× daily    Self-healing fetch in the API
        + data-quality checks       (when the scheduled job is late)
                   │                   │
                   └─────────┬─────────┘
                             ▼
                 PostgreSQL on Neon (180,000 price hours)
                             │
         ┌───────────────────┼────────────────────┐
         ▼                   ▼                    ▼
  Forecast models     Cost engine            LLM layer
  (9 files: mean,     (VAT, strømstøtte,     (Claude Haiku,
   low, high × 3)      nettleie, Norgespris)  facts from code)
         └───────────────────┼────────────────────┘
                             ▼
                FastAPI on Fly.io  →  landing page + REST API
```

## Engineering

- **176 automated tests**, run in CI on every push together with linting and a Docker build. Rules like strømstøtte, DST days and holiday rates are tested against hand-calculated numbers.
- **Guard tests for the models.** CI fails if the API's feature list, the training script and the saved model files ever disagree, or if serving computes a feature differently from training. A model change can't reach production half-done.
- **Failures are loud.** A health endpoint reports data freshness per area, and the nightly job fails if prices or weather are missing or implausible. Before these checks, weather updates had silently stopped for 2.5 months, and the scheduled job was regularly hours late. Both were found by measuring, then fixed.
- **Database changes as migrations**, with up and down scripts tested in both directions.
- **Security by default.** LLM output is HTML-escaped before it reaches the page, user questions are length-limited, and error details never leave the server.

## Tech stack

**Backend:** Python, FastAPI, PostgreSQL (Neon), psycopg
**ML:** scikit-learn (HistGradientBoostingRegressor, quantile loss), pandas, split conformal calibration
**AI:** Anthropic Claude Haiku
**Data:** hvakosterstrommen.no, Open-Meteo, Elhub open data
**Infrastructure:** Docker, GitHub Actions (CI, deploy, scheduled ingestion), Fly.io
**Frontend:** Vanilla HTML and JavaScript, Chart.js

## API

| Endpoint | What it returns |
|---|---|
| `/` | The landing page |
| `/health` | Data freshness per price area (`ok` / `stale` / `error`) |
| `/prices` | Hourly spot prices, filter by date range |
| `/stats` | Average, min and max over a period |
| `/prices/by-hour` | Average price per hour of day across all history |
| `/forecast` | Forecast for the first unpublished day, with an 80 % interval |
| `/cost` | Real household price per hour today and tomorrow, spot and Norgespris |
| `/cost/now` | Real price this hour, and appliance costs now vs. at the cheapest time |
| `/compare` | One month of your consumption: spot with strømstøtte vs. Norgespris |
| `/compare/months` | Months available for `/compare` |
| `/summary` | Daily advice in Norwegian |
| `/ask` | Answer to a question about electricity costs |
| `/accuracy` | Stored forecasts compared with actual prices |

All endpoints take `?area=NO1` to `?area=NO5`.

## Run it locally

```bash
git clone https://github.com/bilalgcm/strompris-pipeline.git
cd strompris-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d                       # local Postgres
export DATABASE_URL="host=localhost port=5432 dbname=strompris user=strom password=strom"
python db/migrate.py up 000                # prices, weather, forecasts
python db/migrate.py up 001                # household consumption

cd ingest
for area in NO1 NO2 NO3 NO4 NO5; do python backfill.py $area 2022-09-01; done   # about 10 min per area
python fetch_weather.py                    # Oslo temperatures since 2022
python fetch_household.py 2026-08-01       # Elhub household consumption
cd ..

python model/save_model.py                 # train models and calibration
python -m uvicorn api.main:app --reload    # http://127.0.0.1:8000

ruff check . && python -m pytest -q        # what CI runs
```

`/summary` and `/ask` need `ANTHROPIC_API_KEY` in a `.env` file. To measure the model yourself: `python model/export_data.py` and then `python model/backtest.py`.

## Limitations

- **Nettleie is Elvia's tariff** (Oslo and most of Østlandet). Other grid companies can enter their own rates through the API, but the page uses Elvia.
- **Tax and support rates are for 2026** and need updating every January.
- **Weather is from Oslo** for every price area.
- **Models are retrained manually.** They don't learn from new data until `save_model.py` is run.
- **The Norgespris comparison uses a typical household's hourly pattern**, not your own. Uploading your own Elhub file is planned.
