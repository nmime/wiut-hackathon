"""Общие константы и пути сервиса. Никаких сетевых адресов здесь нет: ядро работает офлайн."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ARTIFACTS_DIR = Path(os.getenv("ML_ARTIFACTS_DIR", ROOT / "models" / "artifacts"))
AUDIT_PATH = Path(os.getenv("ML_AUDIT_PATH", ROOT / "audit" / "audit.jsonl"))
DATA_DIR = Path(os.getenv("ML_DATA_DIR", ROOT / "data"))
GROUND_TRUTH_DIR = ROOT / "generator" / "ground_truth"  # читает только eval/
REPORTS_DIR = ROOT / "eval" / "reports"

GENERATOR_VERSION = "gen-1.0.0"
SERVICE_VERSION = "0.1.0"

# Все даты приводятся к Asia/Tashkent (UTC+5, без перехода на летнее время).
LOCAL_UTC_OFFSET_HOURS = 5
TZ_SUFFIX = "+05:00"

CHANNELS = ("card", "qr", "transfer", "cash", "other")
CATEGORIES = (
    "revenue", "supplier", "salary", "rent", "tax", "utilities",
    "loan_repayment", "transfer_own", "other",
)
FIXED_CATEGORIES = ("salary", "rent", "tax", "utilities")
DEBT_CATEGORY = "loan_repayment"
OWN_TRANSFER_CATEGORY = "transfer_own"

# Лимиты входного файла
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ROWS = 1_000_000

# Режимы по глубине истории (полные месяцы)
MIN_HISTORY_MONTHS = 6       # меньше -> отказ
SEASONAL_MIN_MONTHS = 12     # меньше -> без сезонности
FULL_MODE_MONTHS = 24        # от 24 -> полный режим

HORIZON = 12                 # горизонт прогноза, месяцев
MIN_TERM, MAX_TERM = 3, 36   # допустимый срок кредита
DEFAULT_ANNUAL_RATE = 0.24   # если ставка не передана
DEFAULT_TERM = 12

# Целевое покрытие при выборе рабочей точки буфера (доля месяцев, где платёж <= факт. профицита)
TARGET_COVERAGE = 0.90
# Второй уровень («повышенный риск», полоса P20): покрытие ниже, сумма выше. Выбор — за офицером.
TARGET_COVERAGE_RISK = 0.80

ENABLE_LLM = os.getenv("ML_ENABLE_LLM", "0") == "1"  # опционально, не для ядра
