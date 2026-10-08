from datetime import date

import pytest

from api.holidays import easter_sunday, is_holiday, norwegian_holidays


@pytest.mark.parametrize("year, expected", [
    (2000, date(2000, 4, 23)),
    (2019, date(2019, 4, 21)),
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
    (2038, date(2038, 4, 25)),  # latest possible Easter date
    (2285, date(2285, 3, 22)),  # earliest possible Easter date
])
def test_easter_sunday(year, expected):
    assert easter_sunday(year) == expected


def test_all_2026_holidays():
    assert norwegian_holidays(2026) == {
        date(2026, 1, 1),    # nyttaarsdag
        date(2026, 4, 2),    # skjaertorsdag
        date(2026, 4, 3),    # langfredag
        date(2026, 4, 5),    # 1. paaskedag
        date(2026, 4, 6),    # 2. paaskedag
        date(2026, 5, 1),    # arbeidernes dag
        date(2026, 5, 14),   # Kristi himmelfartsdag
        date(2026, 5, 17),   # grunnlovsdag
        date(2026, 5, 24),   # 1. pinsedag
        date(2026, 5, 25),   # 2. pinsedag
        date(2026, 12, 25),  # 1. juledag
        date(2026, 12, 26),  # 2. juledag
    }


def test_christmas_eve_is_not_a_public_holiday():
    assert not is_holiday(date(2026, 12, 24))


def test_ordinary_weekday_is_not_a_holiday():
    assert not is_holiday(date(2026, 10, 8))
