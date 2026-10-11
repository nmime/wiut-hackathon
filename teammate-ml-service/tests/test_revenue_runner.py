"""Revenue-only benchmark checks; generated revenues here are test fixtures."""

from __future__ import annotations

import copy
import json
import subprocess
import sys

import numpy as np
import pytest

from benchmark.revenue_runner import (
    SERVICE_ROOT,
    UNKNOWN_PROFILE_COLUMNS,
    RevenueRunner,
    build_profile,
    inflow_predictions,
    month_index,
    month_label,
    validate_case,
)


def synthetic_case(count=36, scale=1.0, start="2024-01"):
    forecast_start = month_index(start)
    indices = list(range(forecast_start - count, forecast_start))
    revenue = [
        float(scale * (100 + 20 * np.sin(2 * np.pi * month / 12))) for month in indices
    ]
    return {
        "id": "test-only-synthetic-revenue",
        "months": [month_label(month) for month in indices],
        "inflow": revenue,
        "forecast_start": start,
    }


@pytest.fixture(scope="module")
def runner():
    instance = RevenueRunner()
    yield instance
    instance.close()


def test_missing_metrics_are_unknown_and_history_is_not_reallocated():
    case = synthetic_case()
    identity, months, inflow, _, _ = validate_case(case)
    profile = build_profile(identity, months, inflow)
    np.testing.assert_array_equal(profile["inflow_total"], inflow)
    assert profile[list(UNKNOWN_PROFILE_COLUMNS)].isna().all().all()
    assert profile["month_idx"].tolist() == months


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda case: case.update(actual=[999] * 12), "invalid_case_fields"),
        (lambda case: case.update(inflow=[True] * 36), "invalid_inflow"),
        (lambda case: case.update(inflow=[float("nan")] * 36), "invalid_inflow"),
        (lambda case: case.update(inflow=[-1.0] * 36), "invalid_inflow"),
        (lambda case: case.update(inflow=[0.0] * 36), "no_positive_revenue"),
        (
            lambda case: case["months"].__setitem__(5, "2021-05"),
            "noncontiguous_history",
        ),
        (lambda case: case.update(forecast_start="2024-02"), "misaligned_forecast"),
    ],
)
def test_rejects_future_labels_unobserved_months_and_invalid_revenue(
    runner, change, reason
):
    case = synthetic_case()
    change(case)
    result = runner.predict_case(case)
    assert result["status"] == "refused"
    assert result["reason"]["code"] == reason
    assert "predictions" not in result


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        (synthetic_case(count=5), "insufficient_history"),
        (synthetic_case(start="2019-12"), "unsupported_calendar"),
        (synthetic_case(start="2029-02"), "unsupported_calendar"),
    ],
)
def test_short_history_and_frozen_calendar_refusals(runner, case, reason):
    result = runner.predict_case(case)
    assert result["status"] == "refused"
    assert result["reason"]["code"] == reason


def test_real_frozen_inference_identity_quantiles_and_history_only_transform(runner):
    case = synthetic_case()
    original = copy.deepcopy(case)
    result = runner.run([case])["cases"][0]
    assert case == original
    assert result["status"] == "ok"
    assert result["forecast_months"] == [f"2024-{month:02d}" for month in range(1, 13)]
    assert result["transform"]["history_mean_original_units"] == pytest.approx(100)
    assert result["transform"]["fitted_on"] == "provided_observed_history_only"
    assert result["auxiliary_inputs"] == "unknown_nan"
    assert result["industry_prior"] == "unavailable_not_selected"
    predictions = result["predictions"]
    assert all(len(values) == 12 for values in predictions.values())
    assert all(
        np.isfinite(values).all() and np.min(values) >= 0
        for values in predictions.values()
    )
    assert np.all(np.asarray(predictions["p10"]) <= predictions["conformal_median"])
    assert np.all(np.asarray(predictions["conformal_median"]) <= predictions["p90"])
    assert "diagnostic_native_units" not in result
    assert "free_cash_flow" not in result
    manifest = json.loads((SERVICE_ROOT / "vendor-manifest.json").read_text())
    assert runner.identity["model_artifact_sha256"] == manifest["model_artifact_sha256"]
    assert runner.identity["archive_sha256"] == manifest["archive_sha256"]
    assert runner.identity["training_metadata"]["n_train_businesses"] == 420
    json.dumps(runner.run([case]), allow_nan=False)


