"""MCP server for Strompris Pipeline: lets Claude and other AI agents use the platform as tools.

It is a thin client over the public REST API (https://strompris-pipeline.fly.dev), so all
price, cost and forecast logic stays in the tested API code. Nothing here touches the database.

Run it locally over stdio, e.g. from Claude Desktop or Claude Code (see mcp_server/README.md):
    python mcp_server/server.py

Set STROMPRIS_API_URL to point at a local API instead (http://127.0.0.1:8000).
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API_URL = os.environ.get("STROMPRIS_API_URL", "https://strompris-pipeline.fly.dev").rstrip("/")
OSLO = ZoneInfo("Europe/Oslo")
AREAS = {
    "NO1": "Østlandet (Oslo)",
    "NO2": "Sørlandet (Kristiansand)",
    "NO3": "Midt-Norge (Trondheim)",
    "NO4": "Nord-Norge (Tromsø)",
    "NO5": "Vestlandet (Bergen)",
}

server = MCPServer(
    name="strompris",
    instructions=(
        "Norwegian electricity prices for the five price areas: "
        + ", ".join(f"{k} = {v}" for k, v in AREAS.items())
        + ". Spot prices are in NOK per kWh excluding VAT. 'Real' prices are what a household pays: "
        "VAT, hourly stroemstoette, Elvia nettleie and (if given) the supplier markup. "
        "Times are Oslo time. Forecasts carry an 80 % prediction interval."
    ),
)

# One shared client; tests replace it with one that doesn't touch the network.
client = httpx.Client(base_url=API_URL, timeout=30)


def _get(path: str, **params) -> dict | list:
    """GET from the API and return JSON, with errors an agent can act on.

    Problems are raised as ToolError: MCP passes its message to the agent, while any other
    exception reaches the agent only as a generic "Error executing tool".
    """
    response = client.get(path, params={k: v for k, v in params.items() if v is not None})
    if response.status_code == 422:
        raise ToolError(f"Invalid input: {response.json().get('detail')}")
    if response.status_code == 404:
        raise ToolError(response.json().get("detail", "Not found"))
    response.raise_for_status()
    return response.json()


def _check_area(area: str) -> str:
    area = area.upper()
    if area not in AREAS:
        raise ToolError(f"Unknown price area {area!r}. Use one of: {', '.join(AREAS)}")
    return area


def _oslo(iso: str) -> str:
    """'2026-10-09T22:00:00+00:00' -> '2026-10-10 00:00' in Oslo time, easier for an agent to read out."""
    return datetime.fromisoformat(iso).astimezone(OSLO).strftime("%Y-%m-%d %H:%M")


@server.tool()
def get_prices(area: str = "NO1", date: str | None = None) -> list[dict]:
    """Hourly spot prices (NOK/kWh excl. VAT) for one day. `date` is YYYY-MM-DD in Oslo time, default today.
    Tomorrow's prices are usually published around 13:00."""
    area = _check_area(area)
    prices = _get("/prices", area=area, **{"from": date, "to": date} if date else {})
    if not date:  # /prices defaults to a week; keep today only
        today = datetime.now(OSLO).strftime("%Y-%m-%d")
        prices = [p for p in prices if _oslo(p["time_start"]).startswith(today)]
    return [{"time": _oslo(p["time_start"]), "spot_nok_per_kwh": p["nok_per_kwh"]} for p in prices]


@server.tool()
def get_real_cost_now(area: str = "NO1") -> dict:
    """What a household pays for electricity this hour, on spot and on Norgespris, with the price broken
    into parts, plus what a dishwasher, washing machine, dryer, EV charge and shower cost now vs. at the
    cheapest time ahead."""
    area = _check_area(area)
    data = _get("/cost/now", area=area)
    if "spot" not in data:
        raise ToolError(data.get("message", "No price for this hour yet"))
    for tariff in ("spot", "norgespris"):
        for a in data[tariff]["appliances"]:
            if a.get("best_start"):
                a["best_start"] = _oslo(a["best_start"])
    data["time"] = _oslo(data.pop("time_start"))
    return data


@server.tool()
def get_forecast(area: str = "NO1") -> list[dict]:
    """ML forecast of spot prices (NOK/kWh excl. VAT) for the first day without published prices,
    with an 80 % prediction interval (low/high), calibrated to hold about 80 % of the time."""
    area = _check_area(area)
    return [
        {"time": _oslo(p["time_start"]), "forecast": p["forecast_nok_per_kwh"],
         "low": p.get("low_nok_per_kwh"), "high": p.get("high_nok_per_kwh")}
        for p in _get("/forecast", area=area)
    ]


def cheapest_window(hours: list[dict], length: int, now: datetime) -> dict | None:
    """Cheapest run of `length` consecutive hours that hasn't ended yet, from /cost hours.

    Scored on the real household price on spot. Same rule as api/appliances.py; kept here
    so the MCP server only depends on the public API, not on the API's code.
    """
    future = [h for h in hours if datetime.fromisoformat(h["time_start"]) + timedelta(hours=1) > now]
    best = None
    for i in range(len(future) - length + 1):
        window = future[i:i + length]
        avg = sum(h["spot"]["total"] for h in window) / length
        if best is None or avg < best["avg_real_nok_per_kwh"] - 1e-12:
            best = {"start": _oslo(window[0]["time_start"]), "hours": length,
                    "avg_real_nok_per_kwh": round(avg, 4)}
    return best


@server.tool()
def cheapest_hours(area: str = "NO1", hours: int = 2, markup_nok_per_kwh: float = 0.0) -> dict:
    """Best time to start something that runs `hours` consecutive hours (1-24), within the prices
    published so far, scored on what a household actually pays on spot."""
    area = _check_area(area)
    if not 1 <= hours <= 24:
        raise ToolError("hours must be between 1 and 24")
    data = _get("/cost", area=area, markup=markup_nok_per_kwh)
    best = cheapest_window(data["hours"], hours, datetime.now(OSLO))
    if best is None:
        raise ToolError(f"Not enough published hours left for a {hours}-hour window. Try fewer hours or after 13:00.")
    return best


@server.tool()
def compare_spot_norgespris(month: str, kwh: float, area: str = "NO1", paslag_ore: float = 0.0) -> dict:
    """For one month of consumption (YYYY-MM and total kWh from the invoice), what spot with
    stroemstoette cost vs. what Norgespris would have cost. `paslag_ore` is the supplier markup in
    oere/kWh including VAT, as invoices show it. Uses a typical household's hourly pattern."""
    area = _check_area(area)
    return _get("/compare", area=area, month=month, kwh=kwh, paslag_ore=paslag_ore)


if __name__ == "__main__":
    server.run()  # stdio
