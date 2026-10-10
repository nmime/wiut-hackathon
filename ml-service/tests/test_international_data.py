"""Importer/split tests; never construct or evaluate actual terminal test cases."""

import copy
import csv
import io
import json
import zipfile
from datetime import date

import numpy as np
import pytest

from capacity_ml.international_data import (
    DATA_PATHS,
    build_international_cases,
    international_data_digest,
    load_international_series,
)
from capacity_ml.revenue_data import RevenueSeries, parse_month
from scripts.import_international_data import (
    bounded_zip,
    build_abs_snapshot,
    build_canada_snapshot,
    partitions,
)


def archive(files: dict[str, str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as file:
        for name, text in files.items():
            file.writestr(name, text)
    return stream.getvalue()


def test_abs_parser_original_units_dates_and_explicit_missing():
    strings = [
        "Turnover ; New South Wales ; Supermarket and grocery stores ;",
        "$ Millions",
        "Original",
        "FLOW",
        "Month",
        "A-fixture",
    ]
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    headers = [(1, 0), (2, 1), (3, 2), (4, 3), (5, 4), (10, 5)]
    rows = [
        f'<row r="{row}"><c r="B{row}" t="s"><v>{value}</v></c></row>'
        for row, value in headers
    ]
    july = (date(2005, 7, 1) - date(1899, 12, 30)).days
    august = (date(2005, 8, 1) - date(1899, 12, 30)).days
    rows.extend(
        [
            f'<row r="11"><c r="A11"><v>{july}</v></c><c r="B11"><v>12.5</v></c></row>',
            f'<row r="12"><c r="A12"><v>{august}</v></c><c r="B12"/></row>',
        ]
    )
    raw = archive(
        {
            "xl/workbook.xml": f'<workbook xmlns="{namespace}"><workbookPr/></workbook>',
            "xl/sharedStrings.xml": f'<sst xmlns="{namespace}">'
            + "".join(f"<si><t>{text}</t></si>" for text in strings)
            + "</sst>",
            "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{namespace}"><sheetData>'
            + "".join(rows)
            + "</sheetData></worksheet>",
        }
    )
    snapshot = build_abs_snapshot(raw)
    assert snapshot["series"][0]["months"] == ["2005-07", "2005-08"]
    assert snapshot["series"][0]["values"] == [12.5, None]
    assert snapshot["source"]["units"] == "million AUD, current prices"
    assert snapshot["quality_counts"] == {"missing_or_suppressed": 1}
    bad = {
        "xl/workbook.xml": f'<workbook xmlns="{namespace}"><workbookPr date1904="1"/></workbook>',
        "xl/sharedStrings.xml": f'<sst xmlns="{namespace}"/>',
        "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{namespace}"/>',
    }
    with pytest.raises(ValueError, match="date epoch"):
        build_abs_snapshot(archive(bad))


def test_canada_parser_preserves_suppression_and_removes_overlap():
    columns = [
        "REF_DATE",
        "GEO",
        "North American Industry Classification System (NAICS)",
        "Sales",
        "Adjustments",
        "UOM",
        "SCALAR_FACTOR",
        "VALUE",
        "STATUS",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    base = dict(
        zip(
            columns,
            [
                "2023-01",
                "Ontario",
                "Retail trade [44-45]",
                "Total retail sales",
                "Unadjusted",
                "Dollars",
                "thousands",
                "1000",
                "",
            ],
            strict=True,
        )
    )
    for category, month, value, status in (
        ("Miscellaneous retailers [459B]", "2023-01", "200", "A"),
        ("Miscellaneous retailers [459B]", "2023-02", "", "x"),
        ("Miscellaneous retailers [459B]", "2023-03", "0", ""),
        ("Miscellaneous retailers [459B]", "2023-04", "50", "F"),
        ("Miscellaneous retailers [459B]", "2023-05", "-12", ""),
        ("Cannabis retailers [459993]", "2023-01", "80", ""),
        ("Retail trade [44-45]", "2023-01", "1000", ""),
    ):
        writer.writerow(
            {
                **base,
                columns[2]: category,
                "REF_DATE": month,
                "VALUE": value,
                "STATUS": status,
            }
        )
    snapshot = build_canada_snapshot(archive({"20100056.csv": buffer.getvalue()}))
    assert len(snapshot["series"]) == 1
    assert snapshot["series"][0]["sector"] == "Miscellaneous retailers [459B]"
    assert snapshot["series"][0]["values"] == [200, None, 0, None, -12]
    assert snapshot["source"]["units"] == "thousand CAD, current prices"
    assert snapshot["quality_counts"]["suppressed"] == 1
    assert snapshot["quality_counts"]["unreliable"] == 1
    assert snapshot["quality_counts"]["negative_published_value"] == 1


def test_offline_sources_licenses_taxonomy_and_frozen_geography():
    series, metadata = load_international_series()
    assert metadata["series"] == 380 and metadata["observations"] == 58700
    assert (
        metadata["nonnull_published_observations"]
        + metadata["missing_suppressed_or_unreliable_observations"]
        == metadata["observations"]
    )
    assert len(international_data_digest()) == 64
    assert metadata["providers"]["abs"]["license"] == "CC BY 4.0"
    assert (
        metadata["providers"]["statcan"]["license"] == "Statistics Canada Open Licence"
    )
    assert {source["units"] for source in metadata["sources"]} == {
        "million AUD, current prices",
        "thousand CAD, current prices",
    }
    for source in metadata["sources"]:
        assert len(source["raw_sha256"]) == 64
        assert source["download_url"].startswith("https://")
    assert all(row.group.startswith(row.source["provider"] + ":") for row in series)
    assert all(len(row.months) <= 240 for row in series)
    assert not any(
        "[459993]" in row.sector or "Total (Industry)" == row.sector for row in series
    )
    for protocol in metadata["protocols"].values():
        groups = protocol["geographic_groups"]
        assert not set(groups["train"]) & set(groups["validation"])
        assert not set(groups["train"]) & set(groups["test"])
        assert not set(groups["validation"]) & set(groups["test"])
        assert parse_month(protocol["training_target_end"]) < parse_month(
            protocol["validation_target_start"]
        )
        assert parse_month(protocol["validation_target_end"]) < parse_month(
            protocol["test_target_start"]
        )
    # Inspect null representation, not any final held-out revenue statistic.
    snapshots = [json.loads(path.read_text()) for path in DATA_PATHS]
    assert all(
        any(None in row["values"] for row in snapshot["series"])
        for snapshot in snapshots
    )


def test_training_validation_bounds_and_no_terminal_label_dependency():
    series, metadata = load_international_series()
    changed = copy.deepcopy(series)
    for row in changed:
        protocol = metadata["protocols"][row.source["provider"]]
        # Overwrite without inspecting actual terminal labels or building test.
        row.values[row.months >= parse_month(protocol["test_target_start"])] = np.nan
    for split, count in (("train", 2707), ("validation", 59)):
        cases, excluded = build_international_cases(split, (series, metadata))
        repeated, repeated_exclusions = build_international_cases(
            split, (changed, metadata)
        )
        assert len(cases) == count and excluded == repeated_exclusions
        assert len(cases) == len(repeated)
        for case, modified in zip(cases, repeated, strict=True):
            provider = case.identity.split(":")[0]
            protocol = metadata["protocols"][provider]
            assert case.group in protocol["geographic_groups"][split]
            assert len(case.history.inflow) >= 24
            assert case.history.months[-1] < case.history.forecast_start
            boundary = (
                "training_target_end" if split == "train" else "validation_target_end"
            )
            assert case.history.forecast_start + 11 <= parse_month(protocol[boundary])
            np.testing.assert_array_equal(case.actual, modified.actual)


def test_synthetic_split_fixture_missing_month_excludes_only_its_window():
    months = np.arange(parse_month("2018-01"), parse_month("2025-01"))
    row = RevenueSeries(
        "fixture:series",
        "retail",
        "fixture:group",
        months,
        np.ones(len(months)),
        {"provider": "fixture"},
    )
    protocol = {
        "geographic_groups": {"train": [row.group], "validation": [], "test": []},
        "minimum_history_months": 24,
        "maximum_case_history_months": 60,
        "training_origin_stride_months": 6,
        "training_target_end": "2023-12",
    }
    metadata = {"protocols": {"fixture": protocol}}
    before, _ = build_international_cases("train", ([row], metadata))
    row.values[-1] = np.nan  # A later unavailable month cannot erase train history.
    after, _ = build_international_cases("train", ([row], metadata))
    assert len(after) == len(before) and len(after) > 0
    row.values[np.flatnonzero(row.months == parse_month("2020-03"))[0]] = np.nan
    missing, exclusions = build_international_cases("train", ([row], metadata))
    assert len(missing) < len(before) and exclusions
    with pytest.raises(ValueError, match="explicitly"):
        build_international_cases("all", ([row], metadata))


def test_partition_is_value_independent_and_archive_expansion_bounded():
    assert partitions("fixture", ("a", "b", "c", "d", "e")) == partitions(
        "fixture", ("e", "d", "c", "b", "a")
    )
    with pytest.raises(ValueError, match="expansion bound"):
        bounded_zip(archive({"large": "0" * (33 * 1024 * 1024)}))
