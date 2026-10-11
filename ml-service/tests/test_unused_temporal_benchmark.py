"""Reservation integrity and leakage checks without loading or scoring a model."""

import json

import numpy as np
import pytest

from benchmarks import unused_temporal as reserved
from capacity_ml.evaluate_public import build_cases as build_retail_baseline
from capacity_ml.external_data import build_external_cases, load_external_series
from capacity_ml.international_data import (
    build_international_cases,
    load_international_series,
)
from capacity_ml.public_data import load_public_data
from capacity_ml.public_revenue import build_cases
from capacity_ml.revenue_data import RevenueSeries, load_revenue_series, parse_month


@pytest.fixture(scope="module")
def frozen_reservation():
    return reserved.load_reserved_cases()


def test_reserved_real_targets_are_unique_and_after_training(frozen_reservation):
    cases, manifest = frozen_reservation
    coordinates = {
        (case.identity, case.history.forecast_start + horizon)
        for case in cases
        for horizon in range(len(case.actual))
    }
    assert len(cases) == 448
    assert len(coordinates) == sum(len(case.actual) for case in cases) == 4540
    assert manifest["overlap_with_original_target_coordinates"] == 0
    assert manifest["overlap_with_original_case_history_coordinates"] == 0
    assert set(manifest["providers"]) == {
        "uzbekistan_siat",
        "abs",
        "statcan",
        "eurostat",
    }
    ends = {
        "uzbekistan_siat": parse_month("2025-12"),
        "abs": parse_month("2023-06"),
        "statcan": parse_month("2024-07"),
        "eurostat": parse_month("2024-08"),
    }
    for case in cases:
        provider = reserved._provider(case)
        assert case.history.forecast_start > ends[provider]
        assert np.all(case.history.months < case.history.forecast_start)
        assert len(case.history.months) <= (48 if provider == "uzbekistan_siat" else 60)
        assert np.isfinite(case.actual).all()
        assert (case.actual >= 0).all()


def test_retail_identity_aliases_cannot_hide_prior_public_targets(frozen_reservation):
    cases, manifest = frozen_reservation
    baseline, _ = build_retail_baseline(load_public_data())
    prior_coordinates = {
        ("retail:" + case.code, case.history.forecast_start + horizon)
        for rows in baseline.values()
        for case in rows
        for horizon in range(len(case.actual))
    }
    reserved_coordinates = {
        (case.identity, case.history.forecast_start + horizon)
        for case in cases
        for horizon in range(len(case.actual))
    }
    assert not reserved_coordinates & prior_coordinates
    assert set(manifest["verified_public_baseline_panels"]) == {
        "train",
        "validation",
        "test",
    }
    assert manifest["verified_public_baseline_panels"]["test"]["cases"] == 26


def test_reserved_coordinates_disjoint_from_every_original_real_builder(
    frozen_reservation,
):
    reserved_cases, _ = frozen_reservation
    uz, _ = build_cases(*load_revenue_series())
    original_cases = sum(uz.values(), [])
    international = load_international_series()
    external = load_external_series()
    for split in ("train", "validation", "test"):
        cases, _ = build_international_cases(split, international)
        original_cases.extend(cases)
    for split in ("train", "validation", "audit"):
        cases, _ = build_external_cases(split, external)
        original_cases.extend(cases)
    original_coordinates = {
        (case.identity, case.history.forecast_start + horizon)
        for case in original_cases
        for horizon in range(len(case.actual))
    }
    new_coordinates = {
        (case.identity, case.history.forecast_start + horizon)
        for case in reserved_cases
        for horizon in range(len(case.actual))
    }
    assert not new_coordinates & original_coordinates


@pytest.mark.parametrize(
    "field,value",
    [
        ("sorted_target_coordinates_sha256", "0" * 64),
        ("actual_targets_sha256", "0" * 64),
        ("case_identities_sha256", "0" * 64),
        ("source_sha256", {}),
    ],
)
def test_changed_frozen_manifest_fails_closed(
    monkeypatch, tmp_path, frozen_reservation, field, value
):
    _, manifest = frozen_reservation
    changed = {**manifest, field: value}
    path = tmp_path / "changed-reservation.json"
    path.write_text(json.dumps(changed))
    monkeypatch.setattr(reserved, "MANIFEST_PATH", path)
    # Reusing the independently rebuilt frozen fixture avoids repeating dataset
    # construction; the invariant under test is strict comparison, not fitting.
    monkeypatch.setattr(reserved, "reserve_cases", lambda: frozen_reservation)
    with pytest.raises(ValueError, match="Reserved temporal targets"):
        reserved.load_reserved_cases()


def test_missing_manifest_cannot_be_created_during_evaluation(monkeypatch, tmp_path):
    path = tmp_path / "not-reserved.json"
    monkeypatch.setattr(reserved, "MANIFEST_PATH", path)
    with pytest.raises(ValueError, match="Reserve target coordinates"):
        reserved.load_reserved_cases()
    assert not path.exists()


def test_reserved_window_preserves_missing_and_methodology_exclusions():
    start = parse_month("2025-09")
    months = np.arange(start - 24, start + 12)
    values = np.full(len(months), 100.0)
    row = RevenueSeries("eurostat:XX:test", "test", "eurostat:XX", months, values, {})
    _, reason = reserved._window(row, start, 12, 60, 24, {start - 3: "b"})
    assert reason == "break_or_definition_change_inside_window"
    # Match the original Eurostat rule: a regime marker at the exact window
    # boundary starts the supplied definition rather than breaking it inside.
    case, reason = reserved._window(row, start, 12, 60, 24, {start - 24: "b"})
    assert case is not None and reason is None
    values[-1] = np.nan
    _, reason = reserved._window(row, start, 12, 60, 24)
    assert reason == "missing_suppressed_or_unreliable_month"
    values[-1] = -1
    _, reason = reserved._window(row, start, 12, 60, 24)
    assert reason == "negative_actual_revenue"
