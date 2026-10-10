"""Bounded explicit refresh of additional licensed SIAT revenue aggregates.

No network operation runs during training or inference. Keep provider revisions
visible, use within-year YTD differences, and declare actual unit conversions.
"""

import hashlib
import json
import math
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SOURCES = (
    (964, "wholesale", 1.0, "2020-01"),
    (3409, "market_services", 1000.0, "2024-10"),
    (3227, "accommodation_food", 1000.0, "2024-10"),
)
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SERIES = 500
PERIOD = re.compile(r"^(\d{4})-M(0[1-9]|1[0-2])$")
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "revenue-series.json"


def build_source(raw: bytes, specification: tuple) -> dict:
    identifier, sector, multiplier, usable_from = specification
    payload = json.loads(raw)[0]
    records = payload["data"]
    if not 1 <= len(records) <= MAX_SERIES:
        raise ValueError("Provider series count exceeds declared bound")
    metadata = {
        row["name_en"]: row.get("value_en")
        for row in payload["metadata"]
        if row.get("value_en") is not None
    }
    expected_unit = "million sums" if multiplier == 1 else "in bln. Soums"
    if metadata.get("Unit of measurement") != expected_unit:
        raise ValueError("Provider units changed; review conversion explicitly")
    if usable_from == "2024-10" and "September 2024" not in metadata.get("Note", ""):
        raise ValueError("Provider methodology note changed; review regime policy")
    series, quality_issues, codes = [], [], set()
    for record in records:
        code = str(record["Code"])
        if not re.fullmatch(r"\d{4}|\d{7}", code) or code in codes:
            raise ValueError("Invalid/duplicate official geographic code")
        codes.add(code)
        values = {key: value for key, value in record.items() if PERIOD.fullmatch(key)}
        if not 1 <= len(values) <= 240:
            raise ValueError("Provider history exceeds declared 240-month bound")
        months, totals, increments = [], [], []
        for period, value in sorted(values.items()):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid provider YTD value for {code}/{period}")
            year, month = map(int, PERIOD.fullmatch(period).groups())
            previous = values.get(f"{year}-M{month - 1:02d}") if month > 1 else 0
            increment = (
                (value - previous) * multiplier if previous is not None else None
            )
            label = f"{year:04d}-{month:02d}"
            months.append(label)
            totals.append(round(value * multiplier, 6))
            increments.append(round(increment, 6) if increment is not None else None)
            if increment is None or increment < 0:
                quality_issues.append(
                    {
                        "code": code,
                        "month": label,
                        "reason": "missing_previous_month"
                        if increment is None
                        else "negative_increment",
                        "monthly_million_uzs": increments[-1],
                    }
                )
        series.append(
            {
                "code": code,
                "region": record["Klassifikator_en"],
                "geographic_group": code[:4],
                "level": "district"
                if len(code) == 7
                else "national"
                if code == "1700"
                else "region",
                "months": months,
                "ytd_million_uzs": totals,
                "monthly_million_uzs": increments,
            }
        )
    return {
        "source": {
            "id": identifier,
            "sector": sector,
            "publisher": metadata["Official statistics preparer"],
            "indicator": metadata["Indicator identification number (code)"],
            "title": metadata["Indicator name"],
            "landing_url": f"https://siat.stat.uz/data/{identifier}/?lang=en",
            "download_url": f"https://api.siat.stat.uz/media/uploads/sdmx/sdmx_data_{identifier}.json",
            "license": "CC BY 4.0",
            "license_evidence_url": f"https://siat.stat.uz/data/{identifier}/?lang=en",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "source_modified": metadata["Last modified date"],
            "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
            "units_as_published": metadata["Unit of measurement"],
            "published_to_million_uzs_multiplier": multiplier,
            "standardized_units": "million UZS; 1 billion UZS = 1000 million UZS",
            "interpretation": "Year-to-date turnover/service volume; within-year differences, January reset. These are aggregates, not borrower cash flow or expense records.",
            "provider_note": metadata.get("Note", ""),
            "usable_from": usable_from,
            "methodology_policy": "Service series exclude pre-September-2024 observations and the September transition increment; October differences use two totals under the new survey definition."
            if usable_from == "2024-10"
            else "Use published contiguous observations; retain negative revisions and exclude affected forecasting windows.",
        },
        "series": series,
        "quality_issues": quality_issues,
    }


def main() -> None:
    datasets = []
    for specification in SOURCES:
        identifier = specification[0]
        url = f"https://api.siat.stat.uz/media/uploads/sdmx/sdmx_data_{identifier}.json"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("Provider download exceeds 1 MiB bound")
        datasets.append(build_source(raw, specification))
    snapshot = {"format": 1, "datasets": datasets}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    temporary.replace(OUTPUT)
    print(
        json.dumps(
            {
                "datasets": [
                    {
                        "sector": data["source"]["sector"],
                        "series": len(data["series"]),
                        "observations": sum(
                            len(row["months"]) for row in data["series"]
                        ),
                        "quality_issues": len(data["quality_issues"]),
                    }
                    for data in datasets
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
