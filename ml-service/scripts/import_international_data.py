"""Explicit bounded refresh of original ABS/Statistics Canada retail revenue.

Only committed compact derived snapshots are read by training/inference.
No external parser dependencies, adjusted series, fabricated gaps or expenses.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_SERIES = 500
HISTORY_MONTHS = 240
MONTH = re.compile(r"^([0-9]{4})-(0[1-9]|1[0-2])$")
ABS_URL = "https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025/8501011.xlsx"
CANADA_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/20100056-eng.zip"
ABS_STATES = (
    "New South Wales",
    "Victoria",
    "Queensland",
    "South Australia",
    "Western Australia",
    "Tasmania",
    "Northern Territory",
    "Australian Capital Territory",
)
CANADA_PROVINCES = (
    "Newfoundland and Labrador",
    "Prince Edward Island",
    "Nova Scotia",
    "New Brunswick",
    "Quebec",
    "Ontario",
    "Manitoba",
    "Saskatchewan",
    "Alberta",
    "British Columbia",
    "Yukon",
    "Northwest Territories",
    "Nunavut",
)
ABS_PARENTS = {
    "Food retailing",
    "Household goods retailing",
    "Clothing, footwear and personal accessory retailing",
    "Other retailing",
    "Cafes, restaurants and takeaway food services",
    "Total (Industry)",
}


def month_id(label: str) -> int:
    match = MONTH.fullmatch(label)
    if match is None or int(match[1]) < 1:
        raise ValueError("Invalid provider month")
    return int(match[1]) * 12 + int(match[2]) - 1


def month_label(value: int) -> str:
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def bounded_zip(raw: bytes) -> zipfile.ZipFile:
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Download exceeds 8 MiB bound")
    archive = zipfile.ZipFile(io.BytesIO(raw))
    if (
        len(archive.infolist()) > 100
        or sum(row.file_size for row in archive.infolist()) > MAX_UNCOMPRESSED_BYTES
    ):
        raise ValueError("Archive exceeds declared expansion bound")
    return archive


def partitions(provider: str, geographies: tuple[str, ...]) -> dict:
    groups = sorted(
        [f"{provider}:{geography}" for geography in geographies],
        key=lambda group: hashlib.sha256(
            ("international-region-v1:" + group).encode()
        ).hexdigest(),
    )
    train_end = int(len(groups) * 0.6)
    validation_end = train_end + (len(groups) - train_end) // 2
    return {
        "train": groups[:train_end],
        "validation": groups[train_end:validation_end],
        "test": groups[validation_end:],
    }


def finish_snapshot(
    provider: str,
    rows: list[dict],
    source: dict,
    last_month: str,
    raw: bytes,
    quality: Counter,
) -> dict:
    terminal_end = month_id(last_month)
    for row in rows:
        if len(row["months"]) != len(row["values"]):
            raise ValueError("Unaligned monthly arrays")
        if len(row["months"]) > HISTORY_MONTHS:
            raise ValueError("Derived history exceeds the 240-month bound")
        if any(month_id(value) > terminal_end for value in row["months"]):
            raise ValueError("Unexpected data beyond frozen terminal period")
    if not 1 <= len(rows) <= MAX_SERIES or len(
        {row["identity"] for row in rows}
    ) != len(rows):
        raise ValueError("Invalid provider series count/identities")
    return {
        "format": 1,
        "source": {
            **source,
            "provider": provider,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
            "observations": sum(len(row["months"]) for row in rows),
            "nonnull_published_observations": sum(
                value is not None for row in rows for value in row["values"]
            ),
            "missing_suppressed_or_unreliable_observations": sum(
                value is None for row in rows for value in row["values"]
            ),
            "series": len(rows),
            "last_published_month_used": last_month,
            "transformation": "Original unadjusted monthly nominal sales/turnover, not YTD. Preserve published units, negative observations and null missing/suppressed/unreliable/nonfinite values. Remove national totals and overlapping industry parents; retain at most 240 calendar months. No currency conversion, gap-zero imputation or expense labels.",
        },
        "protocol": {
            "frozen_before_training": True,
            "grouping": "Provider-prefixed state/province; all industry series from one geography stay together. Sector records are dependent aggregate series, not independent firms.",
            "split_algorithm": "SHA256('international-region-v1:' + provider + ':' + geography), sorted; floor(0.6*n) train, half remaining validation/test",
            "geographic_groups": partitions(
                provider, ABS_STATES if provider == "abs" else CANADA_PROVINCES
            ),
            "training_target_end": month_label(terminal_end - 24),
            "validation_target_start": month_label(terminal_end - 23),
            "validation_target_end": month_label(terminal_end - 12),
            "test_target_start": month_label(terminal_end - 11),
            "test_target_end": last_month,
            "forecast_months": 12,
            "training_origin_stride_months": 6,
            "minimum_history_months": 24,
            "maximum_case_history_months": 60,
            "quality_policy": "Reject an entire case if any required history/target month is missing, suppressed, unreliable, nonfinite or negative. Published zero sales remain actual zeros; all-zero history is excluded.",
            "test_policy": "Terminal test labels are imported but must not be read for training or validation selection; build test cases only after final model freeze.",
        },
        "quality_counts": dict(quality),
        "series": rows,
    }


def build_abs_snapshot(raw: bytes) -> dict:
    archive = bounded_zip(raw)
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    properties = workbook.find("s:workbookPr", namespace)
    if properties is not None and properties.attrib.get("date1904") not in (
        None,
        "0",
        "false",
    ):
        raise ValueError("Unexpected Excel date epoch")
    strings = [
        "".join(row.itertext())
        for row in ET.fromstring(archive.read("xl/sharedStrings.xml"))
    ]
    xml = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
    cells = {}
    rows = xml.findall(".//s:row", namespace)
    if len(rows) > 2000:
        raise ValueError("ABS workbook exceeds row bound")
    for row in rows:
        for cell in row:
            value = cell.find("s:v", namespace)
            text = value.text if value is not None else ""
            cells[cell.attrib["r"]] = (
                strings[int(text)] if cell.attrib.get("t") == "s" else text
            )
    selected, quality = [], Counter()
    for column in [key[:-1] for key in cells if re.fullmatch(r"[A-Z]+1", key)]:
        parts = [
            part.strip() for part in cells[column + "1"].split(";") if part.strip()
        ]
        if (
            len(parts) != 3
            or parts[0] != "Turnover"
            or parts[1] not in ABS_STATES
            or parts[2] in ABS_PARENTS
        ):
            continue
        expected = {2: "$ Millions", 3: "Original", 4: "FLOW", 5: "Month"}
        if any(
            cells.get(column + str(row)) != value for row, value in expected.items()
        ):
            raise ValueError("ABS units/frequency/adjustment changed")
        observations = []
        for row in rows:
            number = int(row.attrib["r"])
            serial = cells.get("A" + str(number), "")
            if number < 11 or not serial:
                continue
            timestamp = date(1899, 12, 30) + timedelta(days=float(serial))
            label = f"{timestamp.year:04d}-{timestamp.month:02d}"
            if not month_id("2005-07") <= month_id(label) <= month_id("2025-06"):
                continue
            value = cells.get(column + str(number), "")
            try:
                amount = float(value)
            except (TypeError, ValueError):
                amount = None
                quality["missing_or_suppressed"] += 1
            if amount is not None and not math.isfinite(amount):
                quality["nonfinite"] += 1
                amount = None
            if amount is not None and amount < 0:
                quality["negative_published_value"] += 1
            observations.append((label, amount))
        selected.append(
            {
                "identity": "abs:" + cells[column + "10"],
                "group": "abs:" + parts[1],
                "geography": parts[1],
                "sector": parts[2],
                "months": [item[0] for item in observations],
                "values": [item[1] for item in observations],
            }
        )
    return finish_snapshot(
        "abs",
        selected,
        {
            "publisher": "Australian Bureau of Statistics",
            "title": "Retail Trade, Australia, June 2025; Table 11 original turnover by state and industry subgroup",
            "landing_url": "https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025",
            "download_url": ABS_URL,
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "license_evidence_url": "https://www.abs.gov.au/website-privacy-copyright-and-disclaimer",
            "attribution": "© Commonwealth of Australia, Australian Bureau of Statistics. Adapted from original ABS monthly turnover estimates; no endorsement implied.",
            "units": "million AUD, current prices",
            "source_release_date": "2025-07-31",
            "publication_status": "Ceased: June 2025 is the final Retail Trade release. This is historical data, not a continuing 2026 series.",
            "limitations": "Sample-based geographic/industry aggregates, not individual borrower cash receipts. Shared economic shocks and survey revision vintage create dependence; original values retain seasonality and COVID disruptions.",
        },
        "2025-06",
        raw,
        quality,
    )


def build_canada_snapshot(raw: bytes) -> dict:
    archive = bounded_zip(raw)
    with archive.open("20100056.csv") as file:
        reader = csv.DictReader(io.TextIOWrapper(file, encoding="utf-8-sig"))
        records = list(reader)
    if len(records) > 500000:
        raise ValueError("Canada CSV exceeds row bound")
    field = "North American Industry Classification System (NAICS)"
    categories = {re.search(r"\[([^]]+)\]$", row[field])[1] for row in records}
    # The two published 459A/459B composites partition industry 459. Cannabis
    # 459993 overlaps 459B; exclude that duplicate before choosing leaves.
    categories.discard("459993")
    leaves = {
        code
        for code in categories
        if code != "44-45"
        and not any(other != code and other.startswith(code) for other in categories)
    }
    buckets, quality = {}, Counter()
    for row in records:
        code = re.search(r"\[([^]]+)\]$", row[field])[1]
        if (
            row["GEO"] not in CANADA_PROVINCES
            or code not in leaves
            or row["Sales"] != "Total retail sales"
            or row["Adjustments"] != "Unadjusted"
        ):
            continue
        if row["UOM"] != "Dollars" or row["SCALAR_FACTOR"] != "thousands":
            raise ValueError("Canada published units changed")
        month = month_id(row["REF_DATE"])
        if not month_id("2006-08") <= month <= month_id("2026-07"):
            continue
        identity = "statcan:" + row["GEO"] + ":" + code
        bucket = buckets.setdefault(
            identity,
            {
                "identity": identity,
                "group": "statcan:" + row["GEO"],
                "geography": row["GEO"],
                "sector": row[field],
                "observations": {},
            },
        )
        if row["REF_DATE"] in bucket["observations"]:
            raise ValueError("Duplicate Canada geography/category/month")
        amount = None
        status = row["STATUS"]
        if status in {"x", "..", "F"} or not row["VALUE"]:
            quality[
                "suppressed"
                if status == "x"
                else "unreliable"
                if status == "F"
                else "missing"
            ] += 1
        else:
            try:
                amount = float(row["VALUE"])
            except ValueError as error:
                raise ValueError("Invalid Canada published numeric value") from error
            if not math.isfinite(amount):
                quality["nonfinite"] += 1
                amount = None
            if amount is not None and amount < 0:
                quality["negative_published_value"] += 1
            if status:
                quality["published_quality_" + status] += 1
        bucket["observations"][row["REF_DATE"]] = amount
    selected = []
    for bucket in buckets.values():
        observations = bucket.pop("observations")
        months = sorted(observations)
        selected.append(
            {
                **bucket,
                "months": months,
                "values": [observations[month] for month in months],
            }
        )
    return finish_snapshot(
        "statcan",
        selected,
        {
            "publisher": "Statistics Canada",
            "title": "Table 20-10-0056-01 Monthly retail trade sales by province and territory",
            "landing_url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601",
            "download_url": CANADA_URL,
            "license": "Statistics Canada Open Licence",
            "license_url": "https://www.statcan.gc.ca/en/terms-conditions/open-licence",
            "license_evidence_url": "https://www.statcan.gc.ca/en/terms-conditions/open-licence",
            "attribution": "Statistics Canada. Table 20-10-0056-01, Monthly retail trade sales by province and territory. Adapted for forecasting; no endorsement implied.",
            "units": "thousand CAD, current prices",
            "source_release_date": "2026-09-24",
            "doi": "https://doi.org/10.25318/2010005601-eng",
            "status_policy": "Null x (confidential), .. (unavailable), F (too unreliable) and absent values; retain published numeric quality A–E and record counts. No fabricated zero sales.",
            "hierarchy_policy": "Exclude Canada/CMA totals, seasonally adjusted and e-commerce duplicates. Keep deepest published nonoverlapping NAICS categories; exclude cannabis459993 because it overlaps miscellaneous459B.",
            "limitations": "Provincial industry survey estimates, not independent firms or bank receipts. Current provider vintage may revise old values and published NAICS definitions are backcast; normalized patterns may not transfer to borrower cash flow.",
        },
        "2026-07",
        raw,
        quality,
    )


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Provider download exceeds 8 MiB bound")
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-directory",
        type=Path,
        help="Optional offline raw source directory containing international-abs.xlsx and international-statcan.zip",
    )
    args = parser.parse_args()
    for provider, url, raw_name, build in (
        ("abs", ABS_URL, "international-abs.xlsx", build_abs_snapshot),
        ("statcan", CANADA_URL, "international-statcan.zip", build_canada_snapshot),
    ):
        raw = (
            (args.raw_directory / raw_name).read_bytes()
            if args.raw_directory
            else download(url)
        )
        snapshot = build(raw)
        destination = ROOT / "data" / f"international-{provider}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        temporary.replace(destination)
        print(
            json.dumps(
                {
                    "provider": provider,
                    "series": len(snapshot["series"]),
                    "observations": snapshot["source"]["observations"],
                    "quality": snapshot["quality_counts"],
                    "protocol": snapshot["protocol"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
