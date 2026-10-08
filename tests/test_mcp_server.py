"""Tests for the MCP server, with the API replaced by a fake so nothing touches the network."""

import asyncio
from datetime import datetime

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import mcp_server.server as srv

OSLO = srv.OSLO


def fake_api(routes: dict):
    """An httpx client whose responses come from `routes` ({path: json or (status, json)})."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes[request.url.path]
        status, payload = body if isinstance(body, tuple) else (200, body)
        return httpx.Response(status, json=payload)
    return httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))


@pytest.fixture
def api(monkeypatch):
    def install(routes):
        monkeypatch.setattr(srv, "client", fake_api(routes))
    return install


def hour(iso, total):
    return {"time_start": iso, "spot": {"total": total}}


def test_unknown_area_is_rejected():
    with pytest.raises(ToolError, match="Unknown price area"):
        srv.get_forecast("NO9")


def test_lowercase_area_is_accepted(api):
    api({"/forecast": []})
    assert srv.get_forecast("no1") == []


def test_forecast_converts_times_to_oslo_and_keeps_the_band(api):
    api({"/forecast": [{"time_start": "2026-10-09T22:00:00+00:00", "forecast_nok_per_kwh": 0.95,
                        "low_nok_per_kwh": 0.8, "high_nok_per_kwh": 1.15}]})
    assert srv.get_forecast("NO1") == [{"time": "2026-10-10 00:00", "forecast": 0.95, "low": 0.8, "high": 1.15}]


def test_api_validation_errors_become_readable(api):
    api({"/compare": (404, {"detail": "Mangler data for 2026-10 i NO1. Velg en annen måned."})})
    with pytest.raises(ToolError, match="Mangler data"):
        srv.compare_spot_norgespris("2026-10", 500)


def test_cheapest_window_by_hand():
    hours = [
        hour("2026-10-09T22:00:00+00:00", 1.0),  # 00:00 Oslo
        hour("2026-10-09T23:00:00+00:00", 0.5),
        hour("2026-10-10T00:00:00+00:00", 0.3),
        hour("2026-10-10T01:00:00+00:00", 2.0),
    ]
    now = datetime(2026, 10, 9, 23, 30, tzinfo=OSLO)  # before all of them
    # 2-hour averages: 0.75, 0.40, 1.15 -> starts 01:00 Oslo
    assert srv.cheapest_window(hours, 2, now) == {"start": "2026-10-10 01:00", "hours": 2, "avg_real_nok_per_kwh": 0.4}


def test_cheapest_window_skips_hours_that_have_ended():
    hours = [hour("2026-10-09T22:00:00+00:00", 0.1), hour("2026-10-09T23:00:00+00:00", 0.5)]
    now = datetime(2026, 10, 10, 1, 30, tzinfo=OSLO)  # the 00:00 hour has ended
    assert srv.cheapest_window(hours, 1, now)["start"] == "2026-10-10 01:00"


def test_cheapest_window_none_when_too_few_hours_left():
    hours = [hour("2026-10-09T22:00:00+00:00", 0.1)]
    assert srv.cheapest_window(hours, 3, datetime(2026, 10, 9, 23, 0, tzinfo=OSLO)) is None


def test_cheapest_hours_rejects_bad_length():
    with pytest.raises(ToolError, match="between 1 and 24"):
        srv.cheapest_hours("NO1", 0)


def test_tools_are_registered_with_descriptions():
    tools = asyncio.run(srv.server.list_tools())
    names = {t.name for t in tools}
    assert names == {"get_prices", "get_real_cost_now", "get_forecast", "cheapest_hours", "compare_spot_norgespris"}
    assert all(t.description for t in tools)


def test_tool_call_through_the_mcp_layer(api):
    api({"/forecast": [{"time_start": "2026-10-09T22:00:00+00:00", "forecast_nok_per_kwh": 0.95}]})
    result = asyncio.run(srv.server.call_tool("get_forecast", {"area": "NO2"}))
    assert "2026-10-10 00:00" in str(result)


def test_errors_reach_the_agent_with_their_message():
    # A plain exception would arrive as just "Error executing tool get_forecast", which an agent
    # can't act on. With ToolError the message survives; the protocol layer sends it as an error result.
    with pytest.raises(ToolError, match="Unknown price area 'NO9'. Use one of"):
        asyncio.run(srv.server.call_tool("get_forecast", {"area": "NO9"}))
