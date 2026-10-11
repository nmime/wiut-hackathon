"""Frozen real-revenue residual grids; no expense/default coverage claim."""

from collections import defaultdict

import numpy as np

LEVELS = np.arange(1, 100, dtype=float) / 100
VERSION = "empirical-real-revenue-grid-v1"


def bucket(history_length, horizon):
    support = "short" if history_length < 12 else "annual"
    period = "1_3" if horizon <= 3 else "4_6" if horizon <= 6 else "7_12"
    return f"{support}:{period}"


def weighted_quantiles(values, weights):
    values, weights = np.asarray(values, dtype=float), np.asarray(weights, dtype=float)
    if not len(values) or values.shape != weights.shape:
        raise ValueError("Residual values and weights must be nonempty and aligned")
    if (
        not np.isfinite(values).all()
        or not np.isfinite(weights).all()
        or np.any(weights <= 0)
    ):
        raise ValueError("Residuals must be finite and weights positive")
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order]) / np.sum(weights)
    indices = np.searchsorted(cumulative, LEVELS, side="left")
    quantiles = values[order][np.minimum(indices, len(order) - 1)]
    quantiles[:49] = np.minimum(quantiles[:49], 0)
    quantiles[49] = 0
    quantiles[50:] = np.maximum(quantiles[50:], 0)
    return quantiles


def calibrate(rows, predictions):
    grouped = defaultdict(list)
    for row in rows:
        scale = float(np.mean(row["inflow"][-12:]))
        if scale <= 0:
            raise ValueError("Calibration requires positive historical scale")
        for h, actual in enumerate(row["actual"], 1):
            grouped[bucket(len(row["inflow"]), h)].append(
                (
                    row["provider"],
                    (actual - predictions[row["id"]][h - 1]) / scale,
                    row["id"],
                    (row["identity"], row["forecast_start"] + h - 1)
                    if "identity" in row and "forecast_start" in row
                    else (row["id"], h),
                )
            )
    expected = {
        f"{support}:{period}"
        for support in ("short", "annual")
        for period in ("1_3", "4_6", "7_12")
    }
    if set(grouped) != expected:
        raise ValueError("Calibration lacks a declared history/horizon bucket")
    grids = {}
    for name, samples in sorted(grouped.items()):
        counts = {
            provider: sum(row[0] == provider for row in samples)
            for provider in {row[0] for row in samples}
        }
        offsets = weighted_quantiles(
            [row[1] for row in samples], [1 / counts[row[0]] for row in samples]
        )
        grids[name] = {
            "offsets": offsets.tolist(),
            "observations": len(samples),
            "cases": len({row[2] for row in samples}),
            "unique_target_coordinates": len({row[3] for row in samples}),
            "provider_observations": counts,
        }
    return {
        "version": VERSION,
        "levels": LEVELS.tolist(),
        "buckets": grids,
        "method": "Provider-balanced signed history-normalized real development residual quantiles; median anchored at zero; empirical dependent aggregate grid, no formal prospective/borrower coverage guarantee.",
    }


def revenue_grid(median, scale, history_length, calibration):
    median = np.asarray(median, dtype=float)
    if (
        median.shape != (12,)
        or not np.isfinite(median).all()
        or np.any(median < 0)
        or not np.isfinite(scale)
        or scale <= 0
    ):
        raise ValueError("Revenue center/scale is malformed")
    if calibration["version"] != VERSION or not np.array_equal(
        calibration["levels"], LEVELS
    ):
        raise ValueError("Unrecognized real-revenue calibration")
    result = []
    for h, center in enumerate(median, 1):
        offsets = np.asarray(
            calibration["buckets"][bucket(history_length, h)]["offsets"]
        )
        if (
            offsets.shape != (99,)
            or not np.isfinite(offsets).all()
            or np.any(np.diff(offsets) < 0)
            or offsets[49] != 0
        ):
            raise ValueError(
                "Calibration grid is not finite, ordered and median anchored"
            )
        result.append(np.maximum(center + scale * offsets, 0))
    return np.asarray(result)


def coverage(rows, predictions, calibration):
    totals = defaultdict(
        lambda: {
            "months": 0,
            "above_p10": 0,
            "above_p20": 0,
            "inside_p10_p90": 0,
            "width_sum": 0.0,
        }
    )
    for row in rows:
        scale = float(np.mean(row["inflow"][-12:]))
        grid = revenue_grid(
            predictions[row["id"]], scale, len(row["inflow"]), calibration
        )
        for h, actual in enumerate(row["actual"]):
            part = totals[row["provider"]]
            part["months"] += 1
            part["above_p10"] += int(actual >= grid[h, 9])
            part["above_p20"] += int(actual >= grid[h, 19])
            part["inside_p10_p90"] += int(grid[h, 9] <= actual <= grid[h, 89])
            part["width_sum"] += float((grid[h, 89] - grid[h, 9]) / scale)
    return {
        "nominal_targets_pct": {"above_p10": 90, "above_p20": 80, "inside_p10_p90": 80},
        "providers": {
            name: {
                "observed_months": part["months"],
                **{
                    key + "_pct": 100 * part[key] / part["months"]
                    for key in ("above_p10", "above_p20", "inside_p10_p90")
                },
                "mean_normalized_width": part["width_sum"] / part["months"],
            }
            for name, part in sorted(totals.items())
        },
        "scope": "Revenue observations only; expenses/free flow/repayment outcomes uncalibrated. Dependent revised-vintage series; reported empirical coverage, not a guaranteed borrower confidence level.",
    }
