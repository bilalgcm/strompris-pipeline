from datetime import UTC, datetime

from ingest.fetch_weather import only_past

# Shape of an Open-Meteo forecast response with past_days (times are UTC, no offset)
SAMPLE = {"hourly": {
    "time": ["2026-10-08T20:00", "2026-10-08T21:00", "2026-10-08T22:00", "2026-10-08T23:00"],
    "temperature_2m": [7.1, 6.8, 6.5, None],
}}


def test_only_past_drops_hours_that_have_not_started():
    times, temps = only_past(SAMPLE, datetime(2026, 10, 8, 21, 30, tzinfo=UTC))
    assert times == ["2026-10-08T20:00", "2026-10-08T21:00"]
    assert temps == [7.1, 6.8]


def test_only_past_includes_the_current_hour_start():
    times, _ = only_past(SAMPLE, datetime(2026, 10, 8, 22, 0, tzinfo=UTC))
    assert times[-1] == "2026-10-08T22:00"
