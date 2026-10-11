"""Collect and reserve new public revenue sources without forecast inference.

NZ is wholly evaluation-only. A frozen subset of Canadian wholesale geographies
is also evaluation-only; remaining geographies have chronological train/dev/test
targets. Published revised vintages are retrospective evidence, not forecasts
made before the underlying observations became public.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import urllib.request
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from capacity_ml.forecasting import MonthlyHistory
from capacity_ml.public_revenue import PublicCase
from capacity_ml.revenue_data import RevenueSeries, parse_month

ROOT = Path(__file__).resolve().parents[1]
DATA_PATHS = (
    ROOT / "data/fresh-statcan-wholesale.json",
    ROOT / "data/fresh-statsnz.json",
)
MANIFEST_PATH = ROOT / "data/fresh-holdout-reservation.json"
PROTOCOL_VERSION = "fresh-public-revenue-v1"
CANADA_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/20100074-eng.zip"
NZ_URL = "https://www.stats.govt.nz/assets/Uploads/Electronic-card-transactions/Electronic-card-transactions-August-2026/Download-data/electronic-card-transactions-august-2026.zip"
NZ_TITLES = {
    "ECTM.S1GA1": "Consumables",
    "ECTM.S1GA2": "Durables",
    "ECTM.S1GA3": "Hospitality",
    "ECTM.S1GA4": "Services",
    "ECTM.S1GA5": "Apparel",
    "ECTM.S1GA6": "Motor vehicles excl. fuel",
    "ECTM.S1GA7": "Fuel",
    "ECTM.S1GA8": "Non-retail excl. services",
}
WHOLESALE_CODES = (
    "41111",
    "41112",
    "41113",
    "41119",
    "412",
    "4131",
    "4132",
    "4133",
    "4134",
    "4141",
    "4142",
    "4143",
    "4144",
    "41451",
    "41452",
    "4151",
    "4152",
    "4153",
    "4161",
    "4162",
    "4163",
    "4171",
    "4172",
    "4173",
    "4179",
    "4181",
    "4182",
    "4183",
    "4184",
    "4185",
    "4186",
    "4189",
)
WHOLESALE_GEOGRAPHIES = (
    "Alberta",
    "British Columbia",
    "Manitoba",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Northwest Territories",
    "Nova Scotia",
    "Nunavut",
    "Ontario",
    "Prince Edward Island",
    "Quebec",
    "Saskatchewan",
    "Yukon",
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _label(month: int) -> str:
    return f"{int(month) // 12:04d}-{int(month) % 12 + 1:02d}"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen evidence: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _protocol(provider: str, identities: list[str]) -> dict:
    result = {
        "version": PROTOCOL_VERSION,
        "frozen_before_model_errors": True,
        "minimum_history_months": 24,
        "maximum_case_history_months": 60,
        "horizon_months": 12,
        "training_origin_stride_months": 3,
        "annual_audit_target_starts": [
            f"{year}-{8 if provider == 'statcan_wholesale' else 9:02d}"
            for year in range(2017, 2026)
        ],
        "latest_holdout_target_start": "2025-08"
        if provider == "statcan_wholesale"
        else "2025-09",
        "latest_holdout_target_end": "2026-07"
        if provider == "statcan_wholesale"
        else "2026-08",
        "national_industries_are_not_independent_geographies": provider == "statsnz",
        "bootstrap_grouping": "provider plus annual target-start year; all industries in a year stay together",
    }
    if provider == "statsnz":
        result.update(
            audit_only_sectors=sorted(identities),
            fit_sectors=[],
            selection_rule="All eight disjoint published leaf industries; NZ never enters training or development.",
        )
    else:
        ordered = sorted(
            WHOLESALE_GEOGRAPHIES,
            key=lambda geography: hashlib.sha256(
                ("20261011|" + geography).encode()
            ).hexdigest(),
        )
        count = max(3, math.ceil(len(ordered) / 3))
        result.update(
            audit_only_geographies=ordered[:count],
            fit_geographies=ordered[count:],
            audit_only_sectors=sorted(
                identity
                for identity in identities
                if identity.split(":")[1] in ordered[:count]
            ),
            fit_sectors=sorted(
                identity
                for identity in identities
                if identity.split(":")[1] in ordered[count:]
            ),
            training_target_end="2024-07",
            development_target_start="2024-08",
            development_target_end="2025-07",
            selection_rule="All 13 provinces/territories sorted by sha256('20261011|' + geography name); first max(3,ceil(n/3)) geographies wholly audit-only, all others chronological fit/dev/latest holdout. All 32 disjoint deepest published NAICS leaves retained before completeness exclusions.",
        )
    return result


def parse_statsnz(raw: bytes, retrieved_at: str) -> dict:
    """Select exact monthly nominal actual leaf-value rows; never interpolate."""
    archive = zipfile.ZipFile(io.BytesIO(raw))
    filenames = archive.namelist()
    if len(filenames) != 1 or not filenames[0].endswith(".csv"):
        raise ValueError("Unexpected Stats NZ archive schema")
    rows = list(
        csv.DictReader(io.StringIO(archive.read(filenames[0]).decode("utf-8-sig")))
    )
    grouped = {code: {} for code in NZ_TITLES}
    for row in rows:
        code = row["Series_reference"]
        if code not in NZ_TITLES:
            continue
        if (
            row["Group"]
            != "Values - Electronic card transactions A/S/T by industry group"
            or row["Series_title_1"] != "Actual"
            or row["Series_title_2"] != NZ_TITLES[code]
            or row["UNITS"] != "Dollars"
            or row["Magnitude"] != "6"
            or any(row[f"Series_title_{index}"] for index in (3, 4, 5))
            or not re.fullmatch(r"[0-9]{4}\.(0[1-9]|1[0-2])", row["Period"])
        ):
            raise ValueError("Stats NZ monthly nominal leaf definition changed")
        month = row["Period"].replace(".", "-")
        parse_month(month)
        if month in grouped[code]:
            raise ValueError("Duplicate Stats NZ series/calendar coordinate")
        status = row["STATUS"]
        if status not in {"C", "F", "P", "R"}:
            raise ValueError("Unknown Stats NZ quality status")
        value = None
        if row["Data_value"] and not row["Suppressed"] and status in {"F", "P", "R"}:
            value = float(row["Data_value"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid Stats NZ nominal value")
        grouped[code][month] = (value, status)
    series = []
    for code, observations in grouped.items():
        if not observations:
            raise ValueError("Missing fixed Stats NZ leaf industry")
        months = sorted(observations)
        series.append(
            {
                "identity": "statsnz:" + code,
                "sector": NZ_TITLES[code],
                "group": "NZ",
                "months": months,
                "values": [observations[month][0] for month in months],
                "statuses": [observations[month][1] for month in months],
            }
        )
    source = {
        "provider": "statsnz",
        "country": "New Zealand",
        "title": "Electronic card transactions: August 2026; monthly actual values by industry group",
        "url": "https://www.stats.govt.nz/information-releases/electronic-card-transactions-august-2026/",
        "download_url": NZ_URL,
        "license": "CC BY 4.0",
        "license_url": "https://www.stats.govt.nz/about-us/copyright/",
        "attribution": "This work is based on/includes Stats NZ's data which are licensed by Stats NZ for reuse under the Creative Commons Attribution 4.0 International licence.",
        "metadata_url": "https://datainfoplus.stats.govt.nz/item/nz.govt.stats/ba3649c2-07d8-4c34-a10f-659eb22d6d3e",
        "methodology_url": "https://datainfoplus.stats.govt.nz/item/nz.govt.stats/3d0dfc89-6bf5-4677-8cef-3befc36f5b90",
        "units": "million NZD, current prices, GST inclusive, not seasonally adjusted",
        "monetary_unit": "NZD",
        "magnitude": 6,
        "measure": "Nominal monthly merchant electronic-card spending, a partial revenue proxy",
        "retrieved_at_utc": retrieved_at,
        "raw_download_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_member": filenames[0],
        "publication_date": "2026-09-15",
        "calendar_start": "2000-01",
        "first_observed_month": "2002-10",
        "last_observed_month": "2026-08",
        "published_status_policy": "F final, P provisional, R revised accepted when numeric and unsuppressed; C confidential/missing and all blanks remain null, never zero.",
        "taxonomy_policy": "Eight disjoint ANZSIC06 merchant leaf groups. Core retail, retail and total parent aggregates excluded; quarterly and annual rows, counts, percentages, adjusted and trend rows excluded.",
        "limitations": "National administrative card-spend aggregates share economic shocks. Cash, cheques, bank transfers and other non-card sales are outside scope. The June 2025 release revised/backcast classifications using previously unclassified transactions. This current revised vintage is retrospective unseen-provider evidence, not a vintage-correct prospective test, borrower revenue, expenses, repayment or default labels.",
    }
    return {
        "format": 1,
        "source": source,
        "protocol": _protocol("statsnz", [row["identity"] for row in series]),
        "series": series,
    }


def parse_statcan_wholesale(raw: bytes, retrieved_at: str) -> dict:
    """Read licensed unadjusted nominal sales; retain missing/suppressed as null."""
    archive = zipfile.ZipFile(io.BytesIO(raw))
    if set(archive.namelist()) != {"20100074.csv", "20100074_MetaData.csv"}:
        raise ValueError("Unexpected Statistics Canada wholesale archive schema")
    records = list(
        csv.DictReader(io.StringIO(archive.read("20100074.csv").decode("utf-8-sig")))
    )
    field = "North American Industry Classification System (NAICS)"
    names = {row[field] for row in records}
    categories = {
        match[1]: name for name in names if (match := re.search(r"\[([0-9]+)\]$", name))
    }
    leaves = {
        code: name
        for code, name in categories.items()
        if not any(other != code and other.startswith(code) for other in categories)
    }
    if set(leaves) != set(WHOLESALE_CODES):
        raise ValueError("Fixed disjoint wholesale leaf taxonomy changed")
    geographies = {row["GEO"] for row in records} - {"Canada"}
    if geographies != set(WHOLESALE_GEOGRAPHIES):
        raise ValueError("Fixed wholesale province/territory geography changed")
    grouped = {
        (geography, code): {}
        for geography in WHOLESALE_GEOGRAPHIES
        for code in WHOLESALE_CODES
    }
    status_counts = Counter()
    for row in records:
        match = re.search(r"\[([0-9]+)\]$", row[field])
        if (
            row["GEO"] not in geographies
            or row["Adjustments"] != "Unadjusted"
            or match is None
            or match[1] not in leaves
        ):
            continue
        if (
            row["UOM"] != "Dollars"
            or row["SCALAR_FACTOR"] != "thousands"
            or row["UOM_ID"] != "81"
            or row["SCALAR_ID"] != "3"
            or row["SYMBOL"]
            or row["TERMINATED"]
        ):
            raise ValueError(
                "Wholesale nominal sales units or publication schema changed"
            )
        month, status = row["REF_DATE"], row["STATUS"]
        parse_month(month)
        if status not in {"", "A", "B", "C", "D", "E", "F", "x", "..", "p", "r"}:
            raise ValueError("Unknown wholesale data quality status")
        observations = grouped[(row["GEO"], match[1])]
        if month in observations:
            raise ValueError("Duplicate wholesale geography/leaf/calendar coordinate")
        status_counts[status or "unflagged"] += 1
        value = None
        if row["VALUE"] and status not in {"x", "..", "F"}:
            value = float(row["VALUE"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid wholesale nominal published sales")
        observations[month] = (value, status)
    months = [
        _label(month)
        for month in range(parse_month("1993-01"), parse_month("2026-07") + 1)
    ]
    series = []
    for (geography, code), observations in sorted(grouped.items()):
        if any(month not in months for month in observations):
            raise ValueError("Wholesale source calendar changed; review reservation")
        series.append(
            {
                "identity": f"statcan_wholesale:{geography}:{code}",
                "sector": leaves[code],
                "group": f"statcan_wholesale:{geography}",
                "months": months,
                "values": [
                    observations.get(month, (None, "not_published"))[0]
                    for month in months
                ],
                "statuses": [
                    observations.get(month, (None, "not_published"))[1]
                    for month in months
                ],
            }
        )
    source = {
        "provider": "statcan_wholesale",
        "country": "Canada",
        "title": "Statistics Canada Table 20-10-0074-01 Wholesale trade, sales; unadjusted province/territory deepest disjoint NAICS leaves",
        "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010007401",
        "download_url": CANADA_URL,
        "license": "Statistics Canada Open Licence",
        "license_url": "https://www.statcan.gc.ca/en/terms-conditions/open-licence",
        "attribution": "Adapted from Statistics Canada, Table 20-10-0074-01 Wholesale trade, sales, July 2026. This does not constitute an endorsement by Statistics Canada of this product.",
        "doi": "https://doi.org/10.25318/2010007401-eng",
        "units": "thousand CAD, current prices, not seasonally adjusted",
        "monetary_unit": "CAD",
        "magnitude": 3,
        "measure": "Nominal monthly wholesale merchant sales",
        "publication_date": "2026-09-15",
        "retrieved_at_utc": retrieved_at,
        "raw_download_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_metadata_sha256": hashlib.sha256(
            archive.read("20100074_MetaData.csv")
        ).hexdigest(),
        "calendar_start": "1993-01",
        "last_observed_month": "2026-07",
        "published_status_counts_before_missing_calendar_fill": dict(status_counts),
        "published_status_policy": "Numeric A excellent/B very good/C good/D acceptable/E use with caution and unflagged/provisional/revised published values accepted, matching existing Canadian retail quality policy. F unreliable, x confidential, .. missing and absent calendar cells remain null, never zero. E is retained with its original flag, never relabelled high quality.",
        "taxonomy_policy": "All 32 numeric deepest published NAICS leaves, no selected ancestor/descendant pair. Exclusion subtotal codes and national Canada total omitted. All 13 nonoverlapping provinces/territories retained before missing-window exclusions. Calendar gaps before a category exists are explicit null; newer leaves may have only recent eligible cases.",
        "limitations": "Canada and Statistics Canada already appear in the previous RETAIL corpus; these WHOLESALE labels and industry taxonomies are new, not a new independent country/provider. National parent aggregates and geographic totals excluded. Provinces share revisions and macroeconomic shocks. Northwest Territories included Nunavut before 1999, so this overlapping pre-1999 Northwest Territories history is made unusable. Monthly unadjusted estimates revised back to 2012 with the May 2017 sample change; current-vintage histories are not historical vintages. Oilseed/grain and petroleum detailed reporting starts 2023. No borrower revenue, expense, repayment or default labels.",
        "source_availability_note": "US Census direct XLSX/bulk downloads returned 403 and the API requires a key. FRED redistribution was excluded because its current terms prohibit software/system/ML development or training. Singapore data researched only as an alternative and not used. No model scores drove this source substitution.",
    }
    for row in series:
        if row["group"] == "statcan_wholesale:Northwest Territories":
            for index, month in enumerate(months):
                if month < "1999-01":
                    row["values"][index] = None
                    row["statuses"][index] = "overlapping_geography_before_1999"
    return {
        "format": 1,
        "source": source,
        "protocol": _protocol("statcan_wholesale", [row["identity"] for row in series]),
        "series": series,
    }


def load_fresh_series() -> tuple[list[RevenueSeries], dict]:
    series, sources, protocols, hashes = [], [], {}, {}
    for path in DATA_PATHS:
        snapshot = json.loads(path.read_text())
        source, protocol = snapshot["source"], snapshot["protocol"]
        provider = source["provider"]
        if (
            snapshot["format"] != 1
            or provider not in {"statcan_wholesale", "statsnz"}
            or not protocol["frozen_before_model_errors"]
            or protocol["version"] != PROTOCOL_VERSION
        ):
            raise ValueError("Unexpected fresh-source format/provider/protocol")
        expected_license = (
            "CC BY 4.0" if provider == "statsnz" else "Statistics Canada Open Licence"
        )
        if source["license"] != expected_license or source["magnitude"] != (
            6 if provider == "statsnz" else 3
        ):
            raise ValueError("Fresh monetary units/license changed")
        identities = [row["identity"] for row in snapshot["series"]]
        if protocol != _protocol(provider, identities):
            raise ValueError("Fresh frozen split/sector assignment changed")
        sources.append(source)
        protocols[provider] = protocol
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for row in snapshot["series"]:
            months = np.asarray([parse_month(month) for month in row["months"]])
            values = row["values"]
            if (
                not row["identity"].startswith(provider + ":")
                or row["group"]
                != (
                    "NZ"
                    if provider == "statsnz"
                    else "statcan_wholesale:" + row["identity"].split(":")[1]
                )
                or len(months) != len(values)
                or len(values) != len(row["statuses"])
                or len(months) < 24
                or np.any(np.diff(months) != 1)
                or any(
                    value is not None
                    and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or value < 0
                    )
                    for value in values
                )
            ):
                raise ValueError("Invalid fresh monthly identity/calendar/value arrays")
            observed = np.asarray(
                [np.nan if value is None else value for value in values]
            )
            if int(months[-1]) != parse_month(protocol["latest_holdout_target_end"]):
                raise ValueError("Fresh snapshot lacks the fixed latest terminal month")
            series.append(
                RevenueSeries(
                    row["identity"],
                    row["sector"],
                    row["group"],
                    months,
                    observed,
                    source,
                )
            )
    if len(series) != len({row.identity for row in series}):
        raise ValueError("Duplicate fresh identities")
    return series, {
        "sources": sources,
        "protocols": protocols,
        "source_snapshots": hashes,
        "series": len(series),
        "currency_policy": "Retain thousand current CAD and million current NZD separately. No currency conversion. Pool only dimensionless error ratios.",
    }


def build_fresh_cases(split: str, dataset=None) -> tuple[list[PublicCase], list[dict]]:
    if split not in {"train", "development", "holdout"}:
        raise ValueError("Specify train, development or holdout explicitly")
    series, metadata = dataset if dataset is not None else load_fresh_series()
    cases, exclusions = [], []
    for row in series:
        provider = row.source["provider"]
        protocol = metadata["protocols"][provider]
        audit_only = row.identity in protocol["audit_only_sectors"]
        if split != "holdout" and audit_only:
            continue
        if split == "train":
            origins = range(
                int(row.months[0]) + 24,
                parse_month(protocol["training_target_end"]) - 10,
                protocol["training_origin_stride_months"],
            )
        elif split == "development":
            origins = [parse_month(protocol["development_target_start"])]
        elif audit_only:
            origins = [
                parse_month(month) for month in protocol["annual_audit_target_starts"]
            ]
        else:
            origins = [parse_month(protocol["latest_holdout_target_start"])]
        mapping = dict(zip(row.months, row.values, strict=True))
        for origin in origins:
            start = max(int(row.months[0]), origin - 60)
            values = np.asarray(
                [mapping.get(month, np.nan) for month in range(start, origin + 12)]
            )
            reason = (
                "insufficient_history"
                if origin - start < 24
                else "missing_suppressed_or_unreliable_month"
                if np.any(~np.isfinite(values))
                else "negative_actual_revenue"
                if np.any(values < 0)
                else "all_zero_history"
                if np.mean(values[:-12][-12:]) <= 0
                else None
            )
            if reason:
                exclusions.append(
                    {
                        "identity": row.identity,
                        "group": row.group,
                        "split": split,
                        "target_start": _label(origin),
                        "reason": reason,
                    }
                )
                continue
            observed = values[:-12]
            cases.append(
                PublicCase(
                    row.identity,
                    row.sector,
                    row.group,
                    MonthlyHistory(
                        np.arange(start, origin),
                        observed,
                        np.full(len(observed), np.nan),
                        origin,
                    ),
                    values[-12:],
                )
            )
    return cases, exclusions


def _coordinates(cases: list[PublicCase]) -> set[tuple[str, int]]:
    return {
        (case.identity, case.history.forecast_start + horizon)
        for case in cases
        for horizon in range(len(case.actual))
    }


def reserve_fresh_holdout(write_manifest: bool = False) -> dict:
    """Validate and hash every final label before any model is fitted/scored."""
    from capacity_ml.evaluate_public import build_cases as public_baseline_cases
    from capacity_ml.external_data import build_external_cases, load_external_series
    from capacity_ml.international_data import (
        build_international_cases,
        load_international_series,
    )
    from capacity_ml.public_data import load_public_data
    from capacity_ml.public_revenue import build_cases
    from capacity_ml.revenue_data import load_revenue_series

    from .unused_temporal import load_reserved_cases

    dataset = load_fresh_series()
    split_cases, exclusions = {}, {}
    for split in ("train", "development", "holdout"):
        split_cases[split], exclusions[split] = build_fresh_cases(split, dataset)
    holdout = split_cases["holdout"]
    targets = _coordinates(holdout)
    histories = {
        (case.identity, int(month))
        for split in ("train", "development")
        for case in split_cases[split]
        for month in case.history.months
    }
    development_targets = _coordinates(
        split_cases["train"] + split_cases["development"]
    )
    if targets & (development_targets | histories):
        raise ValueError(
            "Fresh holdout target coordinate leaked into fitting/development"
        )
    if len(targets) != sum(len(case.actual) for case in holdout):
        raise ValueError("Fresh annual holdout target windows overlap")
    original, _ = build_cases(*load_revenue_series())
    old = sum(original.values(), [])
    for split in ("train", "validation", "test"):
        old += build_international_cases(split, load_international_series())[0]
    for split in ("train", "validation", "audit"):
        old += build_external_cases(split, load_external_series())[0]
    old += load_reserved_cases()[0]
    original_targets = _coordinates(old)
    public, _ = public_baseline_cases(load_public_data())
    for cases in public.values():
        for case in cases:
            original_targets.update(
                ("retail:" + case.code, case.history.forecast_start + horizon)
                for horizon in range(len(case.actual))
            )
    new_identities = {row.identity for row in dataset[0]}
    if new_identities & {case.identity for case in old} or targets & original_targets:
        raise ValueError("Fresh provider taxonomy overlaps prior corpus/evidence")
    identities = sorted(
        [
            case.identity,
            _label(case.history.forecast_start),
            len(case.history.inflow),
            len(case.actual),
        ]
        for case in holdout
    )
    target_values = sorted(
        [case.identity, _label(case.history.forecast_start + horizon), float(value)]
        for case in holdout
        for horizon, value in enumerate(case.actual)
    )
    result = {
        "protocol_version": PROTOCOL_VERSION,
        "reserved_before_model_errors": True,
        "sources": dataset[1]["sources"],
        "protocols": dataset[1]["protocols"],
        "source_snapshots": dataset[1]["source_snapshots"],
        "target_coordinates_sha256": _hash(
            sorted([identity, _label(month)] for identity, month in targets)
        ),
        "target_values_sha256": _hash(target_values),
        "case_identities_sha256": _hash(identities),
        "target_months": len(targets),
        "cases": len(holdout),
        "counts": {
            split: dict(Counter(case.identity.split(":")[0] for case in cases))
            for split, cases in split_cases.items()
        },
        "exclusions": exclusions,
        "original_target_coordinates_checked": len(original_targets),
        "disjoint_from_original_targets": True,
        "disjoint_from_own_train_dev_targets_and_histories": True,
        "limitations": "New provider/sector label reservation in a current revised vintage; historical eras overlap training countries. Annual national panels have macroeconomic dependence. Whole-year bootstrap describes these reserved blocks, not a prospective independent-country confidence interval or borrower accuracy.",
    }
    if MANIFEST_PATH.exists() and json.loads(MANIFEST_PATH.read_text()) != result:
        raise ValueError("Frozen fresh holdout reservation changed")
    if write_manifest and not MANIFEST_PATH.exists():
        _write(MANIFEST_PATH, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", choices=["statcan_wholesale", "statsnz"])
    parser.add_argument("--raw-file", type=Path)
    parser.add_argument("--reserve", action="store_true")
    args = parser.parse_args()
    if args.collect:
        index = 0 if args.collect == "statcan_wholesale" else 1
        url = CANADA_URL if index == 0 else NZ_URL
        raw = (
            args.raw_file.read_bytes()
            if args.raw_file
            else urllib.request.urlopen(url, timeout=60).read()
        )
        collector = parse_statcan_wholesale if index == 0 else parse_statsnz
        _write(DATA_PATHS[index], collector(raw, datetime.now(UTC).isoformat()))
        print(DATA_PATHS[index])
    if args.reserve:
        reservation = reserve_fresh_holdout(write_manifest=True)
        print(
            json.dumps(
                {
                    key: reservation[key]
                    for key in (
                        "counts",
                        "cases",
                        "target_months",
                        "target_coordinates_sha256",
                    )
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
