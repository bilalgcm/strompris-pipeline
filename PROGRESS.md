# Strompris Pipeline — Project Status

## What this is
A real-time Norwegian electricity price platform: ingestion, storage, ML forecasting, and LLM-powered insights, served over a documented REST API.

## Stack
Python, FastAPI, PostgreSQL (Docker), scikit-learn (HistGradientBoostingRegressor), Anthropic Claude Haiku, Docker Compose.

## What's built (Phases 0–3)
- Ingestion: fetch + backfill from hvakosterstrommen.no (NO1, Sept 2022–present, ~33k hourly rows)
- Storage: Postgres in Docker with upsert (idempotent), named volume for persistence
- API endpoints: /health, /prices (date range), /stats, /prices/by-hour, /forecast (next 24h ML predictions), /summary (LLM daily insight in Norwegian)
- ML: gradient-boosted tree trained on calendar + lag features, MAE ~0.183 kr/kWh (baseline 0.191), saved with joblib
- LLM: Claude Haiku generates Norwegian-language price summaries from actual + forecasted data

## What's next (Phase 4)
- Dockerfile for the app (currently only DB is containerized)
- GitHub Actions CI
- Cloud deployment (Azure) with Terraform
- Monitoring (Grafana/Prometheus)

## How to run locally
docker compose up -d
python3 ingest/fetch_prices.py        # fetch today
python3 model/save_model.py           # retrain model
python -m uvicorn api.main:app --reload
# needs .env with ANTHROPIC_API_KEY
