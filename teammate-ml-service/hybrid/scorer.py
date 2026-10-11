"""Final merged financial engine; all original model bytes stay frozen.

The provider supplies real-data revenue quantiles and an observed-total-outflow
projection. Native vendor loan primitives are reused, while the recommendation
is solved against the actual offered schedule rather than an annuity proxy.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from teammate_bridge.loader import load_candidate
from teammate_bridge.schemas import ScoreRequest

ANNUAL_RATE = 0.24
TERM_MONTHS = 12
LEVELS = np.round(np.linspace(0.01, 0.99, 99), 2)
MONEY_TOLERANCE = 1.0  # Native solver's stated tolerance, in explicitly mapped UZS.


class HybridInputError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _month(value) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        if 1 <= year <= 9999 and 1 <= month <= 12:
            return year * 12 + month - 1
    raise ValueError("Provider months must be real YYYY-MM or integer month IDs.")


def month_label(value: int) -> str:
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def _vector(value, length: int, name: str, nonnegative=True) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if (
        result.shape != (length,)
        or not np.isfinite(result).all()
        or (nonnegative and (result < 0).any())
    ):
        raise ValueError(f"Provider {name} must contain aligned finite values.")
    return result


@dataclass
class FinancialForecast:
    months: list[int]
    mode: str
    in_p50: np.ndarray
    out_p50: np.ndarray
    free_p50: np.ndarray
    in_grid: np.ndarray
    free_grid: np.ndarray

    def q(self, level: float) -> np.ndarray:
        return self.free_grid[:, int(np.argmin(np.abs(LEVELS - level)))]

    def coverage(self, payments: np.ndarray) -> float:
        return float(np.mean(self.free_grid >= payments[:, None]))


def validate_forecast(payload: ScoreRequest, supplied: object) -> dict:
    if not isinstance(supplied, dict):
        raise ValueError("Revenue provider returned an invalid object.")
    required = {
        "months",
        "median",
        "revenue_grid",
        "quantile_levels",
        "observed_outflow_projection",
        "history_months",
        "history_inflow",
        "history_outflow",
        "expense_policy",
        "provenance",
    }
    if not required <= set(supplied):
        raise ValueError(
            "Revenue provider omitted required forecast or provenance fields."
        )
    if {"actual", "actuals", "future_targets", "future_revenue"} & set(supplied):
        raise ValueError(
            "Revenue provider must not pass future outcome labels to scoring."
        )
    months = [_month(value) for value in supplied["months"]]
    cutoff = _month(payload.as_of_date[:7])
    if months != list(range(cutoff + 1, cutoff + 13)):
        raise ValueError(
            "Revenue provider forecasts must align with the assessment's following twelve months."
        )
    history = [_month(value) for value in supplied["history_months"]]
    if (
        not history
        or len(history) > 600
        or any(np.diff(history) != 1)
        or history[-1] > cutoff
    ):
        raise ValueError(
            "Revenue provider history must be continuous and end on or before assessment."
        )
    levels = _vector(supplied["quantile_levels"], 99, "quantile levels")
    if not np.array_equal(levels, LEVELS):
        raise ValueError(
            "Revenue provider must use the declared .01–.99 quantile grid."
        )
    median = _vector(supplied["median"], 12, "median revenue")
    grid = np.asarray(supplied["revenue_grid"], dtype=float)
    if (
        grid.shape != (12, 99)
        or not np.isfinite(grid).all()
        or (grid < 0).any()
        or (np.diff(grid, axis=1) < 0).any()
    ):
        raise ValueError(
            "Revenue provider quantiles must be finite, nonnegative and ordered (12, 99)."
        )
    if not np.allclose(grid[:, 49], median, rtol=1e-9, atol=1e-9):
        raise ValueError("Revenue provider's center and 50th quantile must agree.")
    inflow = _vector(supplied["history_inflow"], len(history), "observed inflow")
    outflow = _vector(
        supplied["history_outflow"], len(history), "observed total outflow"
    )
    observed = {month: [0.0, 0.0] for month in history}
    for row in payload.transactions:
        month = _month(row.ts[:7])
        if month in observed:
            observed[month][row.direction == "out"] += row.amount_index
    expected = np.asarray([observed[month] for month in history])
    if not np.allclose(inflow, expected[:, 0], rtol=1e-9, atol=1e-6) or not np.allclose(
        outflow, expected[:, 1], rtol=1e-9, atol=1e-6
    ):
        raise ValueError(
            "Revenue provider history differs from the authenticated request's observed transactions."
        )
    expenses = _vector(
        supplied["observed_outflow_projection"], 12, "observed outflow projection"
    )
    if supplied["expense_policy"] != "observed_cost_projection":
        raise ValueError(
            "Combined scorer requires an observed-total-outflow projection, without synthetic expense labels."
        )
    provenance = supplied["provenance"]
    if not isinstance(provenance, dict) or not {
        "revenue_model_version",
        "real_training_targets",
        "model_artifact_sha256",
        "calibration_sha256",
    } <= set(provenance):
        raise ValueError(
            "Revenue provider must declare frozen model and real calibration identity."
        )
    if (
        type(provenance["real_training_targets"]) is not int
        or provenance["real_training_targets"] < 0
    ):
        raise ValueError("Revenue provider training target count is invalid.")
    for name in ("model_artifact_sha256", "calibration_sha256"):
        if not isinstance(provenance[name], str) or not re.fullmatch(
            r"[0-9a-f]{64}", provenance[name]
        ):
            raise ValueError(
                "Revenue provider artifact identities must be full SHA-256 values."
            )
    return {
        **supplied,
        "months": months,
        "history_months": history,
        "median": median,
        "revenue_grid": grid,
        "history_inflow": inflow,
        "history_outflow": outflow,
        "observed_outflow_projection": expenses,
    }


def persistent_decline(inflow: np.ndarray) -> dict:
    """Predeclared observed-history guard; repeating seasonal dips do not suffice."""
    if len(inflow) < 12:
        return {"triggered": False, "reason": "fewer_than_12_observed_months"}
    if len(inflow) >= 18:
        earlier, recent = inflow[-18:-12], inflow[-6:]
        usable = earlier > 0
        ratios = recent[usable] / earlier[usable]
        median_ratio = float(np.median(ratios)) if len(ratios) else None
        declining_share = float(np.mean(ratios <= 0.9)) if len(ratios) else None
        triggered = len(ratios) >= 5 and median_ratio <= 0.8 and declining_share >= 0.8
        return {
            "triggered": bool(triggered),
            "matched_months": int(len(ratios)),
            "median_year_on_year_ratio": median_ratio,
            "declining_matched_month_share": declining_share,
            "policy": "latest6_matched_year_on_year_min5_positive_prior_months_median_ratio_lte.8_and_share_ratio_lte.9_gte.8",
            "seasonality_adjustment": "same_calendar_months_one_year_earlier",
        }
    window = inflow[-12:]
    mean = float(np.mean(window))
    floor = 0.05 * max(mean, 1.0)
    annual_log_slope = float(
        np.polyfit(np.arange(12), np.log(window + floor), 1)[0] * 12
    )
    declining_share = float(np.mean(np.diff(window) < 0))
    earlier, recent = float(np.mean(window[:3])), float(np.mean(window[-3:]))
    ratio = recent / earlier if earlier > 0 else 1.0
    triggered = annual_log_slope <= -0.35 and declining_share >= 0.8 and ratio <= 0.7
    return {
        "triggered": bool(triggered),
        "annual_log_slope": annual_log_slope,
        "declining_month_share": declining_share,
        "recent_to_earlier_ratio": ratio,
        "policy": "12_to17_month_fallback_log_slope_lte_minus.35_and_declining_share_gte.8_and_recent_first3_ratio_lte.7",
        "seasonality_adjustment": "insufficient_history_for_six_matched_year_on_year_months_strict_monotonic_fallback",
    }


class HybridEngine:
    def __init__(self):
        bundle, artifact_hash, version, manifest, self.snapshot, _, _ = load_candidate()
        from models.schedule import (
            amortize,
            annuity_payment,
            max_feasible_principal,
            present_value,
            solve_adaptive,
        )

        self.amortize = amortize
        self.annuity_payment = annuity_payment
        self.max_feasible_principal = max_feasible_principal
        self.present_value = present_value
        self.solve_adaptive = solve_adaptive
        self.buffer_main, self.buffer_risk = bundle.buffer_k, bundle.buffer_k_risk
        self.identity = {
            "native_model_version": version,
            "model_artifact_sha256": artifact_hash,
            "archive_sha256": manifest["archive_sha256"],
            "bridge_source_sha256": manifest["bridge_source_sha256"],
            "financial_source_hashes": {
                name: hashlib.sha256(
                    Path(__file__).with_name(name).read_bytes()
                ).hexdigest()
                for name in ("scorer.py", "transport.py")
            },
            "buffer_main_synthetic": self.buffer_main,
            "buffer_risk_synthetic": self.buffer_risk,
            "annual_rate": ANNUAL_RATE,
            "term_months": TERM_MONTHS,
        }

    def close(self):
        self.snapshot.cleanup()

    def _rows(
        self, principal: float, payments: np.ndarray, months: list[int]
    ) -> tuple[list[dict], list[dict]]:
        raw = self.amortize(principal, ANNUAL_RATE / 12, payments)
        rounded = np.round(payments, 2)
        # Settle accumulated cent rounding in the final payment; interest is still
        # calculated by the unchanged native amortization equation.
        rounded_rows = self.amortize(principal, ANNUAL_RATE / 12, rounded)
        final_balance = rounded_rows[-1]["balance"]
        if abs(final_balance) < 1:
            # Native amortize masks balances under one UZS; compute the unmasked
            # balance from the original interest/principal rows for cent settlement.
            final_balance = principal - sum(row["principal"] for row in rounded_rows)
        rounded[-1] = round(rounded[-1] + final_balance, 2)
        settled = self.amortize(principal, ANNUAL_RATE / 12, rounded)
        rows = []
        for month, row in zip(months, settled, strict=True):
            payment, interest = round(row["payment"], 2), round(row["interest"], 2)
            rows.append(
                {
                    "month": month_label(month),
                    "payment": payment,
                    "interest": interest,
                    "principal": round(payment - interest, 2),
                    "balance": round(row["balance"], 2),
                }
            )
        return rows, raw

    def _solve_offer(
        self,
        caps: np.ndarray,
        shape: np.ndarray,
        months: list[int],
        adaptive: bool,
        requested: float | None = None,
    ) -> dict:
        rate = ANNUAL_RATE / 12
        pv_budget = float(np.sum(caps / (1 + rate) ** np.arange(1, 13)))
        if adaptive:
            upper = min(self.max_feasible_principal(rate, caps), pv_budget)
        else:
            upper = self.present_value(float(np.min(caps)), rate, 12)
        upper = max(float(upper), 0.0)
        if requested is not None:
            upper = min(upper, requested)
        empty = {
            "principal": 0.0,
            "schedule_type": "adaptive" if adaptive else "annuity",
            "rows": [],
            "native_rows": [],
            "pv_budget": pv_budget,
            "actual_within_capacity": False,
            "caps": caps.tolist(),
        }
        if upper < 0.01:
            return empty

        def solve(principal):
            if adaptive:
                result = self.solve_adaptive(principal, rate, caps, shape=shape)
                if result["status"] != "ok":
                    raise RuntimeError("Native adaptive loan solver failed.")
                payments = np.asarray(result["payments"], dtype=float)
            else:
                payments = np.full(12, self.annuity_payment(principal, rate, 12))
            if (
                payments.shape != (12,)
                or not np.isfinite(payments).all()
                or (payments < 0).any()
            ):
                raise RuntimeError("Native loan solver returned invalid payments.")
            within = (
                np.all(payments <= caps + MONEY_TOLERANCE)
                and float(np.maximum(payments - caps, 0).sum()) <= MONEY_TOLERANCE * 12
            )
            if within:
                settled_rows, _ = self._rows(principal, payments, months)
                settled_payments = np.asarray([row["payment"] for row in settled_rows])
                within = bool(
                    np.all(settled_payments >= 0)
                    and np.all(settled_payments <= caps + MONEY_TOLERANCE)
                )
            return payments, bool(within)

        # Search in the displayed principal's cent units. A final float-to-cent
        # floor can change the native optimum and its cent settlement; retaining
        # an already checked integer-cent candidate prevents that inconsistency.
        upper_cents = int(np.floor(upper * 100))
        payments, within = solve(upper_cents / 100)
        if not within:
            lower_cents = 0
            for _ in range(32):
                if upper_cents - lower_cents <= 1:
                    break
                midpoint_cents = (lower_cents + upper_cents) // 2
                candidate, feasible = solve(midpoint_cents / 100)
                if feasible:
                    lower_cents, payments = midpoint_cents, candidate
                else:
                    upper_cents = midpoint_cents
            upper_cents = lower_cents
        principal = upper_cents / 100
        if principal < 0.01:
            return empty
        rows, raw = self._rows(principal, payments, months)
        settled = np.asarray([row["payment"] for row in rows])
        if np.any(settled > caps + MONEY_TOLERANCE):
            raise RuntimeError("Rounded offered schedule exceeds its declared budget.")
        return {
            **empty,
            "principal": float(principal),
            "rows": rows,
            "native_rows": raw,
            "actual_within_capacity": True,
        }

    def assess(self, supplied: dict, requested: float | None) -> dict:
        inflow = supplied["history_inflow"]
        history_count = len(inflow)
        mode = (
            "no_seasonality"
            if history_count < 12
            else "reduced_seasonality"
            if history_count < 24
            else "full"
        )
        expenses = supplied["observed_outflow_projection"]
        forecast = FinancialForecast(
            supplied["months"],
            mode,
            supplied["median"],
            expenses,
            supplied["median"] - expenses,
            supplied["revenue_grid"],
            supplied["revenue_grid"] - expenses[:, None],
        )
        shape = np.maximum(forecast.free_p50, 0)
        caps = {
            "p10": self.buffer_main * np.maximum(forecast.q(0.10), 0),
            "p20": (self.buffer_risk or self.buffer_main)
            * np.maximum(forecast.q(0.20), 0),
            "p50": self.buffer_main * shape,
        }
        adaptive = history_count >= 12
        tiers = {
            name: self._solve_offer(budget, shape, forecast.months, adaptive)
            for name, budget in caps.items()
        }
        decline_guard = persistent_decline(inflow)
        median_viability = {
            "mean_surplus": float(np.mean(forecast.free_p50)),
            "nonpositive_months": int(np.count_nonzero(forecast.free_p50 <= 0)),
            "policy": "decline_if_nonpositive_mean_surplus_or_at_least6_nonpositive_median_months",
        }
        median_viability["triggered"] = (
            median_viability["mean_surplus"] <= 0
            or median_viability["nonpositive_months"] >= 6
        )
        reason = None
        if history_count < 6:
            tier, verdict, reason = None, "decline", "insufficient_observed_history"
        elif decline_guard["triggered"]:
            tier, verdict, reason = (
                None,
                "decline",
                "strong_persistent_observed_decline",
            )
        elif tiers["p50"]["principal"] <= 0:
            tier, verdict, reason = (
                None,
                "decline",
                "no_actual_median_schedule_capacity",
            )
        elif median_viability["triggered"]:
            tier, verdict, reason = (
                None,
                "decline",
                "nonpositive_median_cashflow_viability",
            )
        elif tiers["p10"]["principal"] > 0:
            tier, verdict = "p10", "affordable"
        elif tiers["p20"]["principal"] > 0:
            tier, verdict = "p20", "elevatedrisk_officer"
        else:
            tier, verdict = "p50", "elevatedrisk_officer"
        requested_exceeds = False
        selected = {
            "principal": 0.0,
            "rows": [],
            "native_rows": [],
            "caps": [0.0] * 12,
            "schedule_type": "adaptive" if adaptive else "annuity",
            "actual_within_capacity": False,
            "pv_budget": 0.0,
        }
        if tier is not None:
            selected = tiers[tier]
            if requested is not None and requested > 0:
                requested_exceeds = requested > selected["principal"] + 0.01
                if not requested_exceeds:
                    selected = self._solve_offer(
                        caps[tier], shape, forecast.months, adaptive, requested
                    )
        principal = selected["principal"]
        if requested is None or requested == 0:
            requested_fit_status = "unspecified"
        elif principal <= 0:
            requested_exceeds = True
            requested_fit_status = "declined_by_guard"
        elif requested_exceeds:
            requested_fit_status = "exceeds_selected_capacity"
        else:
            requested_fit_status = "fits_selected_offer"
        payments = (
            np.asarray([row["payment"] for row in selected["rows"]])
            if principal > 0
            else np.zeros(12)
        )
        score = round(forecast.coverage(payments) * 100, 1) if principal > 0 else 0.0
        history_factor = (
            0.45 if history_count < 12 else 0.7 if history_count < 24 else 1.0
        )
        width = float(np.mean(forecast.q(0.9) - forecast.q(0.1)))
        relative_width = width / max(float(np.mean(forecast.in_p50)), 1.0)
        confidence = round(
            history_factor * float(np.clip(1 - 0.8 * relative_width, 0.2, 1)), 3
        )
        annuity_rows = []
        comparison = None
        if principal > 0:
            equal = np.full(12, self.annuity_payment(principal, ANNUAL_RATE / 12, 12))
            annuity_rows, annuity_raw = self._rows(principal, equal, forecast.months)
            annuity_payments = np.asarray([row["payment"] for row in annuity_rows])
            budget = np.asarray(selected["caps"])
            comparison = {
                "same_principal": principal,
                "same_annual_rate": ANNUAL_RATE,
                "same_term_months": 12,
                "annuity_overload_months": int(
                    np.count_nonzero(annuity_payments > budget + MONEY_TOLERANCE)
                ),
                "offered_overload_months": int(
                    np.count_nonzero(payments > budget + MONEY_TOLERANCE)
                ),
                "annuity_total_interest": round(
                    float(np.sum(annuity_payments)) - principal, 2
                ),
                "offered_total_interest": round(float(np.sum(payments)) - principal, 2),
                "annuity_rows": annuity_rows,
                "native_annuity_rows": annuity_raw,
            }
        return {
            "verdict": verdict,
            "decline_reason": reason,
            "tier": tier,
            "offered": selected,
            "tiers": tiers,
            "score": score,
            "confidence": confidence,
            "relative_interval_width": relative_width,
            "decline_guard": decline_guard,
            "median_viability_guard": median_viability,
            "requested_exceeds": requested_exceeds,
            "requested_amount": requested,
            "requested_fit_status": requested_fit_status,
            "requested_zero_unspecified": requested == 0,
            "comparison": comparison,
            "history_mode": mode,
            "median_surplus": forecast.free_p50.tolist(),
            "free_quantile_grid_conditional_on_observed_cost": forecast.free_grid.tolist(),
        }


def assess_request(payload, provider, request_id: str, *, engine: HybridEngine) -> dict:
    from .transport import build_response

    original_payload = payload
    if not isinstance(payload, ScoreRequest):
        try:
            payload = ScoreRequest.model_validate(
                payload.model_dump() if hasattr(payload, "model_dump") else payload
            )
        except ValidationError as error:
            raise HybridInputError(
                "invalid_assessment_input",
                "Assessment input does not satisfy the authenticated transaction contract.",
            ) from error
    supplied = validate_forecast(payload, provider(original_payload))
    assessment = engine.assess(supplied, payload.requested_amount)
    result = build_response(payload, supplied, assessment, request_id, engine.identity)
    evidence = {
        "financial_engine_identity": engine.identity,
        "revenue_provider_identity": supplied["provenance"],
        "revenue_forecast": {
            "months": [month_label(month) for month in supplied["months"]],
            "median": supplied["median"].tolist(),
            "quantile_levels": LEVELS.tolist(),
            "grid": supplied["revenue_grid"].tolist(),
        },
        "observed_total_outflow_projection": supplied[
            "observed_outflow_projection"
        ].tolist(),
        "separate_debt": "unavailable_already_in_observed_total_outflow_no_additional_deduction",
        "assessment": assessment,
        "scope": "Revenue intervals calibrated on real development aggregates only. Conditional surplus, buffer policy, capacity and repayment safety have no real borrower validation.",
    }
    json.dumps(evidence, allow_nan=False)
    return {"result": result, "evidence": evidence}


def score_request(payload, provider, request_id: str, *, engine: HybridEngine) -> dict:
    return assess_request(payload, provider, request_id, engine=engine)["result"]
