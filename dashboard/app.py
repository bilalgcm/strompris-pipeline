import os
from datetime import date

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Strompris", page_icon="⚡", layout="wide")
st.title("⚡ Strompris Dashboard")
st.caption("Sanntids strompriser, ML-prognose og AI-oppsummering for Oslo (NO1)")

# --- LLM Summary ---
try:
    summary = requests.get(f"{API}/summary").json()
    st.success(summary["summary"])
except Exception:
    st.warning("Kunne ikke hente oppsummering.")

# --- Today + Forecast chart ---
st.subheader("Dagens priser og prognose neste 24 timer")

try:
    prices = requests.get(
        f"{API}/prices",
        params={"from": date.today().isoformat(), "to": date.today().isoformat()},
    ).json()
    forecast = requests.get(f"{API}/forecast").json()

    df_prices = pd.DataFrame(prices)
    df_prices["time"] = pd.to_datetime(df_prices["time_start"]).dt.tz_convert("Europe/Oslo")
    df_prices["kr/kWh"] = df_prices["nok_per_kwh"]
    df_prices["type"] = "Faktisk"

    df_fc = pd.DataFrame(forecast)
    df_fc["time"] = pd.to_datetime(df_fc["time_start"]).dt.tz_convert("Europe/Oslo")
    df_fc["kr/kWh"] = df_fc["forecast_nok_per_kwh"]
    df_fc["type"] = "Prognose"

    combined = pd.concat([
        df_prices[["time", "kr/kWh", "type"]],
        df_fc[["time", "kr/kWh", "type"]],
    ])

    fig = px.line(
        combined, x="time", y="kr/kWh", color="type",
        color_discrete_map={"Faktisk": "#1D9E75", "Prognose": "#D85A30"},
        labels={"time": "Tid", "kr/kWh": "kr/kWh", "type": ""},
    )
    fig.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

    # Stats
    col1, col2, col3 = st.columns(3)
    today_vals = df_prices["kr/kWh"]
    col1.metric("Snitt i dag", f"{today_vals.mean():.2f} kr/kWh")
    col2.metric("Lavest i dag", f"{today_vals.min():.2f} kr/kWh")
    col3.metric("Hoyest i dag", f"{today_vals.max():.2f} kr/kWh")

except Exception as e:
    st.error(f"Kunne ikke hente prisdata: {e}")

# --- Historical daily curve ---
st.subheader("Gjennomsnittlig dagskurve (alle aar)")

try:
    by_hour = requests.get(f"{API}/prices/by-hour").json()
    df_hour = pd.DataFrame(by_hour)
    fig2 = px.area(
        df_hour, x="hour", y="avg_nok_per_kwh",
        labels={"hour": "Time paa dognet", "avg_nok_per_kwh": "kr/kWh (snitt)"},
        color_discrete_sequence=["#1D9E75"],
    )
    fig2.update_layout(xaxis=dict(dtick=2))
    st.plotly_chart(fig2, use_container_width=True)
except Exception as e:
    st.error(f"Kunne ikke hente dagskurve: {e}")

st.caption("Data: hvakosterstrommen.no | Prognose: Gradient Boosting | Oppsummering: Claude Haiku")
