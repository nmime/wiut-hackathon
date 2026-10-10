"""Public benchmark split/quality tests; generated numbers here are test fixtures."""

from copy import deepcopy

import numpy as np
import pytest

from capacity_ml.evaluate_public import (
    TRAIN_LAST_MONTH,
    build_cases,
    evaluate,
    fit_public_model,
    forecast_metrics,
    markdown_report,
)
from capacity_ml.forecasting import feature_matrix
from capacity_ml.public_data import load_public_data


def fixture_dataset() -> dict:
    series = []
    for code, scale, national in (
        ("a", 1.0, False),
        ("b", 3.0, False),
        ("total", 4.0, True),
    ):
        observations = []
        for year in range(2020, 2027):
            ytd = 0.0
            for month in range(1, 13):
                value = scale * (100 + month * 5) * (1.12 ** (year - 2020))
                ytd += value
                observations.append(
                    {
                        "month": f"{year}-{month:02}",
                        "value_ytd_million_uzs": ytd,
                        "monthly_million_uzs": value,
                    }
                )
        series.append(
            {
                "code": code,
                "region": f"Fixture {code}",
                "is_national_total": national,
                "observations": observations,
            }
        )
    return {"source": {"publisher": "Generated test fixture"}, "series": series}


def test_training_targets_end_before_validation_and_national_total_is_excluded():
    cases, excluded = build_cases(fixture_dataset())
    assert not excluded
    assert len(cases["train"]) == 2 * 13
    assert len(cases["validation"]) == 2
    assert len(cases["test"]) == 4
    assert {case.code for split in cases.values() for case in split} == {"a", "b"}
    assert all(
        len(case.history.months) >= 12
        and case.history.months[-1] < case.history.forecast_start
        and case.history.forecast_start + 11 <= TRAIN_LAST_MONTH
        for case in cases["train"]
    )
    assert {case.target_year for case in cases["validation"]} == {2023}
    assert {case.target_year for case in cases["test"]} == {2024, 2025}


def test_post_training_values_cannot_change_training_features_or_targets():
    original = fixture_dataset()
    changed = deepcopy(original)
    for series in changed["series"]:
        for observation in series["observations"]:
            if observation["month"] >= "2023-01":
                observation["monthly_million_uzs"] *= 1000
    original_cases, _ = build_cases(original)
    changed_cases, _ = build_cases(changed)
    for before, after in zip(
        original_cases["train"], changed_cases["train"], strict=True
    ):
        np.testing.assert_array_equal(before.actual, after.actual)
        np.testing.assert_array_equal(
            feature_matrix(before.history), feature_matrix(after.history)
        )


def test_test_actuals_change_errors_without_changing_model_selection():
    original = fixture_dataset()
    changed = deepcopy(original)
    for series in changed["series"]:
        for observation in series["observations"]:
            if observation["month"].startswith(("2024-", "2025-")):
                observation["monthly_million_uzs"] *= 10
    before, after = evaluate(original), evaluate(changed)
    assert before["training"] == after["training"]
    assert before["selection"] == after["selection"]
    assert before["held_out_test"] != after["held_out_test"]
    assert not after["protocol"]["test_used_for_training_or_selection"]
    assert not after["protocol"]["entity_disjoint"]


@pytest.mark.parametrize("invalid", [-1.0, None, float("nan")])
def test_invalid_increment_excludes_entire_affected_case_without_imputation(invalid):
    dataset = fixture_dataset()
    observation = next(
        row for row in dataset["series"][0]["observations"] if row["month"] == "2023-11"
    )
    observation["monthly_million_uzs"] = invalid
    cases, exclusions = build_cases(dataset)
    assert len(cases["train"]) == 26
    assert len(cases["validation"]) == 1
    assert len(cases["test"]) == 2
    assert len(exclusions) == 3
    assert {row["target_start"] for row in exclusions} == {
        "2023-01",
        "2024-01",
        "2025-01",
    }
    assert all(row["issues"][0]["month"] == "2023-11" for row in exclusions)
    assert observation["monthly_million_uzs"] is invalid


def test_missing_month_excludes_training_and_later_histories():
    dataset = fixture_dataset()
    dataset["series"][0]["observations"] = [
        row for row in dataset["series"][0]["observations"] if row["month"] != "2020-05"
    ]
    cases, exclusions = build_cases(dataset)
    assert len(cases["train"]) == 13
    assert len(cases["validation"]) == 1
    assert len(cases["test"]) == 2
    assert len(exclusions) == 16
    assert all(row["issues"][0]["reason"] == "missing_month" for row in exclusions)


def test_training_refuses_later_evaluation_case():
    cases, _ = build_cases(fixture_dataset())
    with pytest.raises(ValueError, match="temporal boundary"):
        fit_public_model(cases["validation"])


def test_percentage_metrics_count_zero_denominators_and_keep_currency_units():
    metrics = forecast_metrics(
        np.array([0.0, 100.0, 200.0]), np.array([10.0, 110.0, 180.0])
    )
    assert metrics["mae_million_uzs"] == pytest.approx(40 / 3)
    assert metrics["mape_positive_actual_pct"] == pytest.approx(10)
    assert metrics["mape_included_months"] == 2
    assert metrics["mape_excluded_zero_months"] == 1
    assert metrics["wape_denominator_million_uzs"] == 300
    assert metrics["wape_pct"] == pytest.approx(40 / 300 * 100)
    with pytest.raises(ValueError, match="never clipped"):
        forecast_metrics(np.array([-1.0]), np.array([0.0]))


def test_official_snapshot_quality_exclusions_and_report_scope():
    dataset = load_public_data()
    result = evaluate(dataset)
    assert result["training"]["regions"] == 14
    assert result["training"]["rolling_origins"] == 182
    assert result["training"]["latest_target_month"] == "2022-12"
    assert result["selection"]["validation"]["regions"] == 13
    assert result["held_out_test"]["region_year_cases"] == 26
    assert result["held_out_test"]["candidates"]["seasonal_naive"]["months"] == 312
    assert len(result["exclusions"]) == 3
    assert all(row["region"] == "Fergana region" for row in result["exclusions"])
    assert (
        result["selected_held_out_test"]
        == result["held_out_test"]["candidates"][
            result["selection"]["selected_candidate"]
        ]
    )
    text = markdown_report(result)
    assert "not an entity-disjoint test" in text
    assert "does not measure borrower payment capacity" in text
    assert "million UZS" in text
