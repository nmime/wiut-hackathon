"""Transparent capacity calculation, not a trained default/approval predictor."""

from uuid import uuid4

import numpy as np

from .forecasting import ForecastModel, MonthlyHistory, aggregate, normalizer
from .schemas import ScoreRequest, ScoreResponse

TERM_MONTHS = 12
INTEREST_RATE = 0.0  # Explicit hackathon policy; equal-payment comparator is identical.
UTILIZATION = 0.85


def history_statistics(history: MonthlyHistory) -> dict:
    incoming = history.inflow
    mean_in = float(np.mean(incoming))
    volatility = float(np.std(incoming) / mean_in) if mean_in > 0 else 0.0
    window = history.net[-12:]
    slope = (
        float(np.polyfit(np.arange(len(window)), window, 1)[0])
        if len(window) > 1
        else 0.0
    )
    scale = mean_in if mean_in > 0 else normalizer(history)
    relative_trend = slope / scale
    inflow_window = incoming[-12:]
    inflow_slope = (
        float(np.polyfit(np.arange(len(inflow_window)), inflow_window, 1)[0])
        if len(inflow_window) > 1
        else 0.0
    )
    relative_inflow_trend = inflow_slope / scale
    trend = (
        "growing"
        if relative_inflow_trend > 0.007
        else "declining"
        if relative_inflow_trend < -0.007
        else "stable"
    )
    return {
        "mean_in": mean_in,
        "cv": volatility,
        "surplus": float(np.mean(history.net)),
        "relative_trend": relative_trend,
        "trend": trend,
        "regularity": float(np.mean(incoming > 0)),
    }


def capacity_plan(history: MonthlyHistory, forecast: np.ndarray) -> dict:
    statistics = history_statistics(history)
    active_months = history.inflow + history.outflow > 0
    count = int(np.count_nonzero(active_months))
    active_positions = np.flatnonzero(active_months)
    activity_gap = (
        len(active_months) - 1 - int(active_positions[-1])
        if len(active_positions)
        else len(active_months)
    )
    recent_activity = float(np.mean(active_months[-12:]))
    confidence = (
        min(count / 36, 1.0)
        / (1 + statistics["cv"])
        * recent_activity
        * np.exp(-activity_gap / 6)
    )
    if count < 12:
        confidence = min(confidence, 0.25)
    if history.partial_only:
        confidence = min(confidence, 0.03)
    recent = history.inflow[-3:]
    prior = history.inflow[-6:-3]
    structural_change = (
        len(prior) == 3
        and np.mean(prior) > 0
        and not 0.65 <= np.mean(recent) / np.mean(prior) <= 1.55
    )
    if structural_change:
        confidence *= 0.6
    # Heuristic evidence indicator, not a calibrated probabilistic interval.
    buffer = 0.55 / (1 + min(statistics["cv"], 2)) * (0.5 + 0.5 * confidence)
    capacities = np.maximum(forecast, 0) * buffer
    flags = ["synthetic_training_only", "uncalibrated_confidence", "zero_interest_mvp"]
    if count < 12:
        flags.append("short_history")
    if count < 6 or history.partial_only:
        flags.append("cold_start_no_loan")
    if statistics["cv"] > 0.5:
        flags.append("high_volatility")
    if structural_change:
        flags.append("possible_pattern_break")
    if history.partial_month_excluded:
        flags.append("partial_month_excluded")
    if history.partial_only:
        flags.append("partial_history_only")
    if activity_gap >= 3:
        flags.append("stale_history_no_loan")
    if recent_activity < 0.75:
        flags.append("missing_activity_months")
    if statistics["surplus"] <= 0:
        flags.append("nonpositive_historical_surplus")
    if np.any(forecast <= 0):
        flags.append("nonpositive_forecast_months")
    viable = (
        count >= 6
        and not history.partial_only
        and statistics["surplus"] > 0
        and statistics["mean_in"] > 0
        and activity_gap < 3
    )
    payments = capacities * UTILIZATION if viable else np.zeros(12)
    principal = float(np.sum(payments))
    equal_installment = float(np.quantile(capacities, 0.2)) if viable else 0.0
    components = [
        (
            "Forecast surplus margin (35%)",
            0.35,
            float(np.clip(np.median(forecast) / normalizer(history) / 0.5, 0, 1)),
        ),
        ("Inflow stability (20%)", 0.2, 1 / (1 + 2 * statistics["cv"])),
        ("Positive forecast months (20%)", 0.2, float(np.mean(forecast > 0))),
        (
            "Observed surplus trend (10%)",
            0.1,
            float(np.clip(0.5 + 12 * statistics["relative_trend"], 0, 1)),
        ),
        ("Months with inflow (15%)", 0.15, statistics["regularity"]),
    ]
    factors = []
    raw_score = 50.0
    for label, weight, value in components:
        contribution = 100 * weight * (value - 0.5)
        raw_score += contribution
        factors.append(
            {
                "factor": label,
                "impact": "positive" if contribution >= 0 else "negative",
                "weight": float(contribution),
            }
        )
    support = float(np.mean(forecast > 0)) if viable else 0.0
    deduction = -raw_score * (1 - support)
    factors.append(
        {
            "factor": "Loan viability/evidence gate (score-point adjustment)",
            "impact": "negative" if deduction < 0 else "positive",
            "weight": float(deduction),
        }
    )
    score = float(np.clip(raw_score + deduction, 0, 100))
    return {
        "statistics": statistics,
        "confidence": float(confidence),
        "buffer": float(buffer),
        "capacities": capacities,
        "payments": payments,
        "principal": principal,
        "equal_installment": equal_installment,
        "score": score,
        "factors": factors,
        "flags": flags,
    }


