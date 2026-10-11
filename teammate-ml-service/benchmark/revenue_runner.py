"""Frozen teammate inflow forecasts for revenue-only research cases.

Input is a JSON list of {id, months, inflow, forecast_start}; it contains observed
history only. Months accept YYYY-MM or the native year * 12 + month - 1 integer.
This bypasses transaction ingestion without inventing unavailable financial or
channel labels. It is a separate benchmark, never a borrower assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Also permit the documented direct-file CLI from outside this service directory.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from teammate_bridge.loader import load_candidate  # noqa: E402

SCHEMA_VERSION = "teammate-revenue-benchmark-v1"
NORMALIZED_HISTORY_MEAN = 100.0
MIN_FORECAST_START = 2020 * 12
MAX_FORECAST_START = 2029 * 12
HORIZON = 12
MAX_HISTORY_MONTHS = 600
CASE_FIELDS = {"id", "months", "inflow", "forecast_start"}
UNKNOWN_PROFILE_COLUMNS = (
    "inflow_card",
    "inflow_qr",
    "inflow_transfer",
    "inflow_cash_other",
    "outflow_total",
    "outflow_fixed",
    "outflow_debt",
    "outflow_operating",
    "net_flow",
    "n_in_txn",
    "active_days",
    "unique_payers",
    "top_payer_share",
)
SOURCE_LIMITATIONS = [
    "Inputs are public monthly revenue aggregates, not borrower transactions. Source provenance and original units must be supplied by the calling benchmark.",
    "The frozen candidate was trained on synthetic businesses. This benchmark measures revenue transfer only; it does not validate expenses, payment capacity, repayment or default.",
    "Operating outflow, fixed costs, debt, payment channels, transaction activity, counterparties and industry are unavailable. Missing profile metrics are NaN and no industry prior is selected.",
    "Only the frozen native inflow branch executes and returns P50/P10/P90. Operating outflow, free cash flow and capacity are neither computed nor measured by this benchmark.",
    "Primary predictions normalize the latest up to 12 observed history months' mean to 100 and rescale to the caller's original units. No currency conversion is implied. The vendor's additive constants make this transform a declared benchmark policy, not exact scale invariance.",
    "Optional unnormalized native-unit predictions are sensitivity diagnostics only. They do not select the primary transform or contribute a second accuracy claim.",
    "The frozen Ramadan calendar covers 2018–2029. Forecasts start in January 2020–January 2029 so every target and its two-year calendar lookback stay within that range.",
    "Native inflow intervals were calibrated on synthetic data and are not guaranteed to have nominal coverage on these public revenue observations.",
    "predictions.median preserves the native in_p50 point center. predictions.conformal_median is the residual-adjusted 50th quantile; a biased conformal interval need not contain the native point center.",
]


class CaseRefusal(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def month_index(value: object) -> int:
    if type(value) is int:
        index = value
        year, _ = divmod(index, 12)
        if not 1 <= year <= 9999:
            raise CaseRefusal(
                "invalid_month", "Native month IDs must have years 1–9999."
            )
        return index
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        if 1 <= year <= 9999 and 1 <= month <= 12:
            return year * 12 + month - 1
    raise CaseRefusal(
        "invalid_month", "Months must be YYYY-MM or integer native month IDs."
    )


def month_label(index: int) -> str:
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}"


def validate_case(case: object) -> tuple[str, list[int], np.ndarray, int, float]:
    if not isinstance(case, dict) or set(case) != CASE_FIELDS:
        raise CaseRefusal(
            "invalid_case_fields",
            "Each case must contain only id, months, inflow and forecast_start; future labels and auxiliary financial fields are forbidden.",
        )
    identity = case["id"]
    if not isinstance(identity, str) or not identity.strip():
        raise CaseRefusal("invalid_id", "Case id must be a nonempty string.")
    months, inflow = case["months"], case["inflow"]
    if not isinstance(months, list) or not isinstance(inflow, list):
        raise CaseRefusal("invalid_history", "months and inflow must be lists.")
    if len(months) != len(inflow):
        raise CaseRefusal(
            "invalid_history", "months and inflow must have equal lengths."
        )
    if len(months) < 6:
        raise CaseRefusal(
            "insufficient_history", "At least six observed history months are required."
        )
    if len(months) > MAX_HISTORY_MONTHS:
        raise CaseRefusal(
            "history_limit", "History is limited to 600 monthly observations."
        )
    indices = [month_index(month) for month in months]
    if any(
        right != left + 1 for left, right in zip(indices, indices[1:], strict=False)
    ):
        raise CaseRefusal(
            "noncontiguous_history",
            "History months must be sorted, unique and contiguous; missing months are not imputed.",
        )
    start = month_index(case["forecast_start"])
    if start != indices[-1] + 1:
        raise CaseRefusal(
            "misaligned_forecast",
            "forecast_start must be exactly the month after the final history month.",
        )
    if not MIN_FORECAST_START <= start <= MAX_FORECAST_START:
        raise CaseRefusal(
            "unsupported_calendar",
            "forecast_start must be January 2020–January 2029 to preserve the frozen 12-month calendar and two-year lookback.",
        )
    values = []
    for value in inflow:
        if type(value) not in (int, float):
            raise CaseRefusal(
                "invalid_inflow",
                "Revenue observations must be finite nonnegative numbers.",
            )
        try:
            number = float(value)
        except (OverflowError, ValueError) as error:
            raise CaseRefusal(
                "invalid_inflow",
                "Revenue observations must be finite nonnegative numbers.",
            ) from error
        if not math.isfinite(number) or number < 0:
            raise CaseRefusal(
                "invalid_inflow",
                "Revenue observations must be finite nonnegative numbers.",
            )
        values.append(number)
    # Dividing before summing avoids overflow for large but finite observations.
    try:
        window = values[-12:]
        mean = math.fsum(value / len(window) for value in window)
    except OverflowError as error:
        raise CaseRefusal("invalid_inflow", "History mean must be finite.") from error
    if not math.isfinite(mean) or mean <= 0:
        raise CaseRefusal(
            "no_positive_revenue",
            "A finite positive mean of the latest up to 12 observed revenue months is required.",
        )
    if mean / NORMALIZED_HISTORY_MEAN <= 0:
        raise CaseRefusal(
            "invalid_normalization",
            "History values are too small for the declared normalization.",
        )
    return identity, indices, np.asarray(values, dtype=float), start, mean


def build_profile(identity: str, months: list[int], inflow: np.ndarray) -> pd.DataFrame:
    """Keep every unsupported metric unknown; no fabricated channel allocations."""
    profile = pd.DataFrame(
        {
            "business_id": identity,
            "month": [month_label(month) for month in months],
            "month_idx": months,
            "inflow_total": inflow,
        }
    )
    for column in UNKNOWN_PROFILE_COLUMNS:
        profile[column] = np.nan
    return profile


def inflow_predictions(forecast, scale: float) -> dict:
    arrays = {
        "median": np.asarray(forecast.in_p50, dtype=float) * scale,
        "p10": np.asarray(forecast.q(0.1, "in"), dtype=float) * scale,
        "p90": np.asarray(forecast.q(0.9, "in"), dtype=float) * scale,
        "conformal_median": np.asarray(forecast.q(0.5, "in"), dtype=float) * scale,
    }
    if any(
        value.shape != (HORIZON,) or not np.isfinite(value).all() or (value < 0).any()
        for value in arrays.values()
    ):
        raise ValueError(
            "Native inflow forecasts must be 12 finite nonnegative values."
        )
    if (arrays["p10"] > arrays["conformal_median"]).any() or (
        arrays["conformal_median"] > arrays["p90"]
    ).any():
        raise ValueError(
            "Native inflow quantiles must satisfy P10 <= conformal P50 <= P90."
        )
    return {name: value.tolist() for name, value in arrays.items()}


@dataclass
class InflowForecast:
    months: list[int]
    mode: str
    in_p50: np.ndarray
    in_grid: np.ndarray
    levels: np.ndarray

    def q(self, level: float, which: str) -> np.ndarray:
        if which != "in":
            raise ValueError("Revenue benchmark provides only inflow quantiles.")
        return self.in_grid[:, int(np.argmin(np.abs(self.levels - level)))]


class RevenueRunner:
    def __init__(self):
        started = time.perf_counter()
        (
            self.bundle,
            artifact_hash,
            version,
            manifest,
            self.snapshot,
            _,
            _,
        ) = load_candidate()
        from features.profile import history_mode
        from models.forecast import (
            FEATS_IN,
            LEVELS,
            business_arrays,
            horizon_row,
            origin_state,
            predict_log,
        )

        self.native_history_mode = history_mode
        self.native_business_arrays = business_arrays
        self.native_origin_state = origin_state
        self.native_horizon_row = horizon_row
        self.native_predict_log = predict_log
        self.native_inflow_features = FEATS_IN
        self.native_levels = LEVELS
        self.load_seconds = time.perf_counter() - started
        self.identity = {
            "model_version": version,
            "native_model_version": self.bundle.version,
            "archive_sha256": manifest["archive_sha256"],
            "model_artifact_sha256": artifact_hash,
            "bridge_source_sha256": manifest["bridge_source_sha256"],
            "vendor_manifest_sha256": hashlib.sha256(
                (SERVICE_ROOT / "vendor-manifest.json").read_bytes()
            ).hexdigest(),
            "benchmark_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "training_metadata": self.bundle.meta,
        }

    def close(self):
        self.snapshot.cleanup()

    def forecast_inflow(self, profile: pd.DataFrame) -> InflowForecast:
        """Execute the frozen inflow equations, leaving outflow/capacity unused."""
        arrays = self.native_business_arrays(profile)
        origin = len(arrays["months"]) - 1
        state = self.native_origin_state(arrays, origin)
        rows = [
            self.native_horizon_row(arrays, state, horizon, None)
            for horizon in range(1, HORIZON + 1)
        ]
        features = pd.DataFrame(rows)
        log_prediction = self.native_predict_log(
            self.bundle.forecast.b_in, features, self.native_inflow_features, "in"
        )
        median = np.maximum(
            np.exp(log_prediction) * (state["L_in"] + state["c_in"]) - state["c_in"],
            0,
        )
        mode = self.native_history_mode(origin + 1)
        grid = np.stack(
            [
                np.maximum(
                    median[index]
                    + self.bundle.forecast._scores("in", horizon, mode)
                    * state["scale"],
                    0,
                )
                for index, horizon in enumerate(range(1, HORIZON + 1))
            ]
        )
        return InflowForecast(
            [state["origin_month"] + horizon for horizon in range(1, HORIZON + 1)],
            mode,
            median,
            grid,
            self.native_levels,
        )

    def predict_case(self, case: object, native_unit_diagnostic: bool = False) -> dict:
        started = time.perf_counter()
        identity = case.get("id") if isinstance(case, dict) else None
        result = {"id": identity if isinstance(identity, str) else None}
        try:
            identity, months, revenue, start, mean = validate_case(case)
            unit_scale = mean / NORMALIZED_HISTORY_MEAN
            normalized = (revenue / mean) * NORMALIZED_HISTORY_MEAN
            result.update(
                transform={
                    "policy": "latest_up_to_12_observed_mean_to_100",
                    "history_mean_original_units": mean,
                    "normalized_history_mean": NORMALIZED_HISTORY_MEAN,
                    "original_units_per_normalized_unit": unit_scale,
                    "fitted_on": "provided_observed_history_only",
                    "window_months": min(len(months), 12),
                },
                history_months=len(months),
                forecast_months=[
                    month_label(start + offset) for offset in range(HORIZON)
                ],
                auxiliary_inputs="unknown_nan",
                industry_prior="unavailable_not_selected",
            )
            inference_started = time.perf_counter()
            forecast = self.forecast_inflow(build_profile(identity, months, normalized))
            result["inference_seconds"] = time.perf_counter() - inference_started
            if list(forecast.months) != list(range(start, start + HORIZON)):
                raise ValueError(
                    "Native forecast months differ from the declared cutoff."
                )
            result.update(
                status="ok",
                history_mode=forecast.mode,
                predictions=inflow_predictions(forecast, unit_scale),
            )
            if native_unit_diagnostic:
                diagnostic_started = time.perf_counter()
                try:
                    native = self.forecast_inflow(
                        build_profile(identity, months, revenue)
                    )
                    result["diagnostic_native_units"] = {
                        "status": "ok",
                        "role": "scale_sensitivity_only",
                        "predictions": inflow_predictions(native, 1.0),
                    }
                except Exception as error:
                    result["diagnostic_native_units"] = {
                        "status": "error",
                        "role": "scale_sensitivity_only",
                        "reason": {
                            "code": "native_unit_inference_failed",
                            "detail": str(error),
                        },
                    }
                result["diagnostic_native_units"]["inference_seconds"] = (
                    time.perf_counter() - diagnostic_started
                )
        except CaseRefusal as error:
            result.update(
                status="refused", reason={"code": error.code, "detail": error.detail}
            )
        except Exception as error:
            result.update(
                status="error",
                reason={"code": "inference_failed", "detail": str(error)},
            )
        result["elapsed_seconds"] = time.perf_counter() - started
        return result

    def run(self, cases: object, native_unit_diagnostic: bool = False) -> dict:
        if isinstance(cases, dict) and set(cases) == {"cases"}:
            cases = cases["cases"]
        if not isinstance(cases, list):
            raise ValueError(
                "Benchmark input must be a list or {cases: list} of history-only cases."
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "model_identity": self.identity,
            "source_limitations": SOURCE_LIMITATIONS,
            "primary_transform": "latest_up_to_12_observed_mean_to_100",
            "native_unit_diagnostic_enabled": native_unit_diagnostic,
            "model_load_seconds": self.load_seconds,
            "cases": [
                self.predict_case(case, native_unit_diagnostic) for case in cases
            ],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--native-unit-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    try:
        cases = json.loads(args.input.read_text(encoding="utf-8"))
        runner = RevenueRunner()
        try:
            result = runner.run(cases, args.native_unit_diagnostic)
        finally:
            runner.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Revenue benchmark failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
