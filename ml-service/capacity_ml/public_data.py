"""Offline public aggregate data and pre-2023 retail seasonality calibration.

Source: Uzbekistan National Statistics Committee, SIAT indicator1.07.02.0002,
CC BY4.0. These are regional year-to-date retail turnover totals, not borrower
transactions, expenses, or repayment outcomes. No network calls at inference.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_PATH = DATA_DIRECTORY / "uzbekistan-retail.json"
CALIBRATION_PATH = DATA_DIRECTORY / "retail-calibration.json"


def load_public_data() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def retail_seasonal_factors() -> np.ndarray:
    calibration = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    if calibration["training_years"] != [2020, 2021, 2022]:
        raise ValueError("Calibration must not use real validation/test years")
    factors = np.asarray(calibration["monthly_factors"], dtype=float)
    if (
        factors.shape != (12,)
        or not np.all(np.isfinite(factors))
        or np.any(factors <= 0)
    ):
        raise ValueError("Invalid public retail seasonality calibration")
    factors.setflags(write=False)
    return factors


def calibration_digest() -> str:
    """Versions the exact source snapshot and derived calibration used offline."""
    digest = hashlib.sha256()
    for path in (SNAPSHOT_PATH, CALIBRATION_PATH):
        digest.update(path.read_bytes())
    return digest.hexdigest()