def score_request(
    request: ScoreRequest, model: ForecastModel, request_id: str | None = None
) -> ScoreResponse:
    history = aggregate(request)
    forecast = model.predict(history)
    if forecast.shape != (12,) or not np.all(np.isfinite(forecast)):
        raise ValueError("Local forecast is malformed/nonfinite")
    plan = capacity_plan(history, forecast)
    stats = plan["statistics"]
    q25, q75 = np.quantile(forecast, [0.25, 0.75])
    calendar_months = [(history.forecast_start + i) % 12 + 1 for i in range(12)]
    weak = [
        month
        for month, value in zip(calendar_months, forecast, strict=True)
        if value < q25
    ]
    strong = [
        month
        for month, value in zip(calendar_months, forecast, strict=True)
        if value > q75
    ]
    average_payment = plan["principal"] / TERM_MONTHS
    schedule = []
    if plan["principal"] > 0:
        for offset, payment in enumerate(plan["payments"], 1):
            note = (
                "reduced"
                if payment < 0.85 * average_payment
                else "increased"
                if payment > 1.15 * average_payment
                else "normal"
            )
            schedule.append(
                {
                    "month_offset": offset,
                    "installment_index": float(payment),
                    "note": note,
                }
            )
    advisory = [
        "A human officer must review this recommendation; the score is payment capacity, not default probability.",
        "Confidence is an evidence heuristic, not a calibrated probability or guarantee.",
        "Factor weights are signed score-point contributions around a baseline of 50; the viability gate adjusts the final score.",
    ]
    if "short_history" in plan["flags"]:
        advisory.append(
            "Provide at least 12 complete months to observe one seasonal cycle; fewer than 6 yield no loan recommendation."
        )
    if "high_volatility" in plan["flags"]:
        advisory.append(
            "Volatile inflows reduce the buffer and confidence; verify recurring expenses and reserve liquidity."
        )
    if "possible_pattern_break" in plan["flags"]:
        advisory.append(
            "Recent inflows differ materially from previous months; confirm whether the operating pattern changed."
        )
    if history.partial_month_excluded:
        advisory.append(
            "The incomplete assessment month is excluded from features; forecast still starts next calendar month."
        )
    if history.partial_only:
        advisory.append(
            "Only a partial current month is available. It is retained for a low-confidence illustrative forecast; no loan is recommended."
        )
    if request.requested_amount is not None:
        plan["flags"].append("currency_conversion_missing")
        advisory.append(
            "Requested amount is UZS, but cash flows and this recommendation are indices. No conversion is declared; the requested amount cannot cap this indexed principal."
        )
    rationale = (
        f"12-month schedule, explicitly 0% interest for this MVP: total payments equal indexed principal. "
        f"Each payment uses {100 * UTILIZATION:.0f}% of positive forecast surplus multiplied by a {100 * plan['buffer']:.1f}% buffer. "
        "The displayed maximum installment is the 20th percentile of buffered month capacities for an equal-payment reference; adaptive months have separate caps. "
        "All amounts are indices; no UZS conversion is declared."
    )
    if plan["principal"] == 0:
        rationale += (
            " Evidence or surplus is insufficient for a positive loan recommendation."
        )
    return ScoreResponse(
        business_id=request.business_id,
        as_of_date=request.as_of_date,
        capacity_score=plan["score"],
        score_band="high"
        if plan["score"] >= 70
        else "medium"
        if plan["score"] >= 35
        else "low",
        cashflow_summary={
            "avg_monthly_inflow_index": stats["mean_in"],
            "inflow_volatility": stats["cv"],
            "net_monthly_surplus_index": stats["surplus"],
            "trend": stats["trend"],
        },
        recommended_loan={
            "max_affordable_installment_index": plan["equal_installment"],
            "suggested_principal_index": plan["principal"],
            "suggested_term_months": TERM_MONTHS,
            "rationale": rationale,
        },
        seasonality={
            "monthly_forecast_index": forecast.tolist(),
            "weak_months": weak,
            "strong_months": strong,
        },
        adaptive_schedule=schedule,
        explanation={"top_factors": plan["factors"], "advisory": advisory},
        confidence=plan["confidence"],
        flags=plan["flags"],
        model_version=model.version,
        request_id=request_id or str(uuid4()),
    )
