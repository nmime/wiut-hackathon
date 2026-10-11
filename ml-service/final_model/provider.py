"""Verified local real-revenue median, real residual grid and observed costs."""

import hashlib
import importlib.metadata
import importlib.util
import io
import json
import sys
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from capacity_ml.forecasting import (
    ForecastModel,
    aggregate,
    normalizer,
    project_observed_expenses,
)
from capacity_ml.revenue_features import revenue_baselines, revenue_feature_matrix

from .calibration import LEVELS, revenue_grid

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_path(directory, name, expected):
    path = directory / name
    if Path(name).name != name or path.is_symlink() or not path.is_file():
        raise ValueError("Final component path or SHA-256 is invalid")
    snapshot = path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != expected:
        raise ValueError("Final component SHA-256 is invalid")
    return snapshot


class RealRevenueProvider:
    def __init__(self, directory):
        directory = Path(directory)
        if directory.is_symlink():
            raise ValueError("Final bundle must not be a symlink")
        from .release import BUNDLE_SHA256, RUNTIME_VERSIONS

        bundle_bytes = verified_path(directory, "bundle.json", BUNDLE_SHA256)
        self.bundle = json.loads(bundle_bytes)
        bundle = self.bundle
        if bundle.get("format") != 1 or bundle.get("revenue_component") not in {
            "current",
            "improved",
        }:
            raise ValueError("Unsupported final revenue bundle")
        for package, expected in RUNTIME_VERSIONS.items():
            if importlib.metadata.version(package) != expected:
                raise ValueError(f"Final runtime dependency changed: {package}")
        actual_baseline_sources = {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted((ROOT / "ml-service/capacity_ml").glob("*.py"))
        }
        if actual_baseline_sources != bundle["baseline_source_hashes"]:
            raise ValueError("Measured incumbent implementation changed")
        vendor_manifest = ROOT / "teammate-ml-service/vendor-manifest.json"
        if sha256(vendor_manifest) != bundle["vendor_manifest_sha256"]:
            raise ValueError("Measured native vendor manifest changed")
        if (
            json.loads(vendor_manifest.read_bytes())["model_artifact_sha256"]
            != bundle["native_financial_artifact_sha256"]
        ):
            raise ValueError("Measured native financial artifact changed")
        baseline_bytes = verified_path(
            directory, bundle["baseline_file"], bundle["baseline_sha256"]
        )
        # Trust only our explicitly frozen artifact before pickle deserialization.
        if (
            bundle["baseline_sha256"]
            != "31693530f17dbd481752d0996b0d4131c65ee0af859346a8f83aea7f17283b96"
        ):
            raise ValueError("The measured incumbent baseline was substituted")
        self.baseline = ForecastModel.load(io.BytesIO(baseline_bytes))
        calibration_bytes = verified_path(
            directory, bundle["calibration_file"], bundle["calibration_sha256"]
        )
        calibration_snapshot = json.loads(calibration_bytes)
        self.calibrations = calibration_snapshot["models"]
        report = json.loads(
            verified_path(
                directory, bundle["fresh_report_file"], bundle["fresh_report_sha256"]
            )
        )
        if (
            report["calibration_sha256"] != bundle["calibration_sha256"]
            or report["manifest"]["default_artifact_sha256"]
            != bundle["baseline_sha256"]
        ):
            raise ValueError(
                "Release calibration/baseline differs from frozen evidence"
            )
        if (
            bool(report["eligible_for_product_integration"])
            != bundle["fresh_revenue_gates_passed"]
        ):
            raise ValueError("Release qualification differs from measured gates")
        if bundle["revenue_component"] == "improved" and not all(
            report["promotion_gates"].values()
        ):
            raise ValueError("Fresh revenue promotion gates failed")
        self.calibration = calibration_snapshot["models"][bundle["revenue_component"]]
        if bundle["calibration_source_sha256"] != sha256(
            Path(__file__).with_name("calibration.py")
        ):
            raise ValueError("Real residual calibration implementation changed")
        # Validate all declared interval buckets even when the first live request
        # has only one particular history length.
        for count in (3, 24):
            revenue_grid(np.ones(12), 1.0, count, self.calibration)
        self.upgrade = None
        self.booster = None
        if bundle["revenue_component"] == "improved":
            if not bundle.get("fresh_revenue_gates_passed"):
                raise ValueError("An unqualified revenue upgrade cannot serve")
            import lightgbm as lgb

            trainer = ROOT / "teammate-ml-service/benchmark/improved_revenue.py"
            spec = importlib.util.spec_from_file_location(
                "final_revenue_upgrade", trainer
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            if module.source_identity() != bundle["upgrade_source_identity"]:
                raise ValueError(
                    "Qualified revenue source differs from frozen evidence"
                )
            self.upgrade = module
            frozen = report["selection"]
            if (
                bundle["upgrade_variant"] != frozen["selected"]["variant"]
                or bundle["incumbent_weight"] != frozen["selected"]["incumbent_weight"]
                or bundle["upgrade_sha256"]
                != frozen["model_identity"]["artifact_hashes"][
                    bundle["upgrade_variant"]
                ]
            ):
                raise ValueError("Final upgrade differs from pre-holdout selection")
            model_bytes = verified_path(
                directory, bundle["upgrade_file"], bundle["upgrade_sha256"]
            )
            self.booster = lgb.Booster(model_str=model_bytes.decode())
        self.identity = {
            "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "baseline_sha256": bundle["baseline_sha256"],
            "baseline_source_hashes": bundle["baseline_source_hashes"],
            "vendor_manifest_sha256": bundle["vendor_manifest_sha256"],
            "native_financial_artifact_sha256": bundle[
                "native_financial_artifact_sha256"
            ],
            "calibration_sha256": bundle["calibration_sha256"],
            "revenue_component": bundle["revenue_component"],
            "revenue_candidate": bundle["revenue_candidate"],
            "fresh_revenue_gates_passed": bundle["fresh_revenue_gates_passed"],
            "fresh_report_sha256": bundle["fresh_report_sha256"],
            "real_training_targets": bundle["real_training_targets"],
        }
        if self.booster is not None:
            self.identity["upgrade_sha256"] = bundle["upgrade_sha256"]
            self.identity["incumbent_weight"] = bundle["incumbent_weight"]
        self.health = {
            "real_revenue_weight": 1.0,
            "synthetic_net_weight": 0.0,
            "expense_mode": "observed_cost_projection",
            "revenue_candidate": bundle["revenue_candidate"],
            "real_training_targets": bundle["real_training_targets"],
            "calibration_scope": "empirical_real_revenue_only",
            "calibrated_borrower_probability": False,
            "data_sources": bundle["sources"],
            "monetary_units": "1 amount_index = 1 UZS from actual imported transactions; public-source monetary/index observations supply normalized patterns only",
        }

    def __call__(self, payload):
        history = aggregate(payload)
        scale = normalizer(history)
        short_history = len(history.months) < 3
        use_upgrade = self.booster is not None and not short_history
        with threadpool_limits(limits=1):
            median = self.baseline.public_revenue_model.predict(history)
            if use_upgrade:
                baselines = revenue_baselines(history)
                case = self.upgrade.make_prediction_case(
                    "live",
                    history.months,
                    history.inflow,
                    history.forecast_start,
                    revenue_feature_matrix(history, baselines),
                    baselines,
                )
                result = self.upgrade.predict_case(
                    self.booster,
                    self.upgrade.VARIANT_CONFIGS[self.bundle["upgrade_variant"]],
                    case,
                )
                if result["status"] != "ok":
                    raise ValueError("Qualified revenue inference failed")
                weight = self.bundle["incumbent_weight"]
                median = weight * median + (1 - weight) * np.asarray(
                    result["predictions"]["median"]
                )
            if not np.any(history.inflow[-12:] > 0):
                median = np.zeros(12)
            expenses = project_observed_expenses(
                history, median, self.baseline.expense_policy
            )
        effective_calibration = (
            self.calibrations["current"] if short_history else self.calibration
        )
        grid = revenue_grid(median, scale, len(history.months), effective_calibration)
        months = [
            f"{int(month) // 12:04d}-{int(month) % 12 + 1:02d}"
            for month in range(history.forecast_start, history.forecast_start + 12)
        ]
        return {
            "months": months,
            "median": median.tolist(),
            "revenue_grid": grid.tolist(),
            "quantile_levels": LEVELS.tolist(),
            "observed_outflow_projection": expenses.tolist(),
            "history_months": [
                f"{int(month) // 12:04d}-{int(month) % 12 + 1:02d}"
                for month in history.months
            ],
            "history_inflow": history.inflow.tolist(),
            "history_outflow": history.outflow.tolist(),
            "expense_policy": "observed_cost_projection",
            "provenance": {
                **self.identity,
                "revenue_model_version": self.bundle["revenue_version"]
                if use_upgrade or self.booster is None
                else self.baseline.version,
                "real_training_targets": self.bundle["real_training_targets"]
                if use_upgrade or self.booster is None
                else 86976,
                "model_artifact_sha256": self.bundle.get(
                    "upgrade_sha256", self.bundle["baseline_sha256"]
                )
                if use_upgrade
                else self.bundle["baseline_sha256"],
                "effective_revenue_component": "improved" if use_upgrade else "current",
                "short_history_fallback": "incumbent_below_upgrade_minimum_3_months"
                if short_history and self.booster is not None
                else None,
                "uncertainty_support": "below_calibration_minimum_3_months"
                if short_history
                else "measured_history_bucket",
                "real_revenue_weight": 1.0,
                "synthetic_net_weight": 0.0,
                "expense_projection_policy": self.baseline.expense_policy,
                "partial_month_excluded": history.partial_month_excluded,
                "partial_only": history.partial_only,
                "uncertainty_scope": "Revenue only; future expenses are an observed-history assumption. Free-flow/repayment/default coverage is unvalidated.",
                "unknown_debt_category": "Observed total outflows already include unclassified repayments; no separate debt or counterparty labels inferred.",
            },
        }


def load_provider(directory):
    return RealRevenueProvider(directory)
