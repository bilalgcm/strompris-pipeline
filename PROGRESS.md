# Strømpris Pipeline: project status

Last updated: 9 October 2026

## Where it stands

Live at [strompris-pipeline.fly.dev](https://strompris-pipeline.fly.dev/). Prices for all five areas since September 2022, updated several times a day. 176 automated tests run in CI on every push, followed by a Docker build and an automatic deploy to Fly.io.

## Timeline

### Summer 2026: first version
- Ingestion from hvakosterstrommen.no and Open-Meteo into PostgreSQL
- Gradient-boosted forecast trained on NO1, MAE 18.1 øre on a single holdout year
- FastAPI with nine endpoints, Claude Haiku summary and Q&A, landing page
- Docker, GitHub Actions CI, deployed on Fly.io with Neon Postgres

### October 2026: rebuild for reliability and real usefulness

**Production hardening**
- Faster cold starts (Fly `suspend`), per-area caching of the forecast and the AI summary
- `/health` reports data freshness per area; the nightly job fails loudly on missing or invalid data
- Scheduled job runs three times a day, and the API fetches missing prices itself when GitHub runs late
- Found and fixed: weather updates had silently stopped on 24 July 2026 (the archive API rejected recent dates)
- Found and fixed: "today" was computed in UTC in several places, and plain dates in SQL were compared against UTC midnight

**What it actually costs**
- Cost engine: VAT, hourly strømstøtte, Elvia nettleie (day, night, weekends, holidays), supplier markup, Norgespris
- "What does it cost right now" card with appliance examples and savings on the real bill
- "Spot or Norgespris?" comparison from one month's invoice numbers, using Elhub's hourly household consumption (new table, migration 001). Checked against a real invoice: within 1.2 %.
- AI summary gets its numbers computed in code, so it can't invent minimums or inflate savings; its output is HTML-escaped

**Model quality**
- Monthly walk-forward backtest over 12 months, all five areas (`model/backtest.py`)
- Forecast only covers hours without published prices
- Previous-day features: NO1 MAE 17.9 → 15.7 øre; over-forecast after evening price drops 19 → 3 to 6 øre
- Own models for NO2 and NO4, chosen by a rule fixed before looking at the results
- 80 % prediction intervals from quantile models, calibrated with split conformal prediction: 78 to 80 % coverage in every area
- Guard tests keep the feature list, the training script and the saved models in sync

## Next

1. **Retrain on a schedule.** Models and the interval calibration only update when `save_model.py` is run by hand.
2. **Elhub file upload** for the Norgespris comparison, so people can use their own hourly consumption instead of a typical profile. Waiting for a real sample file to build the parser against.
3. **MCP server** exposing prices, real costs and the forecast to AI agents.
4. **Markup input on the "nå" card**, and more grid companies than Elvia.
5. **Recheck the household profile against a winter invoice.** September was a weak test because prices and usage weren't strongly correlated that month.

## Known limitations

- Tax, strømstøtte and Norgespris rates are for 2026 and must be updated every January, together with their tests.
- Weather comes from Oslo for every price area.
- Nettleie on the page is Elvia's tariff.
- The Norgespris comparison uses a typical household's hourly pattern, not the user's own.
