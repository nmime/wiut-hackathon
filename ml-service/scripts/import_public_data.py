"""Explicitly refresh the licensed public aggregate snapshot; never runs in API.

Read the provider's year-to-date values as published. January resets; other
months are within-year differences. Negative revisions remain visible and are
excluded by calibration/evaluation rather than silently repaired.
"""

import hashlib
import json
import math
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

SOURCE_URL = "https://api.siat.stat.uz/media/uploads/sdmx/sdmx_data_2699.json"
LANDING_URL = "https://siat.stat.uz/data/2699/?lang=en"
DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
PERIOD = re.compile(r"^(\d{4})-M(\d{2})$")


def build_snapshot(raw: bytes) -> tuple[dict, dict]:
    payload = json.loads(raw)
    records = payload[0]["data"]
    source_metadata = payload[0]["metadata"]
    modified = next(
        row["value_en"]
        for row in source_metadata
        if row["name_en"] == "Last modified date"
    )
    series, issues = [], []
    profiles = []
    for record in records:
        values = {key: value for key, value in record.items() if PERIOD.fullmatch(key)}
        observations = []
        for period, value in sorted(values.items()):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Non-numeric source observation: {period}")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid year-to-date source value: {period}")
            year, month = map(int, PERIOD.fullmatch(period).groups())
            previous = values.get(f"{year}-M{month - 1:02d}") if month > 1 else 0
            increment = value - previous if previous is not None else None
            observation = {
                "month": f"{year:04d}-{month:02d}",
                "value_ytd_million_uzs": value,
                "monthly_million_uzs": round(increment, 6)
                if increment is not None
                else None,
            }
            if increment is None or increment <= 0:
                observation["quality_issue"] = (
                    "missing_previous_month"
                    if increment is None
                    else "nonpositive_monthly_increment"
                )
                issues.append({"region": record["Klassifikator_en"], **observation})
            observations.append(observation)
        entry = {
            "code": str(record["Code"]),
            "region": record["Klassifikator_en"],
            "is_national_total": record["Klassifikator_en"] == "Republic of Uzbekistan",
            "observations": observations,
        }
        series.append(entry)
        if not entry["is_national_total"]:
            for year in (2020, 2021, 2022):
                annual = [
                    row["monthly_million_uzs"]
                    for row in observations
                    if row["month"].startswith(str(year))
                ]
                if len(annual) == 12 and all(
                    value is not None and value > 0 for value in annual
                ):
                    vector = np.asarray(annual)
                    profiles.append(vector / vector.mean())
    if not profiles:
        raise ValueError("No complete positive regional calibration years")
    profile = np.median(np.asarray(profiles), axis=0)
    profile /= profile.mean()
    snapshot = {
        "source": {
            "publisher": "National Statistics Committee of the Republic of Uzbekistan",
            "indicator": "1.07.02.0002",
            "title": "Retail trade volume (by month)",
            "landing_url": LANDING_URL,
            "download_url": SOURCE_URL,
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_modified": modified,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
            "units_as_published": "million sums (UZS)",
            "interpretation": "Year-to-date turnover; monthly increments difference within each year and reset in January.",
            "ytd_confirmation_url": "https://stat.uz/en/press-center/news-of-committee/70489-chakana-savdo-tovar-ajlanmasi-azhmi-370-trln-s-mdan-oshdi-4",
            "transformations": [
                "English region labels only",
                "Within-year monthly differences",
                "No clipping or imputation",
            ],
        },
        "quality_issues": issues,
        "series": series,
    }
    calibration = {
        "source_raw_sha256": snapshot["source"]["raw_sha256"],
        "training_years": [2020, 2021, 2022],
        "region_year_count": len(profiles),
        "method": "Normalize each complete positive regional year's monthly increments by its annual mean; median by calendar month; normalize median to mean one. National total excluded.",
        "monthly_factors": profile.tolist(),
        "future_years_used": False,
    }
    return snapshot, calibration


def main() -> None:
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Source payload exceeded 1 MiB")
    snapshot, calibration = build_snapshot(raw)
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, value in (
        ("uzbekistan-retail.json", snapshot),
        ("retail-calibration.json", calibration),
    ):
        (DATA_DIRECTORY / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "regions_including_national": len(snapshot["series"]),
                "quality_issues": snapshot["quality_issues"],
                "calibration_region_years": calibration["region_year_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
