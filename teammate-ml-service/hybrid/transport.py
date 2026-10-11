"""Validated shared transport for the final merged financial assessment."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from teammate_bridge.schemas import ScoreResponse

from .scorer import ANNUAL_RATE


def build_response(
    payload, forecast: dict, assessment: dict, request_id: str, engine_identity: dict
) -> dict:
    incoming = forecast["history_inflow"][-12:]
    outgoing = forecast["history_outflow"][-12:]
    mean = float(np.mean(incoming))
    volatility = float(np.std(incoming) / mean) if mean > 0 else 0.0
    trend = (
        float(
            np.polyfit(
                np.arange(len(incoming)), np.log(incoming + 0.05 * max(mean, 1.0)), 1
            )[0]
            * 12
        )
        if len(incoming) >= 4
        else 0.0
    )
    offered = assessment["offered"]
    principal = offered["principal"]
    rows = offered["rows"]
    total = round(sum(row["payment"] for row in rows), 2)
    interest = round(total - principal, 2)
    if interest < 0:
        raise ValueError("Combined repayments do not cover principal.")
    annuity = (
        float(assessment["comparison"]["annuity_rows"][0]["payment"]) if rows else 0.0
    )
    surplus = np.asarray(assessment["median_surplus"])
    q25, q75 = np.quantile(surplus, [0.25, 0.75])
    verdict = assessment["verdict"]
    phrases = {
        "affordable": "Прогноз поддерживает предложенный сезонный график на консервативном уровне P10; окончательное решение принимает кредитный офицер.",
        "elevatedrisk_officer": "Повышенная неопределённость: предложенный график опирается на P20 или медианный поток; требуется отдельная оценка кредитного офицера.",
        "decline": "Основная рекомендация равна нулю из-за наблюдаемого устойчивого падения, недостаточной истории или отсутствия посильного медианного графика; итоговое решение фиксирует кредитный офицер.",
    }
    flags = [
        "final_combined_model",
        "annual_rate_24_percent",
        "human_review_required",
        f"hybrid_verdict_{verdict}",
        "verdict_elevated_risk"
        if verdict == "elevatedrisk_officer"
        else f"verdict_{verdict}",
        f"history_mode_{assessment['history_mode']}",
        "real_revenue_intervals_only",
        "conditional_surplus_not_calibrated",
        "synthetic_buffer_policy_unvalidated_on_real_borrowers",
        "capacity_not_default_probability",
        "observed_total_outflow_includes_unclassified_debt",
        "category_unavailable",
        "counterparty_unavailable",
        "amount_index_1_to_1_uzs",
        "offered_schedule_capacity_checked",
    ]
    if assessment["tier"]:
        flags.append(f"offered_capacity_tier_{assessment['tier']}")
    if assessment["decline_reason"]:
        flags.append(assessment["decline_reason"])
    if assessment["decline_guard"]["triggered"]:
        flags.append("sustained_decline_guard")
    if assessment["requested_exceeds"]:
        flags.append("requested_amount_exceeds_offered_capacity")
    flags.append(f"requested_fit_{assessment['requested_fit_status']}")
    if assessment["requested_zero_unspecified"]:
        flags.append("requested_amount_zero_treated_as_unspecified")
    if offered["schedule_type"] == "annuity":
        flags.append("short_history_annuity_fallback")
    provenance = forecast["provenance"]
    below_calibration = (
        provenance.get("uncertainty_support") == "below_calibration_minimum_3_months"
    )
    if below_calibration:
        flags.append("below_calibration_minimum_3_months")
    short_history_fallback = (
        provenance.get("effective_revenue_component") == "current"
        and provenance.get("short_history_fallback")
        == "incumbent_below_upgrade_minimum_3_months"
    )
    if short_history_fallback:
        flags.append("short_history_incumbent_revenue_fallback")
    identity_hash = hashlib.sha256(
        json.dumps(
            {"engine": engine_identity, "provider": provenance},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    advisory = [
        phrases[verdict],
        "Capacity score measures modeled coverage of the actual offered monthly payments. A zero offered loan has score zero. It is not default probability or an automatic credit decision.",
        "Annual nominal interest is 24% (2% per month), term 12 months. Offered repayments include genuine interest and principal amortization; capacity is checked against this actual schedule.",
        "Revenue intervals use real aggregate development residual calibration. Expense, net-flow and borrower repayment outcomes were not observed in those datasets; revenue interval coverage does not validate net-flow or payment safety.",
        "Future costs are a projection of observed total outflows. Existing debt already present in those outflows is included without a second deduction. Categories, separate debt obligations, counterparties and own transfers remain unidentified.",
        "The inherited payment buffers were originally calibrated on synthetic data. Their use here is an explicit policy, with no promised 90% or 80% real-borrower payment coverage.",
        "Automatic recommendations below 5% of the chosen tier's discounted payment budget are immaterial and rejected before trying the next tier. A smaller positive requested amount can still fit an already selected material capacity; a zero request is unspecified.",
        "Wide intervals alone do not cause decline when a feasible material median offer exists: such an offer is marked elevated risk for an officer. Strong persistent observed decline and infeasible median cash flow suppress the main offer.",
        "Confidence is a history/interval evidence indicator, not a calibrated borrower probability. Monetary units are explicit: 1 amount_index = 1 UZS.",
    ]
    if assessment["requested_exceeds"]:
        advisory.append(
            "Requested principal exceeds the actual chosen schedule's capacity; the displayed amount and schedule use the computed recommendation."
        )
    if below_calibration:
        advisory.append(
            "Observed history has fewer than three months, below the minimum history support of the development revenue calibration. The displayed intervals have no measured coverage for this history length; the financial recommendation remains zero because fewer than six observed months are available."
        )
    if short_history_fallback:
        advisory.append(
            "The selected revenue upgrade requires at least three observed months; this request uses the frozen incumbent revenue component instead. The audit records the effective component and its artifact identity."
        )
    if assessment["tier"] == "p50":
        advisory.append(
            "P10/P20 cannot support a material offer; the amount uses buffered median cash flow and requires explicit elevated-risk human review."
        )
    score = assessment["score"]
    return ScoreResponse.model_validate(
        {
            "business_id": payload.business_id,
            "as_of_date": payload.as_of_date,
            "capacity_score": score,
            "score_band": "high" if score >= 70 else "medium" if score >= 40 else "low",
            "cashflow_summary": {
                "avg_monthly_inflow_index": mean,
                "inflow_volatility": volatility,
                "net_monthly_surplus_index": float(np.mean(incoming - outgoing)),
                "trend": "growing"
                if trend > 0.05
                else "declining"
                if trend < -0.05
                else "stable",
            },
            "recommended_loan": {
                "max_affordable_installment_index": max(
                    (row["payment"] for row in rows), default=0.0
                ),
                "suggested_principal_index": principal,
                "suggested_term_months": 12,
                "rationale": phrases[verdict]
                + f" Principal {principal:,.2f} UZS; 24% annual interest, 12 months; tier {assessment['tier'] or 'none'}.",
            },
            "seasonality": {
                "monthly_forecast_index": surplus.tolist(),
                "weak_months": [
                    month % 12 + 1
                    for month, value in zip(forecast["months"], surplus, strict=True)
                    if value < q25
                ],
                "strong_months": [
                    month % 12 + 1
                    for month, value in zip(forecast["months"], surplus, strict=True)
                    if value > q75
                ],
            },
            "adaptive_schedule": [
                {
                    "month_offset": index + 1,
                    "installment_index": row["payment"],
                    "note": "reduced"
                    if row["payment"] < annuity * 0.98
                    else "increased"
                    if row["payment"] > annuity * 1.02
                    else "normal",
                }
                for index, row in enumerate(rows)
            ],
            "explanation": {
                "top_factors": [
                    {
                        "factor": "Modeled coverage of the actual offered schedule (score points)",
                        "impact": "positive" if principal > 0 else "negative",
                        "weight": score,
                    }
                ],
                "advisory": advisory,
            },
            "confidence": assessment["confidence"],
            "forecast_provenance": {
                "real_revenue_weight": 1.0,
                "synthetic_net_weight": 0.0,
                "expense_mode": "observed_cost_projection",
                "revenue_candidate": provenance["revenue_model_version"],
                "real_training_targets": provenance["real_training_targets"],
            },
            "flags": flags,
            "model_version": f"hybrid-v1-{identity_hash[:24]}",
            "request_id": request_id,
            "loan_terms": {
                "annual_rate": ANNUAL_RATE,
                "schedule_type": offered["schedule_type"],
                "total_interest_index": interest,
                "total_repayment_index": total,
                "requested_amount_policy": "capacity_checked",
            },
        }
    ).model_dump(mode="json")
