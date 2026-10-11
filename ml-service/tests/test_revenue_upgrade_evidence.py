"""Statistical invariants use disclosed fixtures, never accuracy evidence."""

import numpy as np
import pytest

from benchmarks.fresh_experiment import block_interval, compact_scores, views
from final_model.calibration import calibrate, revenue_grid


def fixture(identity, provider, year=2020, actual=100.0):
    start = year * 12 + 7
    return {
        "id": identity,
        "identity": identity,
        "provider": provider,
        "group": provider,
        "sector": "synthetic_test",
        "slice": "full",
        "months": list(range(start - 24, start)),
        "inflow": [100.0] * 24,
        "forecast_start": start,
        "actual": [actual] * 12,
        "target_block": year,
    }


def test_block_interval_preserves_case_weights_when_quality_counts_vary_by_year():
    rows = [fixture("a", "canada", 2020)] + [
        fixture(f"b{i}", "canada", 2021) for i in range(3)
    ]
    rows += [fixture("nz0", "nz", 2020), fixture("nz1", "nz", 2021)]
    incumbent = {row["id"]: np.full(12, 110.0) for row in rows}
    candidate = {row["id"]: np.full(12, 105.0) for row in rows}
    candidate["a"] = np.full(12, 120.0)
    a, b = compact_scores(rows, candidate), compact_scores(rows, incumbent)
    expected = 100 * (
        1
        - a["provider_balanced_normalized_mae"] / b["provider_balanced_normalized_mae"]
    )
    result = block_interval(rows, candidate, incumbent)
    assert result["improvement_pct"] == pytest.approx(expected)
    assert result["paired_annual_blocks"] == [2020, 2021]


def test_single_block_is_not_reported_as_a_precise_confidence_interval():
    rows = [fixture("a", "canada")]
    predictions = {"a": np.full(12, 100.0)}
    with pytest.raises(ValueError, match="multi-year"):
        block_interval(rows, predictions, predictions)


def test_real_grid_is_monotone_median_preserving_and_scale_equivariant():
    rows = views(
        [fixture(f"a{i}", "canada", actual=float(80 + 10 * i)) for i in range(5)]
    )
    predictions = {row["id"]: np.full(12, 100.0) for row in rows}
    calibration = calibrate(rows, predictions)
    grid = revenue_grid(np.full(12, 100.0), 100.0, 24, calibration)
    assert grid.shape == (12, 99)
    assert np.all(np.diff(grid, axis=1) >= 0)
    assert np.all(grid[:, 49] == 100)
    np.testing.assert_allclose(
        revenue_grid(np.full(12, 500.0), 500.0, 24, calibration), grid * 5
    )
    assert np.all(grid >= 0)


def test_real_grid_rejects_malformed_calibration_or_future_center():
    rows = views([fixture("a", "canada")])
    calibration = calibrate(rows, {row["id"]: np.full(12, 100.0) for row in rows})
    calibration["buckets"]["annual:1_3"]["offsets"][49] = 1
    with pytest.raises(ValueError, match="median anchored"):
        revenue_grid(np.full(12, 100.0), 100.0, 24, calibration)
    with pytest.raises(ValueError, match="malformed"):
        revenue_grid(np.full(12, np.nan), 100.0, 24, calibration)
