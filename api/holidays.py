"""Norwegian public holidays (helligdager).

Elvia charges the night/weekend grid rate on these days. Five holidays have fixed
dates; seven move with Easter. No external dependency needed.
"""

from datetime import date, timedelta
from functools import cache


def easter_sunday(year: int) -> date:
    """Easter Sunday in the Gregorian calendar (the "Anonymous Gregorian" / Meeus algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


@cache
def norwegian_holidays(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    moving = [-3, -2, 0, 1, 39, 49, 50]  # skjaertorsdag, langfredag, 1./2. paaskedag, Kristi himmelfart, 1./2. pinsedag
    fixed = [date(year, 1, 1), date(year, 5, 1), date(year, 5, 17), date(year, 12, 25), date(year, 12, 26)]
    return frozenset(fixed + [easter + timedelta(days=d) for d in moving])


def is_holiday(day: date) -> bool:
    return day in norwegian_holidays(day.year)
