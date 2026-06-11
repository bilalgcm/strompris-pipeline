# ⚡ Strømpris Pipeline

A real-time Norwegian electricity price platform with ML forecasting and LLM-powered insights — from data ingestion to cloud deployment.

**[→ Live API](https://strompris-pipeline.fly.dev/docs)** · **[→ Live Forecast](https://strompris-pipeline.fly.dev/forecast)** · **[→ Live Summary](https://strompris-pipeline.fly.dev/summary)**

## Why I Built This

I finished my second-year as a software engineering student at OsloMet and started this summer project. After building a crypto API data pipeline in my first year, I wanted my next project to go deeper — not just call an API and print results, but own the whole lifecycle: ingestion, storage, modelling, serving, and deploying it for real. I picked Norwegian electricity prices because it's data that actually matters to people here, and because the Norwegian tech market is short on exactly the skills this project forced me to learn: data engineering, cloud deployment, and integrating AI into real systems. Every part of this was built from scratch, not from a tutorial.



![Dashboard](docs/dashboard.png)

## What it does

Ingests hourly Norwegian electricity spot prices across all five price zones (NO1–NO5), stores four years of history in PostgreSQL, forecasts the next 24 hours using a trained ML model, and generates natural-language daily advice via an LLM — all served through a documented REST API and a visual Streamlit dashboard.

## Architecture

```
hvakosterstrommen.no API
        │
        ▼
  Ingestion (Python)
        │
        ▼
  PostgreSQL (33,000+ hours)
        │
   ┌────┴────┐
   ▼         ▼
ML Model   LLM (Claude Haiku)
   │         │
   └────┬────┘
        ▼
  FastAPI (7 endpoints)
        │
        ▼
  Streamlit Dashboard
```

## Tech Stack

**Backend:** Python, FastAPI, PostgreSQL, psycopg

**ML/AI:** scikit-learn (HistGradientBoostingRegressor), Anthropic Claude Haiku, pandas, joblib

**Infrastructure:** Docker, Docker Compose, GitHub Actions CI, Fly.io, Neon (managed Postgres)

**Frontend:** Streamlit, Plotly

## API Endpoints

| Endpoint | Description |
|---|---|
| `/health` | Health check |
| `/prices` | Hourly spot prices (supports date range and zone filtering) |
| `/stats` | Summary statistics over a time period |
| `/prices/by-hour` | Average price per hour of day across all history |
| `/forecast` | Next 24 hours of ML-predicted prices |
| `/summary` | AI-generated daily price advice in Norwegian |
| `/docs` | Interactive API documentation — try every endpoint live |

All endpoints accept `?area=NO1` through `?area=NO5`.

## Run Locally

```bash
git clone https://github.com/bilalgcm/strompris-pipeline.git
cd strompris-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start the database
docker compose up -d

# Fetch prices and train the model
python3 ingest/fetch_prices.py
python3 model/save_model.py

# Start the API (http://127.0.0.1:8000/docs)
python -m uvicorn api.main:app --reload

# Start the dashboard (http://localhost:8501)
python -m streamlit run dashboard/app.py
```

Requires a `.env` file with `ANTHROPIC_API_KEY` for the `/summary` endpoint.

## ML Model

The forecaster predicts the next 24 hours of electricity prices using a gradient-boosted tree trained on ~33,000 hours of historical data (September 2022 – present).

**Features:** hour of day, day of week, month, weekend flag, price 24h ago, price 168h ago (same hour last week).

**Performance:** MAE of 0.183 kr/kWh on a one-year holdout test set, beating the naive "same as yesterday" baseline of 0.191 kr/kWh. The remaining error is driven by factors outside the feature set — weather, grid events, and news — representing the practical floor for this input set.

## Data Source

[hvakosterstrommen.no](https://www.hvakosterstrommen.no/) — a free, open API for Norwegian day-ahead spot prices. All five price zones (NO1–NO5), hourly resolution, history back to September 2022.

## Future Improvements

- **Weather data integration** — temperature is the primary driver of electricity demand; adding it would push past the current MAE floor
- **Multi-zone forecasting** — the current model is trained on NO1 only; zone-specific models for NO2–NO5
- **Scheduled daily ingestion** — automated price fetching via cloud scheduler
- **Full historical backfill for NO2–NO5** — currently 30 days; NO1 has the complete 4-year history
- **Monitoring** — Grafana dashboards for API health, data freshness, and model drift
