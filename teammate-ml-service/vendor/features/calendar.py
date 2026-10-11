"""Календарные утилиты: индекс месяца и публичный календарь Рамадана.

Даты начала Рамадана — общедоступный календарь (для Узбекистана возможен сдвиг ±1 день,
на месячную агрегацию это не влияет). Это не данные клиента и не ground truth генератора.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import lru_cache

RAMADAN_START = {
    2018: date(2018, 5, 16), 2019: date(2019, 5, 6), 2020: date(2020, 4, 24),
    2021: date(2021, 4, 13), 2022: date(2022, 4, 2), 2023: date(2023, 3, 23),
    2024: date(2024, 3, 11), 2025: date(2025, 3, 1), 2026: date(2026, 2, 18),
    2027: date(2027, 2, 8), 2028: date(2028, 1, 28), 2029: date(2029, 1, 16),
}
RAMADAN_DAYS = 30


def month_idx(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def idx_to_ym(idx: int) -> tuple[int, int]:
    return idx // 12, idx % 12 + 1


def idx_to_str(idx: int) -> str:
    y, m = idx_to_ym(int(idx))
    return f"{y:04d}-{m:02d}"


def str_to_idx(s: str) -> int:
    y, m = s.split("-")[:2]
    return month_idx(int(y), int(m))


def days_in(idx: int) -> int:
    y, m = idx_to_ym(idx)
    return calendar.monthrange(y, m)[1]


@lru_cache(maxsize=4096)
def ramadan_fraction(idx: int) -> float:
    """Доля дней месяца, приходящихся на Рамадан."""
    y, m = idx_to_ym(int(idx))
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    total = 0
    for yr in (y - 1, y):
        start = RAMADAN_START.get(yr)
        if start is None:
            continue
        end = start + timedelta(days=RAMADAN_DAYS - 1)
        lo, hi = max(first, start), min(last, end)
        if lo <= hi:
            total += (hi - lo).days + 1
    return total / ((last - first).days + 1)


@lru_cache(maxsize=4096)
def eid_in_month(idx: int) -> float:
    """1.0, если Ураза-байрам (первый день после Рамадана) попадает в месяц."""
    y, m = idx_to_ym(int(idx))
    for yr in (y - 1, y):
        start = RAMADAN_START.get(yr)
        if start is None:
            continue
        eid = start + timedelta(days=RAMADAN_DAYS)
        if eid.year == y and eid.month == m:
            return 1.0
    return 0.0


MONTH_NAMES_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
                  "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTH_NAMES_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul",
                  "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def month_name(idx: int, lang: str = "ru") -> str:
    y, m = idx_to_ym(idx)
    names = MONTH_NAMES_UZ if lang == "uz" else MONTH_NAMES_RU
    return f"{names[m - 1]} {y}"