def test_primary_is_scale_equivariant_but_native_diagnostic_is_opt_in(runner):
    unscaled = synthetic_case()
    scaled = synthetic_case(scale=1000)
    first = runner.predict_case(unscaled)
    second = runner.predict_case(scaled, native_unit_diagnostic=True)
    assert first["status"] == second["status"] == "ok"
    for quantile in ("median", "p10", "p90"):
        np.testing.assert_allclose(
            second["predictions"][quantile],
            np.asarray(first["predictions"][quantile]) * 1000,
            rtol=1e-12,
        )
    assert second["diagnostic_native_units"]["status"] == "ok"
    assert second["diagnostic_native_units"]["role"] == "scale_sensitivity_only"
    # Additive vendor constants make native-unit inference different from primary.
    assert not np.allclose(
        second["diagnostic_native_units"]["predictions"]["median"],
        second["predictions"]["median"],
        rtol=1e-4,
    )


def test_integer_month_ids_match_string_months(runner):
    case = synthetic_case(count=6, start="2020-01")
    integer_case = {
        **case,
        "months": [month_index(month) for month in case["months"]],
        "forecast_start": month_index(case["forecast_start"]),
    }
    strings = runner.predict_case(case)
    integers = runner.predict_case(integer_case)
    assert strings["status"] == integers["status"] == "ok"
    assert strings["predictions"] == integers["predictions"]


def test_output_validator_does_not_repair_invalid_native_quantiles():
    class InvalidForecast:
        in_p50 = np.ones(12)

        def q(self, level, which):
            return np.full(12, 4.0 if level == 0.1 else 3.0)

    with pytest.raises(ValueError, match="P10 <= conformal P50 <= P90"):
        inflow_predictions(InvalidForecast(), 1.0)


def test_scale_uses_latest_twelve_observations_without_outflow_inference(
    runner, monkeypatch
):
    case = synthetic_case()
    case["inflow"] = [1000.0] * 24 + [20.0] * 12

    def forbidden_outflow(*args, **kwargs):
        pytest.fail("Revenue-only benchmark must not call the outflow booster")

    monkeypatch.setattr(runner.bundle.forecast.b_out, "predict", forbidden_outflow)
    result = runner.run({"cases": [case]})["cases"][0]
    assert result["status"] == "ok"
    assert result["transform"]["history_mean_original_units"] == 20
    assert result["transform"]["original_units_per_normalized_unit"] == 0.2
    assert result["transform"]["window_months"] == 12


def test_conformal_interval_need_not_contain_native_point_center():
    class BiasedForecast:
        in_p50 = np.zeros(12)

        def q(self, level, which):
            return np.full(12, 1 + level)

    result = inflow_predictions(BiasedForecast(), 1.0)
    assert result["median"] == [0.0] * 12
    assert result["conformal_median"] == [1.5] * 12


def test_cli_serializes_success_refusal_and_opt_in_diagnostic(tmp_path):
    input_path = tmp_path / "history.json"
    output_path = tmp_path / "result.json"
    input_path.write_text(
        json.dumps([synthetic_case(count=6), synthetic_case(count=5)])
    )
    process = subprocess.run(
        [
            sys.executable,
            str(SERVICE_ROOT / "benchmark/revenue_runner.py"),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--native-unit-diagnostic",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    output = json.loads(output_path.read_text())
    assert output["native_unit_diagnostic_enabled"] is True
    assert [case["status"] for case in output["cases"]] == ["ok", "refused"]
    assert output["cases"][0]["diagnostic_native_units"]["status"] == "ok"
    assert output["cases"][1]["reason"]["code"] == "insufficient_history"
