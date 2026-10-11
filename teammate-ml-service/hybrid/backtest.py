"""Descriptive same-principal schedule comparison; labels stay outside scoring."""

from __future__ import annotations

import numpy as np


def compare_actual_surplus(assessment: dict, observed_future_surplus) -> dict:
    """Evaluate actual provided surplus against offered and annuity payments.

    Call only after a forecast is frozen. Test fixtures must be disclosed; this
    function does not turn revenue-only observations into repayment labels.
    """
    actual = np.asarray(observed_future_surplus, dtype=float)
    if actual.ndim != 1 or not 1 <= len(actual) <= 12 or not np.isfinite(actual).all():
        raise ValueError("Observed surplus must have 1–12 finite future values.")
    comparison = assessment.get("comparison")
    if comparison is None:
        raise ValueError("No positive offered loan is available for comparison.")
    result = {
        "principal": comparison["same_principal"],
        "annual_rate": comparison["same_annual_rate"],
        "term_months": comparison["same_term_months"],
        "observed_months": len(actual),
        "scope": "Payment overload descriptive comparison; not default or actual repayment classification.",
    }
    for name, rows in (
        ("offered", assessment["offered"]["rows"]),
        ("annuity", comparison["annuity_rows"]),
    ):
        payments = np.asarray([row["payment"] for row in rows])[: len(actual)]
        overload = np.maximum(payments - actual, 0)
        result[name] = {
            "overload_months": int(np.count_nonzero(overload > 1.0)),
            "overload_volume": float(np.sum(overload)),
            "interest_total_full_term": comparison[f"{name}_total_interest"],
        }
    return result
