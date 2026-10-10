"""Scale-free revenue features and bounded, observation-only forecast baselines.

No expense or repayment values are inferred from public revenue histories.
"""

import numpy as np

from .forecasting import MonthlyHistory, normalizer, seasonal_forecast

REVENUE_FEATURE_NAMES = (
    *(f"revenue_lag_{lag}" for lag in range(1, 13)),
    "mean_3",
    "mean_6",
    "mean_12",
    "std_12",
    "recent_level_ratio",
    "annual_log_growth",
    "horizon",
    "history_length",
    "seasonal_naive",
    "damped_seasonal",
    "robust_harmonic",
    "calendar_sin",
    "calendar_cos",
)


def revenue_baselines(history: MonthlyHistory) -> dict[str, np.ndarray]:
    scale = normalizer(history)
    values = np.asarray(history.inflow, dtype=float) / scale
    neutral = MonthlyHistory(
        history.months, history.inflow, np.zeros(len(values)), history.forecast_start
    )
    naive = np.maximum(seasonal_forecast(neutral) / scale, 0)
    yearly_log_growth = 0.0
    if len(values) >= 24:
        previous = values[-24:-12]
        recent = values[-12:]
        valid = (previous > 0.1) & (recent > 0.1)
        if np.count_nonzero(valid) >= 6:
            yearly_log_growth = float(
                np.clip(np.median(np.log(recent[valid] / previous[valid])), -0.7, 0.7)
            )
    damped = naive * np.exp(0.65 * yearly_log_growth)
    # Fit a small harmonic regression robustly in log revenue. Ridge shrinkage
    # prevents extrapolating a noisy partial seasonal cycle as secular growth.
    harmonic = np.full(12, float(np.mean(values[-12:])))
    if len(values) >= 18:
        observed_months = history.months[-36:]
        observed = values[-36:]
        anchor = int(observed_months[-1])
        positions = (observed_months - anchor) / 12
        angles = 2 * np.pi * (observed_months % 12) / 12
        design = np.column_stack(
            [np.ones(len(observed)), positions, np.sin(angles), np.cos(angles)]
        )
        target = np.log(np.maximum(observed, 0.05))
        regularization = np.diag([0, 2.0, 0.4, 0.4])
        weights = np.ones(len(observed))
        coefficients = np.zeros(4)
        for _ in range(3):
            weighted = design * weights[:, None]
            coefficients = np.linalg.solve(
                design.T @ weighted + regularization,
                weighted.T @ target,
            )
            residual = target - design @ coefficients
            weights = 1 / (1 + (residual / 0.3) ** 2)
        coefficients[1] = np.clip(coefficients[1], -0.7, 0.7)
        future = np.arange(history.forecast_start, history.forecast_start + 12)
        future_angles = 2 * np.pi * (future % 12) / 12
        future_design = np.column_stack(
            [
                np.ones(12),
                (future - anchor) / 12,
                np.sin(future_angles),
                np.cos(future_angles),
            ]
        )
        harmonic = np.exp(np.clip(future_design @ coefficients, -5, 3))
    return {
        "seasonal_naive": naive * scale,
        "damped_seasonal": damped * scale,
        "robust_harmonic": harmonic * scale,
    }


def revenue_feature_matrix(history: MonthlyHistory) -> np.ndarray:
    scale = normalizer(history)
    values = np.asarray(history.inflow, dtype=float) / scale
    mean = float(np.mean(values[-12:]))
    lags = [float(values[-lag]) if len(values) >= lag else mean for lag in range(1, 13)]
    prior = float(np.mean(values[-24:-12])) if len(values) >= 24 else mean
    yearly_log_growth = float(
        np.clip(np.log(max(mean, 0.05) / max(prior, 0.05)), -0.7, 0.7)
    )
    base = lags + [
        float(np.mean(values[-3:])),
        float(np.mean(values[-6:])),
        mean,
        float(np.std(values[-12:])),
        float(np.mean(values[-3:])) / max(mean, 0.05),
        yearly_log_growth,
    ]
    baselines = revenue_baselines(history)
    rows = []
    for offset in range(12):
        month = history.forecast_start + offset
        angle = 2 * np.pi * (month % 12) / 12
        rows.append(
            base
            + [
                (month - int(history.months[-1])) / 12,
                min(len(values), 48) / 48,
                *(
                    float(baselines[name][offset] / scale)
                    for name in ("seasonal_naive", "damped_seasonal", "robust_harmonic")
                ),
                float(np.sin(angle)),
                float(np.cos(angle)),
            ]
        )
    return np.asarray(rows)
