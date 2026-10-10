"""New source integrity and development split tests; never build actual audit."""

import copy
import csv
import io
import json

import numpy as np
import pytest

from capacity_ml.external_data import (
    DATA_PATHS,
    build_external_cases,
    external_data_digest,
    load_external_series,
    read_snapshot,
)
from capacity_ml.revenue_data import RevenueSeries, parse_month
from scripts.import_external_data import (
    ONS_LEAF_CODES,
    download,
    eurostat_rows,
    ons_rows,
)


def test_eurostat_nominal_taxonomy_missing_flags_and_real_zero():
    plan = {
        "history_start": "2006-09",
        "history_end": "2006-12",
        "sectors": ["G451", "G452"],
    }
    dimensions = {
        key: {"category": {"index": {code: 0}}}
        for key, code in {
            "freq": "M",
            "indic_bt": "NETTUR",
            "s_adj": "NSA",
            "unit": "I21",
            "geo": "DE",
        }.items()
    }
    dimensions["nace_r2"] = {
        "category": {"index": {"G451": 0}, "label": {"G451": "Motor vehicle sales"}}
    }
    dimensions["time"] = {
        "category": {"index": {"2006-09": 0, "2006-10": 1, "2006-11": 2, "2006-12": 3}}
    }
    dataset = {
        "id": ["freq", "indic_bt", "nace_r2", "s_adj", "unit", "geo", "time"],
        "size": [1, 1, 1, 1, 1, 1, 4],
        "dimension": dimensions,
        "value": {"0": 0, "1": 12.5, "2": 20, "3": -1},
        "status": {"1": "p", "2": "f", "3": "b"},
    }
    rows, quality = eurostat_rows(json.dumps(dataset).encode(), "DE", plan)
    assert rows[0]["values"] == [0, 12.5, None, -1]
    assert rows[0]["flags"] == {"2006-10": "p", "2006-11": "f", "2006-12": "b"}
    assert rows[1]["values"] == [None] * 4
    assert quality["excluded_provider_status"] == 1
    assert quality["negative_published_value_preserved"] == 1
    dataset["dimension"]["indic_bt"]["category"]["index"] = {"VOL_SLS": 0}
    with pytest.raises(ValueError, match="nominal unadjusted turnover"):
        eurostat_rows(json.dumps(dataset).encode(), "DE", plan)


def ons_fixture(title_suffix: str = "") -> bytes:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        ["Title"]
        + [
            "RSI:fixture " + code + " (val nsa):All Business Index" + title_suffix
            for code in ONS_LEAF_CODES
        ]
    )
    writer.writerow(["CDID", *ONS_LEAF_CODES])
    writer.writerow(["PreUnit"] + [""] * len(ONS_LEAF_CODES))
    writer.writerow(["Unit"] + [""] * len(ONS_LEAF_CODES))
    writer.writerow(["Release Date"] + ["18-09-2026"] * len(ONS_LEAF_CODES))
    writer.writerow(["Next release"] + [""] * len(ONS_LEAF_CODES))
    writer.writerow(["Important Notes"] + [""] * len(ONS_LEAF_CODES))
    writer.writerow(["2006 SEP", *([0, ""] + [12.5] * (len(ONS_LEAF_CODES) - 2))])
    writer.writerow(["2006 OCT"] + [-1] * len(ONS_LEAF_CODES))
    return stream.getvalue().encode()


def test_ons_only_value_leaves_original_calendar_and_missing():
    plan = {"history_start": "2006-09", "history_end": "2006-11"}
    rows, _ = ons_rows(ons_fixture(), plan)
    assert len(rows) == 19
    assert rows[0]["values"] == [0, -1, None]
    assert rows[1]["values"] == [None, -1, None]
    assert all(row["group"] == "ons:GB" for row in rows)
    with pytest.raises(ValueError, match="value index"):
        ons_rows(ons_fixture(" volume"), plan)
    with pytest.raises(ValueError, match="vintage changed"):
        ons_rows(ons_fixture().replace(b"18-09-2026", b"23-10-2026"), plan)


