"""Scale-free revenue features and bounded, observation-only forecast baselines.

No expense or repayment values are inferred from public revenue histories.
"""

import numpy as np

from .forecasting import MonthlyHistory, normalizer, seasonal_forecast

REVENUE_FEATURE_NAMES = (
    *(f"target_prior_year_offset_{offset}" for offset in range(-3, 4)),
    "target_two_years_ago",
    "target_three_years_ago",
    "mean_3",
    "mean_6",
    "std_12",
    "annual_log_growth",
    "horizon",
    "history_length",
    "recent_level_change",
    "seasonal_naive",
    "damped_seasonal",
    "robust_harmonic",
    "linear_harmonic",
    "flat_harmonic",
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
    # Raw-value robust harmonics preserve a borrower's own seasonal phase and
    # allow a second annual harmonic. They are observation-based baselines;
    # the public-data residual estimators below learn their corrections.
    linear = np.full(12, float(np.mean(values[-12:])))
    flat = linear.copy()
    if len(values) >= 18:
        observed_months = history.months[-36:]
        observed = values[-36:]
        anchor = int(observed_months[-1])
        positions = (observed_months - anchor) / 12
        angles = 2 * np.pi * (observed_months % 12) / 12
        design = np.column_stack(
            [
                np.ones(len(observed)),
                positions,
                np.sin(angles),
                np.cos(angles),
                np.sin(2 * angles),
                np.cos(2 * angles),
            ]
        )
        future = np.arange(history.forecast_start, history.forecast_start + 12)
        future_angles = 2 * np.pi * (future % 12) / 12
        future_design = np.column_stack(
            [
                np.ones(12),
                (future - anchor) / 12,
                np.sin(future_angles),
                np.cos(future_angles),
                np.sin(2 * future_angles),
                np.cos(2 * future_angles),
            ]
        )
        weights = np.ones(len(observed))
        coefficients = np.zeros(6)
        for _ in range(3):
            weighted = design * weights[:, None]
            coefficients = np.linalg.solve(
                design.T @ weighted + np.diag([0, 2, 0.5, 0.5, 1, 1]),
                weighted.T @ observed,
            )
            weights = 1 / (1 + ((observed - design @ coefficients) / 0.25) ** 2)
        coefficients[1] = np.clip(coefficients[1], -0.7, 0.7)
        linear = np.maximum(future_design @ coefficients, 0)
        coefficients[1] = 0
        flat = np.maximum(future_design @ coefficients, 0)
    return {
        "seasonal_naive": naive * scale,
        "damped_seasonal": damped * scale,
        "robust_harmonic": harmonic * scale,
        "linear_harmonic": linear * scale,
        "flat_harmonic": flat * scale,
    }


def revenue_feature_matrix(
    history: MonthlyHistory, baselines: dict[str, np.ndarray] | None = None
) -> np.ndarray:
    """Target-relative seasonal features; no country or absolute calendar phase.

    Shifting every observed/target month by the same number leaves features
    unchanged. A Christmas sales peak cannot become a global December prior.
    """
    scale = normalizer(history)
    values = np.asarray(history.inflow, dtype=float) / scale
    mean = float(np.mean(values[-12:]))
    prior = float(np.mean(values[-24:-12])) if len(values) >= 24 else mean
    annual_growth = float(np.log(max(mean, 0.05) / max(prior, 0.05)))
    baselines = revenue_baselines(history) if baselines is None else baselines
    mean_three = float(np.mean(values[-3:]))
    mean_six = float(np.mean(values[-6:]))
    volatility = float(np.std(values[-12:]))
    level_change = (
        float(mean_three - np.mean(values[-6:-3])) if len(values) >= 6 else 0.0
    )

    def observed(month: int) -> float:
        index = month - int(history.months[0])
        return float(values[index]) if 0 <= index < len(values) else mean

    rows = []
    for offset in range(12):
        target = history.forecast_start + offset
        prior_year = target - 12
        while prior_year > int(history.months[-1]):
            prior_year -= 12
        rows.append(
            [
                *(observed(prior_year + position) for position in range(-3, 4)),
                observed(prior_year - 12),
                observed(prior_year - 24),
                mean_three,
                mean_six,
                volatility,
                annual_growth,
                (target - int(history.months[-1])) / 12,
                min(len(values), 60) / 60,
                level_change,
                *(
                    float(baselines[name][offset] / scale)
                    for name in (
                        "seasonal_naive",
                        "damped_seasonal",
                        "robust_harmonic",
                        "linear_harmonic",
                        "flat_harmonic",
                    )
                ),
            ]
        )
    return np.asarray(rows)
