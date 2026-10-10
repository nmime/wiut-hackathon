import json

import numpy as np
import pytest

from capacity_ml.public_data import (
    calibration_digest,
    load_public_data,
    retail_seasonal_factors,
)
from scripts.import_public_data import build_snapshot


def provider_payload(snapshot: dict) -> dict:
    return {
        "metadata": [{"name_en": "Last modified date", "value_en": "2026-09-24"}],
        "data": [
            {
                "Code": series["code"],
                "Klassifikator_en": series["region"],
                **{
                    observation["month"].replace("-", "-M"): observation[
                        "value_ytd_million_uzs"
                    ]
                    for observation in series["observations"]
                },
            }
            for series in snapshot["series"]
        ],
    }


def test_public_snapshot_is_attributed_and_preserves_provider_quality_issues():
    snapshot = load_public_data()
    assert snapshot["source"]["license"] == "CC BY 4.0"
    assert snapshot["source"]["indicator"] == "1.07.02.0002"
    assert len(snapshot["series"]) == 15
    assert sum(not row["is_national_total"] for row in snapshot["series"]) == 14
    assert snapshot["quality_issues"] == [
        {
            "region": "Fergana region",
            "month": "2023-11",
            "value_ytd_million_uzs": 21923018.3,
            "monthly_million_uzs": -213822.8,
            "quality_issue": "nonpositive_monthly_increment",
        }
    ]


def test_january_reset_and_yearly_conservation_match_official_ytd_totals():
    snapshot = load_public_data()
    national = next(row for row in snapshot["series"] if row["is_national_total"])
    observations = {row["month"]: row for row in national["observations"]}
    assert (
        observations["2021-01"]["monthly_million_uzs"]
        == observations["2021-01"]["value_ytd_million_uzs"]
    )
    for year in range(2020, 2026):
        annual = [
            observations[f"{year}-{month:02d}"]["monthly_million_uzs"]
            for month in range(1, 13)
        ]
        assert sum(annual) == pytest.approx(
            observations[f"{year}-12"]["value_ytd_million_uzs"]
        )
    assert observations["2026-08"]["value_ytd_million_uzs"] == 370557063.5


def test_future_public_values_cannot_change_pre_2023_calibration():
    payload = provider_payload(load_public_data())
    _, before = build_snapshot(json.dumps([payload]).encode())
    for row in payload["data"]:
        for period in tuple(row):
            if period.startswith(("2023-", "2024-", "2025-", "2026-")):
                row[period] *= 7
    _, after = build_snapshot(json.dumps([payload]).encode())
    assert before["monthly_factors"] == after["monthly_factors"]
    assert before["training_years"] == [2020, 2021, 2022]
    assert before["region_year_count"] == 42
    assert before["future_years_used"] is False
    factors = retail_seasonal_factors()
    assert len(factors) == 12 and np.all(factors > 0)
    assert factors.mean() == pytest.approx(1)
    assert len(calibration_digest()) == 64
