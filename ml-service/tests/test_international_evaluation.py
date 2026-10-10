from types import SimpleNamespace

import numpy as np
import pytest

from capacity_ml.evaluate_international import (
    audit_acceptance,
    evaluate,
    evaluate_cases,
    forecast_metrics,
    grouped_improvement_interval,
)
from capacity_ml.forecasting import ForecastModel, MonthlyHistory
from capacity_ml.public_revenue import PublicCase


def case(identity="fixture", group="fixture", actual=None, history=None):
    observed = np.asarray(
        history if history is not None else np.arange(1, 25), dtype=float
    )
    return PublicCase(
        identity,
        "test_only_revenue",
        group,
        MonthlyHistory(
            np.arange(len(observed)), observed, np.zeros(len(observed)), len(observed)
        ),
        np.asarray(actual if actual is not None else [10, 20], dtype=float),
    )


def test_normalized_metrics_smape_and_seasonal_mase_use_only_history():
    row = case(actual=[0, 20])
    metrics = forecast_metrics([row], [np.array([0.0, 10.0])])
    assert metrics["mae_provider_units"] == 5
    assert metrics["normalized_mae"] == pytest.approx(5 / 18.5)
    assert metrics["smape_pct"] == pytest.approx(100 / 3)
    assert metrics["smape_both_zero_months"] == 1
    assert metrics["seasonal_mase"] == pytest.approx(5 / 12)
    assert metrics["wape_pct"] == 50
    assert metrics["zero_actual_months"] == 1
    assert metrics["wape_excluded_months"] == 0


def test_zero_and_short_mase_denominators_are_explicit():
    short = case("short", actual=[0, 0], history=[1, 2, 3])
    constant = case("constant", actual=[0, 0], history=[2] * 24)
    metrics = forecast_metrics([short, constant], [np.zeros(2), np.zeros(2)])
    assert metrics["seasonal_mase"] is None
    assert metrics["mase_included_months"] == 0
    assert metrics["mase_excluded_short_history_cases"] == 1
    assert metrics["mase_excluded_zero_denominator_cases"] == 1
    assert metrics["wape_pct"] is None
    assert metrics["smape_pct"] == 0
    assert metrics["smape_both_zero_months"] == 4


def test_cross_provider_raw_metrics_are_undefined_but_scale_invariant():
    small = case("small", actual=[10, 20])
    large = case("large", actual=[1000, 2000], history=np.arange(1, 25) * 100)
    predictions = [np.array([5.0, 10.0]), np.array([500.0, 1000.0])]
    values = forecast_metrics([small, large], predictions, same_units=False)
    assert values["mae_provider_units"] is None
    assert values["wape_pct"] is None
    expected = forecast_metrics([small], predictions[:1])
    assert values["normalized_mae"] == expected["normalized_mae"]
    assert values["normalized_wape_pct"] == expected["normalized_wape_pct"]


def test_group_bootstrap_is_deterministic_and_preserves_whole_entities():
    rows = [case("a", "one"), case("b", "one"), case("c", "two")]
    selected = [np.array([9.0, 18.0])] * 3
    baseline = [np.array([8.0, 16.0])] * 3
    interval = grouped_improvement_interval(rows, selected, baseline, replicates=100)
    assert interval == grouped_improvement_interval(
        rows, selected, baseline, replicates=100
    )
    assert interval["resampling_groups"] == 2
    assert interval["macro_case_normalized_mae_improvement_pct"] == 50
    assert interval["grouped_bootstrap_95pct_interval"] == [50, 50]
    one = grouped_improvement_interval(rows[:2], selected[:2], baseline[:2])
    assert one["interval_status"] == "undefined"
    assert one["resampling_groups"] == 1
    assert one["grouped_bootstrap_95pct_interval"] is None


def test_slices_and_counts_include_unique_overlapping_targets():
    rows = [case("a", "one"), case("a", "one"), case("b", "two", history=[1, 2, 3])]
    report = evaluate_cases(
        rows, [np.array([9.0, 18.0])] * 3, {"a": "first", "b": "second"}
    )
    overall = report["overall"]["selected"]
    assert overall["cases"] == 3
    assert overall["series"] == 2
    assert overall["months"] == 6
    assert overall["unique_target_observations"] == 4
    assert overall["wape_pct"] is None
    assert report["providers"]["first"]["selected"]["months"] == 4
    assert report["history_length"]["cold_3_to_11_months"]["selected"]["cases"] == 1
    assert report["forecast_horizon"]["2"]["cases"] == 3


def test_invalid_actuals_predictions_and_alignment_are_rejected():
    with pytest.raises(ValueError, match="nonempty"):
        forecast_metrics([], [])
    with pytest.raises(ValueError, match="identical shapes"):
        forecast_metrics([case()], [np.ones(3)])
    with pytest.raises(ValueError, match="Invalid real observations"):
        forecast_metrics([case(actual=[-1, 2])], [np.ones(2)])
    with pytest.raises(ValueError, match="finite and nonnegative"):
        forecast_metrics([case()], [np.array([np.inf, 2])])
    with pytest.raises(ValueError, match="positive"):
        grouped_improvement_interval([case()], [np.ones(2)], [np.ones(2)], replicates=0)


def test_acceptance_thresholds_are_fixed_and_negative_audits_fail():
    audit = {
        "overall": {"improvement": {"macro_case_normalized_mae_improvement_pct": 1}},
        "providers": {
            "a": {"improvement": {"macro_case_normalized_mae_improvement_pct": -10}}
        },
    }
    assert audit_acceptance(audit)["status"] == "pass"
    audit["providers"]["a"]["improvement"][
        "macro_case_normalized_mae_improvement_pct"
    ] = -10.01
    assert audit_acceptance(audit)["status"] == "fail"
    audit["providers"]["a"]["improvement"][
        "macro_case_normalized_mae_improvement_pct"
    ] = 50
    audit["overall"]["improvement"]["macro_case_normalized_mae_improvement_pct"] = 0
    assert audit_acceptance(audit)["status"] == "fail"


def test_mismatched_snapshot_fails_before_final_cases_are_built(monkeypatch):
    from capacity_ml import international_data

    monkeypatch.setattr(
        ForecastModel,
        "load",
        lambda _: SimpleNamespace(
            public_revenue_model=SimpleNamespace(
                metadata={"international_data_sha256": "trained-digest"}
            )
        ),
    )
    monkeypatch.setattr(
        international_data,
        "load_international_series",
        lambda: ([], {"data_sha256": "different-digest"}),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Do not inspect final labels for a mismatched model")

    monkeypatch.setattr(international_data, "build_international_cases", forbidden)
    with pytest.raises(ValueError, match="snapshot differs"):
        evaluate("test-only-artifact")
