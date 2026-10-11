"""Схема и валидатор transactions.csv / business.csv.

Принцип: ни одна строка не исправляется молча. Ошибки возвращаются списком
«строка — колонка — причина». Номер строки — номер строки в файле (заголовок = 1).
Проверки векторизованы, чтобы файл на 1 млн строк проверялся за секунды.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from config import (
    CATEGORIES, CHANNELS, LOCAL_UTC_OFFSET_HOURS, MAX_ROWS, MAX_UPLOAD_BYTES,
)

REQUIRED_COLUMNS = ["business_id", "txn_id", "timestamp", "amount", "direction", "channel"]
OPTIONAL_COLUMNS = ["counterparty_id", "category", "currency"]
BUSINESS_REQUIRED = ["business_id"]
BUSINESS_OPTIONAL = ["industry_oked", "registration_date", "region", "existing_monthly_debt"]

_AMOUNT_RE = r"^\d+(\.\d+)?$"
_TS_RE = (r"^\d{4}-\d{2}-\d{2}"
          r"([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?"
          r"(Z|[+-]\d{2}:?\d{2})?$")
_TZ_RE = r"(?:Z|[+-]\d{2}:?\d{2})$"

SCHEMA_DOC = {
    "transactions.csv": {
        "required": True,
        "columns": [
            {"name": "business_id", "type": "string", "required": True,
             "rule": "Внутренний ID или хэш ИНН. В одном файле может быть несколько бизнесов."},
            {"name": "txn_id", "type": "string", "required": True, "rule": "Уникален в файле."},
            {"name": "timestamp", "type": "ISO 8601", "required": True,
             "rule": "Без пояса считаем Asia/Tashkent (UTC+5). Допускается только дата."},
            {"name": "amount", "type": "number > 0", "required": True,
             "rule": "В сумах, разделитель — точка, без пробелов и знака."},
            {"name": "direction", "type": "enum", "required": True, "values": ["in", "out"]},
            {"name": "channel", "type": "enum", "required": True, "values": list(CHANNELS)},
            {"name": "counterparty_id", "type": "string", "required": False,
             "rule": "Хэш контрагента: концентрация клиентов и регулярность."},
            {"name": "category", "type": "enum", "required": False, "values": list(CATEGORIES)},
            {"name": "currency", "type": "ISO 4217", "required": False,
             "rule": "По умолчанию UZS. Другие валюты в MVP отклоняются."},
        ],
        "limits": {"max_bytes": MAX_UPLOAD_BYTES, "max_rows": MAX_ROWS, "encoding": "UTF-8",
                   "delimiter": ","},
    },
    "business.csv": {
        "required": False,
        "columns": [
            {"name": "business_id", "type": "string", "required": True},
            {"name": "industry_oked", "type": "string", "required": False,
             "rule": "Отраслевой приор сезонности для короткой истории."},
            {"name": "registration_date", "type": "date", "required": False},
            {"name": "region", "type": "string", "required": False,
             "rule": "Только для разрезов метрик, в скоринг не входит."},
            {"name": "existing_monthly_debt", "type": "number", "required": False,
             "rule": "Платежи по кредитам, НЕ видимым в транзакциях (другие банки)."},
        ],
    },
    "history_modes": {
        "<6": "отказ с причиной",
        "6-11": "оценка без сезонности, низкий confidence, адаптивный график недоступен",
        "12-23": "сезонность с пониженной уверенностью",
        ">=24": "полный режим",
    },
}


@dataclass
class Issue:
    line: int | None
    column: str | None
    reason: str
    value: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    n_errors_total: int = 0
    n_rows: int = 0
    df: pd.DataFrame | None = None
    has_category: bool = False
    has_counterparty: bool = False

    def errors_dict(self) -> list[dict]:
        return [e.to_dict() for e in self.errors]

    def warnings_dict(self) -> list[dict]:
        return [w.to_dict() for w in self.warnings]


class _Collector:
    def __init__(self, max_errors: int):
        self.max_errors = max_errors
        self.errors: list[Issue] = []
        self.total = 0

    def add_mask(self, df: pd.DataFrame, mask: np.ndarray, column: str, reason: str):
        idx = np.flatnonzero(mask)
        self.total += len(idx)
        room = self.max_errors - len(self.errors)
        for i in idx[: max(room, 0)]:
            val = df[column].iat[i] if column in df.columns else None
            self.errors.append(Issue(int(i) + 2, column, reason, None if val is None else str(val)[:80]))

    def add(self, issue: Issue):
        self.total += 1
        if len(self.errors) < self.max_errors:
            self.errors.append(issue)


class CsvStructureError(ValueError):
    """Файл не разбирается как CSV: неверное число полей в строках."""

    def __init__(self, issues: list[Issue], total: int):
        super().__init__(f"{total} строк с неверным числом полей")
        self.issues, self.total = issues, total


def read_csv_bytes(content: bytes, max_errors: int = 500) -> pd.DataFrame:
    """Читает CSV строго как строки — типы проверяет валидатор, а не pandas."""
    text = content.decode("utf-8-sig")
    try:
        return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=",")
    except pd.errors.ParserError:
        issues, total = [], 0
        reader = csv.reader(io.StringIO(text))
        header = next(reader, [])
        for row in reader:
            if len(row) != len(header):
                total += 1
                if len(issues) < max_errors:
                    issues.append(Issue(reader.line_num, None,
                                        f"ожидалось {len(header)} полей, найдено {len(row)} "
                                        f"(возможно, незакавыченная запятая в числе)"))
        raise CsvStructureError(issues, total)


def _parse_timestamps(ts: pd.Series) -> tuple[pd.Series, np.ndarray]:
    """Возвращает локальное (UTC+5) наивное время и маску ошибок разбора."""
    ts = ts.str.strip()
    fmt_ok = ts.str.match(_TS_RE).to_numpy()
    has_tz = ts.str.contains(_TZ_RE, regex=True).to_numpy() & fmt_ok
    out = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    if has_tz.any():
        aware = pd.to_datetime(ts[has_tz].str.replace(" ", "T", n=1), utc=True,
                               format="ISO8601", errors="coerce")
        out[has_tz] = (aware + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)).dt.tz_localize(None)
    naive = fmt_ok & ~has_tz
    if naive.any():
        out[naive] = pd.to_datetime(ts[naive].str.replace(" ", "T", n=1), format="ISO8601",
                                    errors="coerce")
    bad = ~fmt_ok | out.isna().to_numpy()
    return out, bad


def validate_transactions(df: pd.DataFrame, now: datetime | None = None,
                          max_errors: int = 500) -> ValidationResult:
    col = _Collector(max_errors)
    warnings: list[Issue] = []
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    n = len(df)

    if n == 0:
        col.add(Issue(None, None, "файл не содержит строк данных"))
        return ValidationResult(False, col.errors, warnings, col.total, 0)
    if n > MAX_ROWS:
        col.add(Issue(None, None, f"превышен лимит строк: {n} > {MAX_ROWS}"))
        return ValidationResult(False, col.errors, warnings, col.total, n)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    for c in missing:
        col.add(Issue(1, c, "отсутствует обязательная колонка"))
    if missing:
        return ValidationResult(False, col.errors, warnings, col.total, n)

    extra = [c for c in df.columns if c not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS]
    for c in extra:
        warnings.append(Issue(1, c, "лишняя колонка проигнорирована"))

    for c in REQUIRED_COLUMNS + [c for c in OPTIONAL_COLUMNS if c in df.columns]:
        df[c] = df[c].astype(str).str.strip()

    col.add_mask(df, (df["business_id"] == "").to_numpy(), "business_id", "пустое значение")
    col.add_mask(df, (df["txn_id"] == "").to_numpy(), "txn_id", "пустое значение")

    dup = df["txn_id"].duplicated(keep="first") & (df["txn_id"] != "")
    col.add_mask(df, dup.to_numpy(), "txn_id", "дубль txn_id")

    amount_fmt = df["amount"].str.match(_AMOUNT_RE).to_numpy()
    negative = df["amount"].str.match(r"^-\d+(\.\d+)?$").to_numpy()
    col.add_mask(df, negative, "amount",
                 "amount <= 0: знак не ставится, направление задаёт direction")
    col.add_mask(df, ~amount_fmt & ~negative, "amount",
                 "не число в формате 1234.56 (точка, без пробелов и знака)")
    amount = pd.to_numeric(df["amount"].where(amount_fmt), errors="coerce")
    col.add_mask(df, (amount_fmt & (amount.fillna(0).to_numpy() <= 0)), "amount", "amount <= 0")

    ts, ts_bad = _parse_timestamps(df["timestamp"])
    col.add_mask(df, ts_bad, "timestamp", "некорректная дата (ожидается ISO 8601)")
    now = now or datetime.now(timezone.utc)
    now_local = pd.Timestamp(now.astimezone(timezone.utc).replace(tzinfo=None)
                             + timedelta(hours=LOCAL_UTC_OFFSET_HOURS))
    future = (~ts_bad) & (ts > now_local).to_numpy()
    col.add_mask(df, future, "timestamp", "дата в будущем")

    direction = df["direction"].str.lower()
    col.add_mask(df, ~direction.isin(["in", "out"]).to_numpy(), "direction",
                 "допустимо только in / out")
    channel = df["channel"].str.lower()
    col.add_mask(df, ~channel.isin(CHANNELS).to_numpy(), "channel",
                 f"неизвестный канал (допустимо: {', '.join(CHANNELS)})")

    has_category = "category" in df.columns
    if has_category:
        category = df["category"].str.lower()
        bad_cat = (category != "") & ~category.isin(CATEGORIES)
        col.add_mask(df, bad_cat.to_numpy(), "category",
                     f"неизвестная категория (допустимо: {', '.join(CATEGORIES)})")
    else:
        category = pd.Series("", index=df.index)
        warnings.append(Issue(None, "category", "колонка отсутствует: фиксированные расходы и "
                                                "текущий долг не выделяются"))

    if "currency" in df.columns:
        cur = df["currency"].str.upper().replace("", "UZS")
        col.add_mask(df, (cur != "UZS").to_numpy(), "currency",
                     "в MVP поддерживается только UZS")

    has_cp = "counterparty_id" in df.columns
    if not has_cp:
        warnings.append(Issue(None, "counterparty_id", "колонка отсутствует: концентрация "
                                                       "клиентов не рассчитывается"))
    cp = df["counterparty_id"] if has_cp else pd.Series("", index=df.index)

    if col.total:
        return ValidationResult(False, col.errors, warnings, col.total, n,
                                has_category=has_category, has_counterparty=has_cp)

    clean = pd.DataFrame({
        "business_id": df["business_id"].to_numpy(),
        "txn_id": df["txn_id"].to_numpy(),
        "ts": ts.to_numpy(),
        "amount": amount.to_numpy(dtype=float),
        "direction": direction.to_numpy(),
        "channel": channel.to_numpy(),
        "counterparty_id": cp.to_numpy(),
        "category": category.to_numpy(),
    })
    return ValidationResult(True, [], warnings, 0, n, clean, has_category, has_cp)


def validate_business(df: pd.DataFrame, max_errors: int = 200) -> ValidationResult:
    col = _Collector(max_errors)
    warnings: list[Issue] = []
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    if "business_id" not in df.columns:
        col.add(Issue(1, "business_id", "отсутствует обязательная колонка"))
        return ValidationResult(False, col.errors, warnings, col.total, len(df))
    for c in df.columns:
        if c not in BUSINESS_REQUIRED + BUSINESS_OPTIONAL:
            warnings.append(Issue(1, c, "лишняя колонка проигнорирована"))
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    col.add_mask(df, (df["business_id"] == "").to_numpy(), "business_id", "пустое значение")
    col.add_mask(df, df["business_id"].duplicated().to_numpy(), "business_id", "дубль business_id")
    if "existing_monthly_debt" in df.columns:
        v = df["existing_monthly_debt"]
        bad = (v != "") & ~v.str.match(_AMOUNT_RE)
        col.add_mask(df, bad.to_numpy(), "existing_monthly_debt", "не число >= 0")
    if "registration_date" in df.columns:
        v = df["registration_date"]
        parsed = pd.to_datetime(v.where(v != ""), format="%Y-%m-%d", errors="coerce")
        bad = (v != "") & parsed.isna()
        col.add_mask(df, bad.to_numpy(), "registration_date", "ожидается дата YYYY-MM-DD")
    if col.total:
        return ValidationResult(False, col.errors, warnings, col.total, len(df))
    out = pd.DataFrame({"business_id": df["business_id"]})
    out["industry_oked"] = df["industry_oked"] if "industry_oked" in df.columns else ""
    out["registration_date"] = df["registration_date"] if "registration_date" in df.columns else ""
    out["region"] = df["region"] if "region" in df.columns else ""
    if "existing_monthly_debt" in df.columns:
        out["existing_monthly_debt"] = pd.to_numeric(df["existing_monthly_debt"].replace("", np.nan))
    else:
        out["existing_monthly_debt"] = np.nan
    return ValidationResult(True, [], warnings, 0, len(df), out.set_index("business_id"))
