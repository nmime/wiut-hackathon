"""Synthetic fixtures verify comparison accounting, never borrower accuracy."""

import numpy as np
import pytest

from benchmarks.compare_real_revenue import (
    paired_interval,
    prediction_map,
    qualified,
    summary,
    validate_support,
)


def row(identity, provider="abs", group="abs:state", history=12):
    start = 2025 * 12
    return {
        "id": identity,
        "identity": identity,
        "provider": provider,
        "group": group,
        "sector": "test_fixture",
        "months": list(range(start - history, start)),
        "inflow": [100.0] * history,
        "forecast_start": start,
        "actual": [100.0] * 12,
    }


def test_primary_metric_gives_equal_provider_weight_and_never_pools_currency():
    rows = [row(str(i)) for i in range(10)] + [row("canada", "statcan")]
    predictions = {r["id"]: np.full(12, 110.0) for r in rows}
    predictions["canada"] = np.full(12, 140.0)
    result = summary(rows, predictions)
    assert result["provider_balanced_normalized_mae"] == pytest.approx(0.25)
    assert result["overall"]["mae_provider_units"] is None
    assert result["overall"]["wape_pct"] is None


def test_expected_refusal_is_counted_and_never_silently_changes_support():
    rows = [row("short", history=3), row("long")]
    document = {
        "cases": [
            {
                "id": "short",
                "status": "refused",
                "reason": {"code": "insufficient_history"},
            },
            {"id": "long", "status": "ok", "median": [100.0] * 12},
        ]
    }
    validate_support(rows, document, expected_refusals=True)
    result = summary(rows, prediction_map(document))
    assert result["refusal_rate_pct"] == 50
    assert result["supported_cases"] == 1
    document["cases"][0]["reason"]["code"] = "inference_failed"
    with pytest.raises(ValueError, match="short-history"):
        validate_support(rows, document, expected_refusals=True)


def test_missing_identity_invalid_output_or_unexpected_failure_cannot_be_dropped():
    with pytest.raises(ValueError, match="identities"):
        validate_support([row("required")], {"cases": []})
    with pytest.raises(ValueError, match="inference failure"):
        prediction_map({"cases": [{"id": "a", "status": "error"}]})
    with pytest.raises(ValueError, match="Invalid prediction"):
        prediction_map(
            {"cases": [{"id": "a", "status": "ok", "median": [float("nan")] * 12}]}
        )


def test_provider_guard_rejects_a_hidden_local_regression_or_missing_provider():
    reference = {
        "providers": {
            "abs": {"macro_case_normalized_mae": 0.1},
            "statcan": {"macro_case_normalized_mae": 0.2},
        }
    }
    improved = {
        "providers": {
            "abs": {"macro_case_normalized_mae": 0.01},
            "statcan": {"macro_case_normalized_mae": 0.205},
        }
    }
    assert not qualified(improved, reference)
    assert not qualified(
        {"providers": {"abs": {"macro_case_normalized_mae": 0.01}}}, reference
    )


def test_bootstrap_resamples_whole_groups_and_discloses_single_country_limit():
    rows = [row("a", "ons", "ons:GB"), row("b", "ons", "ons:GB")]
    default = {r["id"]: np.full(12, 120.0) for r in rows}
    better = {r["id"]: np.full(12, 110.0) for r in rows}
    result = paired_interval(rows, better, default)
    assert result["groups_by_provider"] == {"ons": 1}
    assert result["improvement_pct"] == 50
    assert result["descriptive_95pct_interval"] == [50, 50]
    assert "not estimated" in result["limitation"]
