"""Independent statistical checks on disclosed fixtures, never model accuracy."""

import hashlib

import numpy as np
import pytest

from benchmarks.fresh_experiment import SEED, block_interval
from final_model.calibration import LEVELS, calibrate, coverage, weighted_quantiles
from final_model.provider import verified_path


def row(identity, provider, year, *, history=24, actual=100):
    origin = year * 12 + 7
    return {
        "id": identity,
        "identity": identity,
        "provider": provider,
        "group": provider,
        "sector": "disclosed_synthetic_statistical_fixture",
        "slice": "full",
        "months": list(range(origin - history, origin)),
        "inflow": [100.0] * history,
        "forecast_start": origin,
        "actual": [float(actual)] * 12,
        "target_block": year,
    }


def test_provider_mass_not_sector_count_controls_empirical_quantiles():
    # One provider has 100 observations, the other only one. Their total
    # calibration masses remain equal, so the larger provider cannot erase the
    # upper tail of the smaller provider.
    values = [-0.2] * 100 + [0.4]
    weights = [1 / 100] * 100 + [1.0]
    quantiles = weighted_quantiles(values, weights)
    assert quantiles[9] == pytest.approx(-0.2)
    assert quantiles[49] == 0
    assert quantiles[89] == pytest.approx(0.4)
    assert np.all(np.diff(quantiles) >= 0)


def test_calibration_support_buckets_and_signed_residuals_are_separate():
    rows = [row("short", "a", 2020, history=3), row("annual", "b", 2020)]
    predictions = {"short": np.full(12, 80.0), "annual": np.full(12, 130.0)}
    grids = calibrate(rows, predictions)["buckets"]
    for period, count in (("1_3", 3), ("4_6", 3), ("7_12", 6)):
        short, annual = grids["short:" + period], grids["annual:" + period]
        assert short["provider_observations"] == {"a": count}
        assert annual["provider_observations"] == {"b": count}
        assert short["offsets"][89] == pytest.approx(0.2)
        assert short["offsets"][9] == 0
        assert annual["offsets"][9] == pytest.approx(-0.3)
        assert annual["offsets"][89] == 0


def test_reported_coverage_counts_actual_outcomes_inclusive_of_boundary():
    calibration = {
        "version": "empirical-real-revenue-grid-v1",
        "levels": LEVELS.tolist(),
        "buckets": {
            f"{support}:{period}": {"offsets": [float((q - 0.5) * 0.5) for q in LEVELS]}
            for support in ("short", "annual")
            for period in ("1_3", "4_6", "7_12")
        },
    }
    rows = [
        row("at_p10", "a", 2020, actual=80),
        row("below", "a", 2020, actual=79),
        row("above", "b", 2020, actual=121),
    ]
    predictions = {item["id"]: np.full(12, 100.0) for item in rows}
    result = coverage(rows, predictions, calibration)
    assert result["providers"]["a"]["observed_months"] == 24
    assert result["providers"]["a"]["above_p10_pct"] == 50
    assert result["providers"]["a"]["inside_p10_p90_pct"] == 50
    assert result["providers"]["b"]["above_p10_pct"] == 100
    assert result["providers"]["b"]["inside_p10_p90_pct"] == 0
    assert result["providers"]["a"]["mean_normalized_width"] == pytest.approx(0.4)


def test_paired_bootstrap_matches_independent_case_count_weighted_resampling():
    rows = [row("a0", "a", 2020)] + [row(f"a1_{i}", "a", 2021) for i in range(3)]
    rows += [row("b0", "b", 2020), row("b1", "b", 2021)]
    incumbent = {item["id"]: np.full(12, 110.0) for item in rows}
    candidate = {item["id"]: np.full(12, 105.0) for item in rows}
    candidate["a0"] = np.full(12, 120.0)
    candidate["b0"] = np.full(12, 112.0)
    draws = np.random.default_rng(SEED).integers(0, 2, (2000, 2))
    independent = []
    for draw in draws:
        provider_errors = []
        for provider in ("a", "b"):
            # Duplicated whole blocks remain duplicated; do not deduplicate
            # sampled cases or treat the annual block mean as a case weight.
            sample = [
                item
                for index in draw
                for item in rows
                if item["provider"] == provider and item["target_block"] == 2020 + index
            ]
            provider_errors.append(
                [
                    np.mean(
                        [
                            np.mean(
                                np.abs(
                                    np.asarray(item["actual"]) - predictions[item["id"]]
                                )
                            )
                            / 100
                            for item in sample
                        ]
                    )
                    for predictions in (candidate, incumbent)
                ]
            )
        challenger_error, reference_error = np.mean(provider_errors, axis=0)
        independent.append(100 * (1 - challenger_error / reference_error))
    result = block_interval(rows, candidate, incumbent)
    np.testing.assert_allclose(
        result["descriptive_95pct_interval"], np.quantile(independent, [0.025, 0.975])
    )


def test_paired_bootstrap_refuses_different_country_year_panels():
    rows = [row("a0", "a", 2020), row("a1", "a", 2021), row("b0", "b", 2020)]
    predictions = {item["id"]: np.full(12, 110.0) for item in rows}
    with pytest.raises(ValueError, match="aligned multi-year"):
        block_interval(rows, predictions, predictions)


def test_component_bytes_and_path_cannot_be_substituted(tmp_path):
    target = tmp_path / "component.json"
    target.write_text("frozen component")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    snapshot = verified_path(tmp_path, "component.json", expected)
    assert snapshot == b"frozen component"
    with pytest.raises(ValueError, match="SHA-256"):
        verified_path(tmp_path, "../component.json", expected)
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="SHA-256"):
        verified_path(tmp_path, "linked.json", expected)
    target.write_text("substituted component")
    # A verified immutable snapshot survives later changes to the backing file;
    # loading that snapshot cannot reopen unverified replacement bytes.
    assert snapshot == b"frozen component"
    with pytest.raises(ValueError, match="SHA-256"):
        verified_path(tmp_path, "component.json", expected)
