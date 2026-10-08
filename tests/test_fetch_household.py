from datetime import date, datetime

from ingest.fetch_household import date_chunks, parse_household

# Shape copied from a real response (8 Oct 2026), trimmed to a few values
SAMPLE = {
    "data": [
        {"type": "price-areas", "id": "*", "attributes": {"name": "*", "consumptionPerGroupMbaHour": []}},
        {"type": "price-areas", "id": "NO1", "attributes": {"name": "NO1", "consumptionPerGroupMbaHour": [
            {"startTime": "2026-08-01T00:00:00+02:00", "endTime": "2026-08-01T01:00:00+02:00",
             "priceArea": "NO1", "consumptionGroup": "cabin", "quantityKwh": 66864.54,
             "lastUpdatedTime": "2026-08-15T18:46:23+02:00", "meteringPointCount": 111177},
            {"startTime": "2026-08-01T00:00:00+02:00", "endTime": "2026-08-01T01:00:00+02:00",
             "priceArea": "NO1", "consumptionGroup": "household", "quantityKwh": 1000513.44,
             "lastUpdatedTime": "2026-08-15T18:46:23+02:00", "meteringPointCount": 1124163},
            {"startTime": "2026-08-01T00:00:00+02:00", "endTime": "2026-08-01T01:00:00+02:00",
             "priceArea": "NO1", "consumptionGroup": "tertiary", "quantityKwh": 314626.8,
             "lastUpdatedTime": "2026-08-15T18:46:23+02:00", "meteringPointCount": 28055},
        ]}},
        {"type": "price-areas", "id": "NO5", "attributes": {"name": "NO5", "consumptionPerGroupMbaHour": [
            {"startTime": "2026-08-01T00:00:00+02:00", "endTime": "2026-08-01T01:00:00+02:00",
             "priceArea": "NO5", "consumptionGroup": "household", "quantityKwh": 500000,
             "lastUpdatedTime": "2026-08-15T18:46:23+02:00", "meteringPointCount": 400000},
        ]}},
    ]
}


def test_parse_keeps_only_households():
    rows = parse_household(SAMPLE)
    assert [r[0] for r in rows] == ["NO1", "NO5"]


def test_parse_values_and_timestamps():
    area, start, kwh, meters, updated = parse_household(SAMPLE)[0]
    assert area == "NO1"
    assert start == datetime.fromisoformat("2026-07-31T22:00:00+00:00")  # 00:00 Oslo summer time
    assert kwh == 1000513.44
    assert meters == 1124163
    assert updated.isoformat() == "2026-08-15T18:46:23+02:00"


def test_parse_handles_empty_and_missing_data():
    assert parse_household({}) == []
    assert parse_household({"data": [{"attributes": {}}]}) == []


def test_date_chunks():
    assert date_chunks(date(2026, 8, 1), date(2026, 8, 16)) == [
        (date(2026, 8, 1), date(2026, 8, 8)),
        (date(2026, 8, 8), date(2026, 8, 15)),
        (date(2026, 8, 15), date(2026, 8, 16)),
    ]
    assert date_chunks(date(2026, 8, 1), date(2026, 8, 1)) == []