def test_external_snapshot_attribution_bounds_and_wholly_unseen_provider():
    series, metadata = load_external_series()
    assert metadata["data_sha256"] == external_data_digest()
    assert len(series) == 679
    assert metadata["observations"] == 162960
    assert metadata["nonnull_published_observations"] == 72141
    assert metadata["missing_suppressed_or_unreliable_observations"] == 90819
    assert [s["provider"] for s in metadata["training_sources"]] == ["eurostat"]
    assert [s["provider"] for s in metadata["audit_only_sources"]] == ["ons"]
    groups = metadata["geographic_groups"]
    assert [len(groups[split]) for split in ("train", "validation", "audit")] == [
        18,
        6,
        7,
    ]
    assert not set(groups["train"]) & set(groups["audit"])
    assert not any(
        group.startswith("ons:") for group in groups["train"] + groups["validation"]
    )
    assert "2021=100" in metadata["providers"]["eurostat"]["units"]
    assert "2024=100" in metadata["providers"]["ons"]["units"]
    for source in metadata["sources"]:
        assert source["license"] and source["license_url"].startswith("https://")
        assert source["raw_files"] and len(source["raw_sha256"]) == 64
    plan = json.loads(DATA_PATHS[0].read_text())
    assert not any(
        a != b and b.startswith(a) for a in plan["sectors"] for b in plan["sectors"]
    )


def test_terminal_data_cannot_change_development_cases():
    dataset = load_external_series()
    trained, exclusions = build_external_cases("train", dataset)
    validated, _ = build_external_cases("validation", dataset)
    assert trained and validated
    assert all(c.history.forecast_start + 11 <= parse_month("2024-08") for c in trained)
    assert all(c.group.startswith("eurostat:") for c in trained + validated)
    altered = copy.deepcopy(dataset)
    # Poison terminal values without reading them; explicit builders must remain
    # unchanged, including quality decisions. Audit-only countries remain unused.
    for row in altered[0]:
        row.values[row.months >= parse_month("2025-09")] = np.nan
        if row.source["provider"] == "ons":
            row.values[:] = np.nan
    after, after_exclusions = build_external_cases("train", altered)
    validation_after, _ = build_external_cases("validation", altered)
    assert exclusions == after_exclusions
    for before_cases, after_cases in ((trained, after), (validated, validation_after)):
        assert len(before_cases) == len(after_cases)
        for before, changed in zip(before_cases, after_cases, strict=True):
            np.testing.assert_array_equal(before.history.inflow, changed.history.inflow)
            np.testing.assert_array_equal(before.actual, changed.actual)
    with pytest.raises(ValueError, match="explicitly"):
        build_external_cases("all", dataset)


def test_later_break_does_not_remove_valid_earlier_training_windows():
    plan = json.loads(DATA_PATHS[0].read_text())
    months = np.arange(parse_month("2006-09"), parse_month("2026-09"))
    row = RevenueSeries(
        "eurostat:LV:G451",
        "G451",
        "eurostat:LV",
        months,
        np.ones(240),
        {"provider": "eurostat"},
    )
    metadata = {
        "protocol": plan,
        "flags": {row.identity: {parse_month("2015-09"): "b"}},
    }
    cases, exclusions = build_external_cases("train", ([row], metadata))
    assert any(c.history.forecast_start < parse_month("2014-09") for c in cases)
    assert any(c.history.forecast_start > parse_month("2020-09") for c in cases)
    assert any(
        e["reason"] == "break_or_definition_change_inside_window" for e in exclusions
    )


def test_download_bounds_chunked_body_before_retaining(monkeypatch):
    import scripts.import_external_data as importer

    class Stream:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"123"
            yield b"456"

    monkeypatch.setattr(importer, "MAX_DOWNLOAD_BYTES", 5)
    monkeypatch.setattr(importer.httpx, "stream", lambda *args, **kwargs: Stream())
    with pytest.raises(ValueError, match="8 MiB"):
        download("https://example.test")


def test_loader_rejects_provider_group_mismatch_and_oversize_snapshot(
    monkeypatch, tmp_path
):
    import capacity_ml.external_data as loader

    ons = json.loads(DATA_PATHS[2].read_text())
    ons["series"][0]["group"] = "eurostat:LV"
    ons["series"][0]["geography"] = "LV"
    tampered = tmp_path / "ons.json"
    tampered.write_text(json.dumps(ons))
    monkeypatch.setattr(loader, "DATA_PATHS", (*DATA_PATHS[:2], tampered))
    with pytest.raises(ValueError, match="provider/geography/identity mismatch"):
        load_external_series()
    monkeypatch.setattr(loader, "MAX_SNAPSHOT_BYTES", 32)
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 33)
    with pytest.raises(ValueError, match="snapshot exceeds"):
        read_snapshot(oversized)
