"""Fresh-source parsing, reservation and split isolation; no model inference."""

import copy
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter

import numpy as np
import pytest

from benchmarks import fresh_data as fresh
from capacity_ml.revenue_data import RevenueSeries, parse_month


@pytest.fixture(scope="module")
def dataset():
    return fresh.load_fresh_series()


@pytest.fixture(scope="module")
def cases(dataset):
    return {
        split: fresh.build_fresh_cases(split, dataset)
        for split in ("train", "development", "holdout")
    }


def coordinates(rows):
    return {
        (row.identity, row.history.forecast_start + horizon)
        for row in rows
        for horizon in range(len(row.actual))
    }


def test_frozen_cases_and_native_currency_coverage(dataset, cases):
    rows, meta = dataset
    assert len(rows) == 416 + 8
    assert {source["provider"] for source in meta["sources"]} == {
        "statcan_wholesale",
        "statsnz",
    }
    canada = next(
        source
        for source in meta["sources"]
        if source["provider"] == "statcan_wholesale"
    )
    nz = next(source for source in meta["sources"] if source["provider"] == "statsnz")
    assert (canada["monetary_unit"], canada["magnitude"]) == ("CAD", 3)
    assert (nz["monetary_unit"], nz["magnitude"]) == ("NZD", 6)
    assert len(cases["train"][0]) == 3812
    assert len(cases["development"][0]) == 71
    final, excluded = cases["holdout"]
    assert Counter(row.identity.split(":")[0] for row in final) == {
        "statcan_wholesale": 455,
        "statsnz": 72,
    }
    assert len(final) == 527 and len(coordinates(final)) == 6324
    assert len(excluded) == 1241
    for row in final:
        assert 24 <= len(row.history.inflow) <= 60
        assert len(row.actual) == 12
        assert np.all(row.history.months < row.history.forecast_start)
        assert np.isfinite(row.history.inflow).all()
        assert np.isfinite(row.actual).all()
        assert (row.actual >= 0).all()
        # No unobserved expense label is fabricated from public revenue.
        assert np.isnan(row.history.outflow).all()


def test_nz_and_canadian_audit_geographies_never_enter_fitting(dataset, cases):
    protocol = dataset[1]["protocols"]["statcan_wholesale"]
    expected = sorted(
        fresh.WHOLESALE_GEOGRAPHIES,
        key=lambda geography: hashlib.sha256(
            ("20261011|" + geography).encode()
        ).hexdigest(),
    )[:5]
    assert protocol["audit_only_geographies"] == expected
    assert expected == [
        "New Brunswick",
        "Yukon",
        "Alberta",
        "British Columbia",
        "Newfoundland and Labrador",
    ]
    audit_ids = set(protocol["audit_only_sectors"])
    assert len(audit_ids) == 5 * 32
    for split in ("train", "development"):
        for row in cases[split][0]:
            assert row.identity.startswith("statcan_wholesale:")
            assert row.identity not in audit_ids
            assert row.identity.split(":")[1] in protocol["fit_geographies"]
            end = row.history.forecast_start + 11
            if split == "train":
                assert end <= parse_month("2024-07")
            else:
                assert row.history.forecast_start == parse_month("2024-08")
                assert end == parse_month("2025-07")
    nz = [row for row in cases["holdout"][0] if row.identity.startswith("statsnz:")]
    assert Counter(row.history.forecast_start for row in nz) == {
        parse_month(f"{year}-09"): 8 for year in range(2017, 2026)
    }


def test_fresh_holdout_targets_disjoint_from_own_fit_targets_and_history(cases):
    final = coordinates(cases["holdout"][0])
    train_dev = cases["train"][0] + cases["development"][0]
    assert not final & coordinates(train_dev)
    histories = {
        (row.identity, int(month)) for row in train_dev for month in row.history.months
    }
    assert not final & histories
    assert len(final) == sum(len(row.actual) for row in cases["holdout"][0])


def test_frozen_reservation_rebuild_checks_all_old_builders_and_values():
    manifest = json.loads(fresh.MANIFEST_PATH.read_text())
    assert fresh.reserve_fresh_holdout(write_manifest=False) == manifest
    assert manifest["disjoint_from_original_targets"]
    assert manifest["disjoint_from_own_train_dev_targets_and_histories"]
    assert (
        manifest["target_coordinates_sha256"]
        == "a3ab52ca75a957486ac6b48706119e534ba19bd503119ae8299e3bdb15b4e1e9"
    )
    assert (
        manifest["target_values_sha256"]
        == "97cda0ee2b0fb939f5b1bf22a082846080c56b121ddf353d8bebcdd4178879e9"
    )


