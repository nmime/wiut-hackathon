"""Bounded explicit refresh of nominal Eurostat/ONS turnover index snapshots.

Run with the locked development dependencies (httpx provides verified TLS).
Training and inference only read the committed snapshots, never the network.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "data" / "external-protocol.json"
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_TOTAL_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_SERIES = 720
ONS_URL = "https://www.ons.gov.uk/file?uri=%2Fbusinessindustryandtrade%2Fretailindustry%2Fdatasets%2Fretailsales%2Fcurrent%2Fdrsi.csv"
# Whole provider/country audit only. Exclude parents, business-size subdivisions,
# Internet-only overlaps, percentages, rolling averages and volume indices.
ONS_LEAF_CODES = (
    "CY3X",
    "CY45",
    "CY4B",
    "EAGB",
    "EAGE",
    "EAGH",
    "EAPG",
    "EAPH",
    "EAPI",
    "EAPK",
    "EAPM",
    "EAPN",
    "EAPO",
    "EAPQ",
    "J43J",
    "JJ8J",
    "JKO6",
    "JOF2",
    "J43H",
)
MONTH_NAMES = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def month_id(label: str) -> int:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", label) or label[:4] == "0000":
        raise ValueError("Invalid monthly calendar label")
    year, month = map(int, label.split("-"))
    return year * 12 + month - 1


def month_label(value: int) -> str:
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text())


def eurostat_url(country: str) -> str:
    return (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_trtu_m"
        "?lang=EN&freq=M&indic_bt=NETTUR&unit=I21&s_adj=NSA&geo="
        + country
        + "&sinceTimePeriod=2006-09&untilTimePeriod=2026-08"
    )


def download(url: str) -> bytes:
    # Streaming bounds apply even when the server omits Content-Length.
    with httpx.stream("GET", url, timeout=30, follow_redirects=True) as response:
        response.raise_for_status()
        if int(response.headers.get("content-length", "0")) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Provider download exceeds 8 MiB")
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                raise ValueError("Provider download exceeds 8 MiB")
            chunks.append(chunk)
    return b"".join(chunks)


def numeric(value: object, quality: Counter) -> float | None:
    try:
        if isinstance(value, bool) or value in (None, "", ":", "..", "."):
            raise ValueError
        result = float(value)
        if not math.isfinite(result):
            raise ValueError
    except (TypeError, ValueError):
        quality["missing_suppressed_or_nonfinite"] += 1
        return None
    if result < 0:
        quality["negative_published_value_preserved"] += 1
    return result


def eurostat_rows(raw: bytes, country: str, plan: dict) -> tuple[list[dict], Counter]:
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Provider JSON exceeds download bound")
    dataset = json.loads(raw)
    dimensions = dataset["dimension"]
    expected = {
        "freq": "M",
        "indic_bt": "NETTUR",
        "s_adj": "NSA",
        "unit": "I21",
        "geo": country,
    }
    if dataset["id"] != ["freq", "indic_bt", "nace_r2", "s_adj", "unit", "geo", "time"]:
        raise ValueError("Unexpected Eurostat dimension order")
    for dimension, code in expected.items():
        membership = dimensions[dimension]["category"]["index"]
        if membership != {code: 0} and not (
            dimension == "geo" and membership == {} and not dataset.get("value")
        ):
            raise ValueError(
                "Eurostat must contain only monthly nominal unadjusted turnover"
            )
    count = dataset["size"][-1]
    if not 1 <= count <= 240 or dataset["size"][2] > 50:
        raise ValueError("Eurostat calendar/category bounds exceeded")
    categories = dimensions["nace_r2"]["category"]
    times = dimensions["time"]["category"]["index"]
    calendar = [
        month_label(m)
        for m in range(
            month_id(plan["history_start"]), month_id(plan["history_end"]) + 1
        )
    ]
    values, statuses = dataset.get("value", {}), dataset.get("status", {})
    rows, quality = [], Counter()
    for sector in plan["sectors"]:
        offset = categories["index"].get(sector)
        observations, flags = [], {}
        for label in calendar:
            index = (
                str(offset * count + times[label])
                if offset is not None and label in times
                else None
            )
            flag = statuses.get(index, "") if index is not None else ""
            value = values.get(index) if index is not None else None
            if flag:
                flags[label] = flag
                quality["provider_flag:" + flag] += 1
            # Forecast/imputed/low reliability/confidential observations are not
            # actual training labels. Break/definition/estimated/provisional flags
            # are retained explicitly, with per-window break rejection in loader.
            if any(code in flag for code in ("f", "i", "u", "c", "C", "N", "P", "m")):
                value = None
                quality["excluded_provider_status"] += 1
            observations.append(numeric(value, quality))
        rows.append(
            {
                "identity": f"eurostat:{country}:{sector}",
                "group": f"eurostat:{country}",
                "geography": country,
                "sector": sector,
                "label": categories.get("label", {}).get(sector, sector),
                "months": calendar,
                "values": observations,
                "flags": flags,
            }
        )
    return rows, quality


def ons_rows(raw: bytes, plan: dict) -> tuple[list[dict], Counter]:
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("ONS CSV exceeds download bound")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    if not 7 <= len(rows) <= 2000 or len(rows[0]) > 1000 or rows[1][0] != "CDID":
        raise ValueError("Unexpected ONS CSV dimensions/metadata")
    codes = rows[1]
    if plan.get("ons_leaf_cdid", list(ONS_LEAF_CODES)) != list(ONS_LEAF_CODES):
        raise ValueError("ONS taxonomy differs from frozen CDID list")
    calendar = [
        month_label(m)
        for m in range(
            month_id(plan["history_start"]), month_id(plan["history_end"]) + 1
        )
    ]
    monthly = {}
    for row in rows[7:]:
        match = re.fullmatch(r"([0-9]{4}) ([A-Z]{3})", row[0])
        if match and match[2] in MONTH_NAMES:
            label = f"{match[1]}-{MONTH_NAMES.index(match[2]) + 1:02d}"
            if label in monthly:
                raise ValueError("Duplicate ONS monthly observation")
            monthly[label] = row
    result, quality = [], Counter()
    for code in ONS_LEAF_CODES:
        if codes.count(code) != 1:
            raise ValueError("Frozen ONS leaf code unavailable or duplicated")
        column = codes.index(code)
        title = rows[0][column]
        if rows[4][column] != "18-09-2026":
            raise ValueError(
                "ONS release vintage changed; review index reference year explicitly"
            )
        lower = title.lower()
        if not (
            "index" in lower
            and "all business" in lower
            and ("val nsa" in lower or "value not seasonally adjusted" in lower)
        ) or any(word in lower for word in ("volume", "internet", "%", "rolling")):
            raise ValueError(
                "ONS code is not an unadjusted nominal all-business value index"
            )
        observations = [
            numeric(
                monthly.get(label, [])[column]
                if len(monthly.get(label, [])) > column
                else None,
                quality,
            )
            for label in calendar
        ]
        result.append(
            {
                "identity": "ons:" + code,
                "group": "ons:GB",
                "geography": "GB",
                "sector": code,
                "label": title,
                "months": calendar,
                "values": observations,
                "flags": {},
            }
        )
    return result, quality


def snapshot(
    provider: str,
    rows: list[dict],
    source: dict,
    raw_files: list[tuple[str, bytes]],
    quality: Counter,
    plan: dict,
) -> dict:
    if (
        not 1 <= len(rows) <= MAX_SERIES
        or sum(len(raw) for _, raw in raw_files) > MAX_TOTAL_DOWNLOAD_BYTES
    ):
        raise ValueError("External corpus bounds exceeded")
    return {
        "format": 1,
        "source": {
            **source,
            "provider": provider,
            "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
            "raw_files": [
                {
                    "url": url,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                for url, raw in raw_files
            ],
            "raw_sha256": hashlib.sha256(
                b"".join(raw for _, raw in raw_files)
            ).hexdigest(),
            "series": len(rows),
            "observations": sum(len(row["months"]) for row in rows),
            "nonnull_published_observations": sum(
                v is not None for row in rows for v in row["values"]
            ),
            "missing_suppressed_or_unreliable_observations": sum(
                v is None for row in rows for v in row["values"]
            ),
            "last_published_month_used": "2026-08",
            "transformation": "Nominal unadjusted sales/turnover VALUE index only; retain published scale, explicit missing nulls and provider flags. No deflated volume, currency conversion, expense/default labels, gap-zero imputation or overlapping industry parents. Negative actual values retained for per-window quality rejection.",
        },
        "protocol": {
            **plan,
            "audit_only": provider == "ons",
            "quality_policy": "Reject only affected windows with required missing/nonfinite/negative observations or a break/definition-change flag strictly inside the window. Retain other windows from the series. Estimated/provisional actual releases retained; forecast/imputed/low-reliability/confidential values become explicit null.",
        },
        "quality_counts": dict(sorted(quality.items())),
        "series": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-directory",
        type=Path,
        help="Use retained raw files offline; never download",
    )
    args = parser.parse_args()
    plan = protocol()
    raw_directory = args.raw_directory or ROOT / "runtime"
    raw_directory.mkdir(parents=True, exist_ok=True)

    def fetch(country: str) -> tuple[str, bytes]:
        path = raw_directory / f"external-eurostat-{country}.json"
        raw = (
            path.read_bytes() if args.raw_directory else download(eurostat_url(country))
        )
        if len(raw) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Raw file exceeds bounded download size")
        if not args.raw_directory:
            path.write_bytes(raw)
        return country, raw

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(fetch, plan["countries"]))
    euro_rows, euro_quality = [], Counter()
    for country, raw in responses:
        rows, quality = eurostat_rows(raw, country, plan)
        euro_rows.extend(rows)
        euro_quality.update(quality)
    euro_source = {
        "publisher": "European Commission, Eurostat",
        "title": "Turnover and volume of sales in wholesale and retail trade - monthly data (sts_trtu_m), NETTUR only",
        "url": "https://ec.europa.eu/eurostat/databrowser/view/sts_trtu_m/default/table?lang=en",
        "license": "Eurostat reuse policy (Decision 2011/833/EU)",
        "license_url": "https://ec.europa.eu/eurostat/help/copyright-notice",
        "units": "nominal net turnover index, 2021=100 (I21), unadjusted (NSA)",
        "attribution": "Source: Eurostat sts_trtu_m, accessed 2026-10-10. Filtered/reformatted by FlowCredit; Eurostat is not responsible for these adaptations.",
        "definition_url": "https://ec.europa.eu/eurostat/cache/metadata/en/sts_wrt_ts_esms_sk.htm",
        "flags_url": "https://ec.europa.eu/eurostat/data/database",
        "scope": "30 EU/EFTA countries; 22 disjoint NACE trade groups, national survey aggregates, not individual businesses or bank receipts. Eurostat commercial reuse exceptions for non-EU/EFTA/candidate countries avoided.",
        "hierarchy_policy": "G451-454; G461-467+G469; G4711/G4719+G472-479. Exclude all G/G45/G46/G47 and thematic composites; G4791 excluded because G479 already includes it.",
        "limitations": "Current vintage, revised and rebased source; no historical-vintage backtest. Index reflects nominal turnover, not cash receipt timing or expenses. Whole countries/industries share economic shocks. Some categories unavailable; all frozen taxonomy slots remain null rather than inventing zero.",
    }
    euro = snapshot(
        "eurostat",
        euro_rows,
        euro_source,
        [(eurostat_url(country), raw) for country, raw in responses],
        euro_quality,
        plan,
    )
    ons_path = raw_directory / "external-ons.csv"
    ons_raw = ons_path.read_bytes() if args.raw_directory else download(ONS_URL)
    if not args.raw_directory:
        ons_path.write_bytes(ons_raw)
    ons_series, ons_quality = ons_rows(ons_raw, plan)
    ons_source = {
        "publisher": "Office for National Statistics",
        "title": "Retail Sales Index DRSI, Great Britain, nominal unadjusted all-business value indices",
        "url": "https://www.ons.gov.uk/businessindustryandtrade/retailindustry/datasets/retailsales/current",
        "license": "Open Government Licence v3.0",
        "license_url": "https://www.ons.gov.uk/help/terms-conditions",
        "units": "nominal retail sales value index, 2024=100, not seasonally adjusted",
        "attribution": "Contains public sector information licensed under the Open Government Licence v3.0. Source: Office for National Statistics, DRSI, released 18 September 2026. Filtered/reformatted by FlowCredit; no ONS endorsement.",
        "definition_url": "https://www.ons.gov.uk/businessindustryandtrade/retailindustry/bulletins/retailsales/august2026",
        "reference_year_evidence": "September 2026 release updates reference year from 2023 to 2024=100; no change to growth rates.",
        "scope": "19 disjoint retail categories in Great Britain, whole provider/country audit only. Entire ONS dataset excluded from fitting and selection.",
        "hierarchy_policy": "Frozen CDID19 all-business sector leaves only, excluding Internet-only overlaps, large/small subdivisions, parent totals, commodity indices, percentages and rolling growth series.",
        "limitations": "National survey aggregates, not independent stores/borrowers. Current-vintage indices and provisional releases; underlying survey periods follow 4/5-week reporting calendars, not exact Gregorian cash receipts. UK omitted from Eurostat countries. No expense/default labels.",
    }
    ons = snapshot(
        "ons", ons_series, ons_source, [(ONS_URL, ons_raw)], ons_quality, plan
    )
    for provider, result in (("eurostat", euro), ("ons", ons)):
        (ROOT / "data" / f"external-{provider}.json").write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n"
        )
        print(
            json.dumps(
                {
                    provider: {
                        key: result["source"][key]
                        for key in (
                            "series",
                            "observations",
                            "nonnull_published_observations",
                            "missing_suppressed_or_unreliable_observations",
                            "raw_sha256",
                        )
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