@pytest.mark.parametrize(
    "field", ["target_values_sha256", "case_identities_sha256", "source_snapshots"]
)
def test_mutated_frozen_reservation_fails_closed(monkeypatch, tmp_path, field):
    manifest = json.loads(fresh.MANIFEST_PATH.read_text())
    manifest[field] = "altered"
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(manifest))
    monkeypatch.setattr(fresh, "MANIFEST_PATH", target)
    with pytest.raises(ValueError, match="Frozen fresh holdout reservation changed"):
        fresh.reserve_fresh_holdout(write_manifest=False)


@pytest.mark.parametrize(
    "mutation", ["units", "boolean_value", "missing_calendar", "duplicate_calendar"]
)
def test_bad_snapshot_units_and_calendar_fail_closed(monkeypatch, tmp_path, mutation):
    snapshot = json.loads(fresh.DATA_PATHS[0].read_text())
    if mutation == "units":
        snapshot["source"]["magnitude"] = 6
    elif mutation == "boolean_value":
        snapshot["series"][0]["values"][-1] = True
    elif mutation == "missing_calendar":
        snapshot["series"][0]["months"][-2] = "2026-05"
    else:
        snapshot["series"][0]["months"][-1] = "2026-06"
    target = tmp_path / "invalid.json"
    target.write_text(json.dumps(snapshot))
    monkeypatch.setattr(fresh, "DATA_PATHS", (target, fresh.DATA_PATHS[1]))
    monkeypatch.setattr(fresh, "ROOT", tmp_path)
    with pytest.raises(
        ValueError, match="units/license|monthly identity/calendar/value"
    ):
        fresh.load_fresh_series()


def test_missing_revenue_is_omitted_without_interpolation_or_zero(dataset):
    rows, meta = dataset
    row = next(row for row in rows if row.identity.startswith("statsnz:"))
    altered = copy.copy(row)
    altered.values = row.values.copy()
    altered.values[-1] = np.nan
    result, excluded = fresh.build_fresh_cases("holdout", ([altered], meta))
    assert len(result) == 8
    assert excluded == [
        {
            "identity": row.identity,
            "group": "NZ",
            "split": "holdout",
            "target_start": "2025-09",
            "reason": "missing_suppressed_or_unreliable_month",
        }
    ]
    altered.values[-1] = -1
    _, excluded = fresh.build_fresh_cases("holdout", ([altered], meta))
    assert excluded[0]["reason"] == "negative_actual_revenue"


def nz_archive(mutation=None):
    fields = [
        "Series_reference",
        "Period",
        "Data_value",
        "Suppressed",
        "STATUS",
        "UNITS",
        "Magnitude",
        "Group",
        "Series_title_1",
        "Series_title_2",
        "Series_title_3",
        "Series_title_4",
        "Series_title_5",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fields)
    writer.writeheader()
    for code, title in fresh.NZ_TITLES.items():
        for period, value, status in (("2002.09", "", "C"), ("2002.10", "100", "F")):
            row = {field: "" for field in fields}
            row.update(
                Series_reference=code,
                Period=period,
                Data_value=value,
                STATUS=status,
                UNITS="Dollars",
                Magnitude="6",
                Group="Values - Electronic card transactions A/S/T by industry group",
                Series_title_1="Actual",
                Series_title_2=title,
            )
            if mutation and code == "ECTM.S1GA1" and period == "2002.10":
                row[mutation[0]] = mutation[1]
            writer.writerow(row)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("source.csv", output.getvalue())
    return raw.getvalue()


def test_nz_confidential_missing_value_stays_null():
    snapshot = fresh.parse_statsnz(nz_archive(), "2026-10-11T00:00:00+00:00")
    assert len(snapshot["series"]) == 8
    assert all(row["values"] == [None, 100.0] for row in snapshot["series"])
    assert all(row["statuses"] == ["C", "F"] for row in snapshot["series"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("Magnitude", "0"),
        ("Series_title_1", "Trend"),
        ("STATUS", "unknown"),
        ("Period", "2026.13"),
    ],
)
def test_nz_changed_schema_fails_closed(field, value):
    with pytest.raises(ValueError):
        fresh.parse_statsnz(nz_archive((field, value)), "2026-10-11T00:00:00+00:00")


def test_short_or_zero_history_does_not_create_invented_case(dataset):
    meta = dataset[1]
    origin = parse_month("2025-09")
    row = RevenueSeries(
        "statsnz:ECTM.S1GA1",
        "Consumables",
        "NZ",
        np.arange(origin - 12, origin + 12),
        np.ones(24),
        {"provider": "statsnz"},
    )
    cases, excluded = fresh.build_fresh_cases("holdout", ([row], meta))
    assert not cases and all(
        item["reason"] == "insufficient_history" for item in excluded
    )
