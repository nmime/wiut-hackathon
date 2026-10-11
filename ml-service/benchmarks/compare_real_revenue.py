"""Freeze/select/compare revenue forecasts using licensed offline observations.

Run preparation for development before selection, and terminal preparation only
after selection is written. This does not modify either serving model or report.
"""

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from capacity_ml.evaluate_international import forecast_metrics
from capacity_ml.external_data import build_external_cases, load_external_series
from capacity_ml.forecasting import ForecastModel, MonthlyHistory, normalizer
from capacity_ml.international_data import (
    build_international_cases,
    load_international_series,
)
from capacity_ml.public_revenue import PublicCase, build_cases
from capacity_ml.revenue_data import load_revenue_series
from capacity_ml.revenue_features import revenue_baselines, revenue_feature_matrix

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PROTOCOL = REPO / "docs/model-benchmark-protocol.md"
PROVIDERS = ("uzbekistan_siat", "abs", "statcan", "eurostat", "ons")
BOOTSTRAP_SEED = 20261011
BOOTSTRAP_REPLICATES = 2000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_manifest(output, model_path):
    manifest = read(Path(output) / "manifest.json")
    if digest(model_path) != manifest["default_artifact_sha256"]:
        raise ValueError("Frozen incumbent artifact changed")
    for relative, expected in manifest["source_snapshots"].items():
        if digest(REPO / relative) != expected:
            raise ValueError("Frozen source snapshot changed")


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def provider(case):
    prefix = case.identity.split(":")[0]
    return prefix if prefix in PROVIDERS else "uzbekistan_siat"


def label(month):
    return f"{int(month) // 12:04d}-{int(month) % 12 + 1:02d}"


def collect(phase):
    uz, uzmeta = load_revenue_series()
    if phase == "development":
        allowed = (
            uzmeta["geographic_groups"]["train"]
            + uzmeta["geographic_groups"]["validation"]
        )
        uz = [row for row in uz if row.group in allowed]
    uzcases, uzexcluded = build_cases(uz, uzmeta)
    intl = load_international_series()
    ext = load_external_series()
    cases, training = [], []
    exclusions = {"uzbekistan": uzexcluded}
    if phase == "development":
        cases += uzcases["validation"]
        training += uzcases["train"]
        splits = (("validation", cases), ("train", training))
    else:
        cases += uzcases["test_2025"] + uzcases["test_2026"]
        splits = (("test", cases),)
    for split, destination in splits:
        rows, omitted = build_international_cases(split, dataset=intl)
        destination.extend(rows)
        exclusions[f"international_{split}"] = omitted
        external_split = "audit" if split == "test" else split
        rows, omitted = build_external_cases(external_split, dataset=ext)
        destination.extend(rows)
        exclusions[f"external_{external_split}"] = omitted
    if phase == "development" and any(
        provider(case) == "ons" for case in cases + training
    ):
        raise ValueError("ONS must never enter development or training")
    sources = uzmeta["sources"] + intl[1]["sources"] + ext[1]["sources"]
    return cases, training, {"sources": sources, "exclusions": exclusions}


def record(case, history_slice="full"):
    return {
        "id": f"{case.identity}|{label(case.history.forecast_start)}|{history_slice}",
        "identity": case.identity,
        "provider": provider(case),
        "group": f"{provider(case)}:{case.group}",
        "sector": case.sector,
        "slice": history_slice,
        "months": case.history.months.astype(int).tolist(),
        "inflow": case.history.inflow.tolist(),
        "forecast_start": int(case.history.forecast_start),
        "actual": case.actual.tolist(),
    }


def case_from(row):
    history = MonthlyHistory(
        np.array(row["months"]),
        np.array(row["inflow"]),
        np.zeros(len(row["inflow"])),
        row["forecast_start"],
    )
    return PublicCase(
        row["identity"], row["sector"], row["group"], history, np.array(row["actual"])
    )


def prepare(phase, output, model_path):
    output = Path(output)
    if not PROTOCOL.exists():
        raise ValueError("Preregister the protocol before generating predictions")
    if phase == "terminal":
        selection = read(output / "selection.json")
        if selection["protocol_sha256"] != digest(PROTOCOL):
            raise ValueError("Protocol changed after development selection")
        verify_manifest(output, model_path)
    model = ForecastModel.load(model_path)
    cases, training, provenance = collect(phase)
    rows = [record(case) for case in cases]
    if phase == "terminal":
        from benchmarks.unused_temporal import load_reserved_cases

        unused, unused_manifest = load_reserved_cases()
        rows.extend(record(case, "unused_temporal_full") for case in unused)
        provenance["unused_temporal_reservation"] = unused_manifest
        for count in (3, 6, 12, 24):
            for case in cases:
                if len(case.history.inflow) < count:
                    continue
                h = case.history
                short = PublicCase(
                    case.identity,
                    case.sector,
                    case.group,
                    MonthlyHistory(
                        h.months[-count:],
                        h.inflow[-count:],
                        np.zeros(count),
                        h.forecast_start,
                    ),
                    case.actual,
                )
                rows.append(record(short, f"history_{count}"))
    features, defaults = [], []
    with threadpool_limits(limits=1):
        for row in rows:
            case = case_from(row)
            baselines = revenue_baselines(case.history)
            scale = normalizer(case.history)
            features.append(
                {
                    "id": row["id"],
                    "features": revenue_feature_matrix(
                        case.history, baselines
                    ).tolist(),
                    "base_log": np.log(
                        baselines["damped_seasonal"] / scale + 0.05
                    ).tolist(),
                    "scale": scale,
                }
            )
            started = time.perf_counter()
            scaled = MonthlyHistory(
                case.history.months,
                case.history.inflow * (100 / scale),
                np.zeros(len(case.history.inflow)),
                case.history.forecast_start,
            )
            prediction = model.public_revenue_model.predict(scaled) * (scale / 100)
            elapsed = time.perf_counter() - started
            defaults.append(
                {
                    "id": row["id"],
                    "status": "ok",
                    "median": prediction.tolist(),
                    "seasonal_naive": baselines["seasonal_naive"].tolist(),
                    "timing_seconds": elapsed,
                }
            )
    write(output / f"{phase}-cases.json", {"cases": rows, "provenance": provenance})
    write(
        output / f"{phase}-input.json",
        {
            "cases": [
                {k: row[k] for k in ("id", "months", "inflow", "forecast_start")}
                for row in rows
            ]
        },
    )
    write(output / f"{phase}-features.json", {"cases": features})
    write(
        output / f"{phase}-default.json",
        {
            "model_version": model.version,
            "model_artifact_sha256": digest(model_path),
            "revenue_candidate": model.public_revenue_model.selected,
            "cases": defaults,
        },
    )
    if phase == "development":
        xs, ys, weights = [], [], []
        provider_counts = Counter()
        for case in training:
            provider_counts[provider(case)] += len(case.actual)
        for case in training:
            scale = normalizer(case.history)
            baselines = revenue_baselines(case.history)
            xs.append(revenue_feature_matrix(case.history, baselines))
            ys.append(
                np.log(case.actual / scale + 0.05)
                - np.log(baselines["damped_seasonal"] / scale + 0.05)
            )
            weights.append(
                np.full(len(case.actual), 1 / provider_counts[provider(case)])
            )
        total = sum(provider_counts.values())
        np.savez_compressed(
            output / "training.npz",
            features=np.vstack(xs),
            targets=np.concatenate(ys),
            weights=np.concatenate(weights) * total / len(provider_counts),
        )
        training_manifest = {
            "cases": len(training),
            "target_months": total,
            "unique_targets": len(
                {
                    (case.identity, case.history.forecast_start + h)
                    for case in training
                    for h in range(len(case.actual))
                }
            ),
            "targets_by_provider": dict(provider_counts),
            "training_npz_sha256": digest(output / "training.npz"),
        }
        snapshots = {
            str(path.relative_to(REPO)): digest(path)
            for path in sorted((ROOT / "data").glob("*.json"))
        }
        write(
            output / "manifest.json",
            {
                "protocol_sha256": digest(PROTOCOL),
                "default_artifact_sha256": digest(model_path),
                "source_snapshots": snapshots,
                "training": training_manifest,
                "scope": "Real aggregate revenue only; auxiliary zero series in incumbent is neutral feature representation, not observed expenses.",
            },
        )
    print(
        json.dumps(
            {
                "phase": phase,
                "cases": len(cases),
                "reserved_temporal_cases": sum(
                    row["slice"] == "unused_temporal_full" for row in rows
                ),
                "stress_cases": sum(
                    row["slice"].startswith("history_") for row in rows
                ),
                "training_cases": len(training),
            }
        )
    )


def prediction_map(document, variant=None):
    rows = (
        document["cases"] if variant is None else document["variants"][variant]["cases"]
    )
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate prediction identities")
    result = {}
    for row in rows:
        if row["status"] not in {"ok", "refused"}:
            raise ValueError("Unexpected inference failure must not be dropped")
        if row["status"] == "ok":
            values = row.get("median", row.get("predictions", {}).get("median"))
            prediction = np.asarray(values, dtype=float)
            if (
                prediction.shape != (12,)
                or not np.all(np.isfinite(prediction))
                or np.any(prediction < 0)
            ):
                raise ValueError("Invalid prediction shape, sign or values")
            result[row["id"]] = prediction
    return result


def validate_support(rows, document, *, expected_refusals=False):
    predictions = {row["id"]: row for row in document["cases"]}
    if set(predictions) != {row["id"] for row in rows}:
        raise ValueError("Model response identities must exactly match all cases")
    for row in rows:
        response = predictions[row["id"]]
        should_refuse = expected_refusals and len(row["inflow"]) < 6
        if (response["status"] == "refused") != should_refuse:
            raise ValueError("Unexpected refusal cannot be silently replaced")
        if (
            should_refuse
            and response.get("reason", {}).get("code") != "insufficient_history"
        ):
            raise ValueError("Only the declared short-history refusal permits fallback")


def summary(rows, predictions):
    supported = [row for row in rows if row["id"] in predictions]
    by_provider = {}
    for name in sorted({row["provider"] for row in supported}):
        subset = [row for row in supported if row["provider"] == name]
        by_provider[name] = forecast_metrics(
            [case_from(row) for row in subset],
            [predictions[row["id"]][: len(row["actual"])] for row in subset],
        )
    overall = (
        forecast_metrics(
            [case_from(row) for row in supported],
            [predictions[row["id"]][: len(row["actual"])] for row in supported],
            same_units=False,
        )
        if supported
        else None
    )
    return {
        "requested_cases": len(rows),
        "supported_cases": len(supported),
        "refused_cases": len(rows) - len(supported),
        "refusal_rate_pct": 100 * (len(rows) - len(supported)) / len(rows)
        if rows
        else None,
        "provider_balanced_normalized_mae": float(
            np.mean(
                [
                    metrics["macro_case_normalized_mae"]
                    for metrics in by_provider.values()
                ]
            )
        )
        if by_provider
        else None,
        "overall": overall,
        "providers": by_provider,
    }


def blend_predictions(rows, default, vendor, real, weights):
    a, b, c = weights
    return {
        row["id"]: a * default[row["id"]]
        + b * vendor.get(row["id"], default[row["id"]])
        + c * real[row["id"]]
        for row in rows
    }


def qualified(candidate, reference, tolerance=0.02):
    if set(candidate["providers"]) != set(reference["providers"]):
        return False
    return all(
        values["macro_case_normalized_mae"]
        <= reference["providers"][name]["macro_case_normalized_mae"] * (1 + tolerance)
        for name, values in candidate["providers"].items()
    )


def select(output):
    output = Path(output)
    rows = read(output / "development-cases.json")["cases"]
    incumbent_doc = read(output / "development-default.json")
    vendor_doc = read(output / "development-vendor.json")
    real_doc = read(output / "development-real-lgb.json")
    validate_support(rows, incumbent_doc)
    validate_support(rows, vendor_doc, expected_refusals=True)
    for variant in real_doc["variants"].values():
        validate_support(rows, variant)
    incumbent = prediction_map(incumbent_doc)
    vendor = prediction_map(vendor_doc)
    reference = summary(rows, incumbent)
    real_scores = {
        name: summary(rows, prediction_map(real_doc, name))
        for name in real_doc["variants"]
    }
    eligible = [
        name for name, scores in real_scores.items() if qualified(scores, reference)
    ]
    real_selected = min(
        eligible or list(real_scores),
        key=lambda name: real_scores[name]["provider_balanced_normalized_mae"],
    )
    real = prediction_map(real_doc, real_selected)
    grid = {}
    for a in range(5):
        for b in range(5 - a):
            c = 4 - a - b
            weights = [a / 4, b / 4, c / 4]
            name = f"blend_{a}_{b}_{c}"
            metrics = summary(
                rows, blend_predictions(rows, incumbent, vendor, real, weights)
            )
            gain = (
                1
                - metrics["provider_balanced_normalized_mae"]
                / reference["provider_balanced_normalized_mae"]
            ) * 100
            grid[name] = {
                "weights_default_vendor_real_lgb": weights,
                "metrics": metrics,
                "gain_pct": gain,
                "provider_guard_pass": qualified(metrics, reference),
                "promotion_development_pass": qualified(metrics, reference)
                and gain >= 5,
            }
    promoted = [
        name for name, values in grid.items() if values["promotion_development_pass"]
    ]
    winner = (
        min(
            promoted,
            key=lambda name: (
                round(grid[name]["metrics"]["provider_balanced_normalized_mae"], 12),
                -grid[name]["weights_default_vendor_real_lgb"][0],
                grid[name]["weights_default_vendor_real_lgb"][1],
            ),
        )
        if promoted
        else "blend_4_0_0"
    )
    selection = {
        "protocol_sha256": digest(PROTOCOL),
        "manifest_sha256": digest(output / "manifest.json"),
        "input_hashes": {
            name: digest(output / name)
            for name in (
                "development-cases.json",
                "development-default.json",
                "development-vendor.json",
                "development-real-lgb.json",
            )
        },
        "real_lgb_variant": real_selected,
        "real_lgb_qualification": bool(eligible),
        "real_lgb_trials": real_scores,
        "blend_trials": grid,
        "selected_blend": winner,
        "selected_weights": grid[winner]["weights_default_vendor_real_lgb"],
        "selected_on": "Original development geography and temporal panels only; no terminal model error read",
        "unsupported_vendor_policy": "Use incumbent prediction when native candidate refuses; refusals reported separately.",
        "frozen_vendor_identity": vendor_doc["model_identity"],
        "real_lgb_identity": real_doc.get("model_identity", real_doc.get("metadata")),
    }
    write(output / "selection.json", selection)
    print(
        json.dumps(
            {
                "selected": winner,
                "real_lgb_variant": real_selected,
                "development_gain_pct": grid[winner]["gain_pct"],
            }
        )
    )


def paired_interval(rows, challenger, incumbent):
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["id"] not in challenger or row["id"] not in incumbent:
            continue
        actual = np.array(row["actual"])
        scale = float(np.mean(row["inflow"][-12:]))
        n = len(actual)
        groups[row["provider"]][row["group"]].append(
            [
                float(np.mean(np.abs(actual - challenger[row["id"]][:n])) / scale),
                float(np.mean(np.abs(actual - incumbent[row["id"]][:n])) / scale),
            ]
        )
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws, points = [], []
    counts = {}
    for name, parts in sorted(groups.items()):
        sums = np.array([np.sum(values, axis=0) for values in parts.values()])
        nums = np.array([len(values) for values in parts.values()])
        counts[name] = len(sums)
        points.append(sums.sum(axis=0) / nums.sum())
        indices = rng.integers(0, len(sums), (BOOTSTRAP_REPLICATES, len(sums)))
        draws.append(sums[indices].sum(axis=1) / nums[indices].sum(axis=1)[:, None])
    if not points:
        return None
    point = np.mean(points, axis=0)
    sampled = np.mean(draws, axis=0)
    valid = sampled[:, 1] > 0
    gains = (1 - sampled[valid, 0] / sampled[valid, 1]) * 100
    return {
        "improvement_pct": float((1 - point[0] / point[1]) * 100)
        if point[1] > 0
        else None,
        "descriptive_95pct_interval": np.quantile(gains, [0.025, 0.975]).tolist()
        if len(gains)
        else None,
        "groups_by_provider": counts,
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "limitation": "Stratified paired geographic bootstrap; one-group providers fixed, so ONS national uncertainty is not estimated. Providers may share economic shocks.",
    }


def report(output):
    output = Path(output)
    selection = read(output / "selection.json")
    if selection["protocol_sha256"] != digest(PROTOCOL):
        raise ValueError("Protocol changed after freeze")
    for name, expected in selection["input_hashes"].items():
        if digest(output / name) != expected:
            raise ValueError("Development evidence changed after selection")
    document = read(output / "terminal-cases.json")
    rows = document["cases"]
    default_doc = read(output / "terminal-default.json")
    vendor_doc = read(output / "terminal-vendor.json")
    real_doc = read(output / "terminal-real-lgb.json")
    verify_manifest(output, REPO / "artifacts/model-benchmark/frozen/default.joblib")
    if digest(output / "manifest.json") != selection["manifest_sha256"]:
        raise ValueError("Frozen comparison manifest changed")
    if (
        default_doc["model_artifact_sha256"]
        != read(output / "manifest.json")["default_artifact_sha256"]
    ):
        raise ValueError("Terminal incumbent predictions came from another artifact")
    validate_support(rows, default_doc)
    validate_support(rows, vendor_doc, expected_refusals=True)
    for variant in real_doc["variants"].values():
        validate_support(rows, variant)
    if vendor_doc["model_identity"] != selection["frozen_vendor_identity"]:
        raise ValueError("Vendor identity changed after freeze")
    if real_doc.get("model_identity") != selection["real_lgb_identity"]:
        raise ValueError("Real LightGBM artifacts changed after freeze")
    incumbent = prediction_map(default_doc)
    vendor = prediction_map(vendor_doc)
    real = prediction_map(real_doc, selection["real_lgb_variant"])
    naive = {row["id"]: np.array(row["seasonal_naive"]) for row in default_doc["cases"]}
    native_units = {
        row["id"]: np.array(row["diagnostic_native_units"]["predictions"]["median"])
        for row in vendor_doc["cases"]
        if row.get("diagnostic_native_units", {}).get("status") == "ok"
    }
    selected = blend_predictions(
        rows, incumbent, vendor, real, selection["selected_weights"]
    )
    models = {
        "default_revenue": incumbent,
        "teammate_frozen": vendor,
        "real_trained_lightgbm": real,
        "development_selected": selected,
        "seasonal_naive": naive,
        "teammate_native_units_diagnostic": native_units,
    }
    panels = {}
    for name in sorted({row["slice"] for row in rows}):
        subset = [row for row in rows if row["slice"] == name]
        matched = [row for row in subset if row["id"] in vendor]
        panels[name] = {
            "all_supported": {
                model: summary(subset, predictions)
                for model, predictions in models.items()
            },
            "common_support": {
                model: summary(matched, predictions)
                for model, predictions in models.items()
            },
            "paired_vendor_vs_default": paired_interval(matched, vendor, incumbent),
            "paired_real_lgb_vs_default": paired_interval(subset, real, incumbent),
            "paired_selected_vs_default": paired_interval(subset, selected, incumbent),
            "by_sector": {
                sector: {
                    model: summary(
                        [row for row in subset if row["sector"] == sector], predictions
                    )
                    for model, predictions in models.items()
                }
                for sector in sorted({row["sector"] for row in subset})
            }
            if name in {"full", "unused_temporal_full"}
            else {},
        }
    full = [row for row in rows if row["slice"] == "full"]
    selected_metrics = panels["full"]["all_supported"]["development_selected"]
    default_metrics = panels["full"]["all_supported"]["default_revenue"]
    interval = panels["full"]["paired_selected_vs_default"]
    lower = interval["descriptive_95pct_interval"][0]
    acceptance = {
        "development_gain_at_least_5pct": selection["blend_trials"][
            selection["selected_blend"]
        ]["promotion_development_pass"],
        "terminal_provider_regression_at_most_10pct": qualified(
            selected_metrics, default_metrics, 0.10
        ),
        "paired_interval_lower_bound_positive": lower > 0,
        "terminal_point_improvement_positive": interval["improvement_pct"] > 0,
    }
    unused_panel = panels["unused_temporal_full"]
    unused_selected = unused_panel["all_supported"]["development_selected"]
    unused_default = unused_panel["all_supported"]["default_revenue"]
    unused_gain = (
        1
        - unused_selected["provider_balanced_normalized_mae"]
        / unused_default["provider_balanced_normalized_mae"]
    ) * 100
    acceptance.update(
        {
            "unused_temporal_gain_at_least_5pct": unused_gain >= 5,
            "unused_temporal_provider_regression_at_most_10pct": qualified(
                unused_selected, unused_default, 0.10
            ),
            "unused_temporal_paired_interval_lower_bound_positive": unused_panel[
                "paired_selected_vs_default"
            ]["descriptive_95pct_interval"][0]
            > 0,
        }
    )
    acceptance["pass"] = all(acceptance.values())
    interval_rows = []
    for row in vendor_doc["cases"]:
        if row["status"] == "ok":
            p = row.get("predictions", row)
            if "p10" in p and "p90" in p:
                interval_rows.append(
                    (row["id"], np.array(p["p10"]), np.array(p["p90"]))
                )
    lookup = {row["id"]: row for row in full}
    intervals = {}
    for name in PROVIDERS:
        supported_intervals = [
            (lookup[key], low, high)
            for key, low, high in interval_rows
            if key in lookup and lookup[key]["provider"] == name
        ]
        if supported_intervals:
            observed, covered, widths = 0, 0, []
            for row, low, high in supported_intervals:
                actual = np.array(row["actual"])
                n = len(actual)
                observed += n
                covered += int(np.sum((actual >= low[:n]) & (actual <= high[:n])))
                widths.extend(
                    ((high[:n] - low[:n]) / np.mean(row["inflow"][-12:])).tolist()
                )
            intervals[name] = {
                "nominal_pct": 80,
                "actual_coverage_pct": 100 * covered / observed,
                "months": observed,
                "mean_history_normalized_width": float(np.mean(widths)),
            }
    manifest = read(output / "manifest.json")
    result = {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": digest(PROTOCOL),
        "manifest": manifest,
        "selection": selection,
        "evidence_status": "Paired retrospective comparative regression; incumbent terminal panels were previously consumed, no fresh confirmatory or borrower evidence.",
        "panels": panels,
        "teammate_revenue_interval_coverage": intervals,
        "individual_terminal_periods": {
            period: {
                name: summary(
                    [
                        row
                        for row in full
                        if row["provider"] == "uzbekistan_siat"
                        and label(row["forecast_start"]) == period
                    ],
                    predictions,
                )
                for name, predictions in models.items()
            }
            for period in ("2025-01", "2026-01")
        },
        "evaluator_source_sha256": {
            path.name: digest(path)
            for path in sorted((ROOT / "benchmarks").glob("*.py"))
        },
        "teammate_refusal_reasons": dict(
            Counter(
                row.get("reason", {}).get("code", "unspecified")
                for row in vendor_doc["cases"]
                if row["status"] == "refused"
            )
        ),
        "local_inference_latency": {
            name: {
                "observations": sum(row["status"] == "ok" for row in document["cases"]),
                "requested_cases": len(document["cases"]),
                "median_seconds": float(
                    np.median(
                        [
                            row.get("timing_seconds", row.get("inference_seconds"))
                            for row in document["cases"]
                            if row["status"] == "ok"
                        ]
                    )
                ),
                "p95_seconds": float(
                    np.quantile(
                        [
                            row.get("timing_seconds", row.get("inference_seconds"))
                            for row in document["cases"]
                            if row["status"] == "ok"
                        ],
                        0.95,
                    )
                ),
            }
            for name, document in (("default", default_doc), ("teammate", vendor_doc))
        },
        "promotion_acceptance": acceptance,
        "decision": "Keep both frozen production scorers unchanged. "
        + (
            "Selected revenue experiment passes comparative guards; a fresh panel and downstream engineering validation are required before changing the frozen serving recipe."
            if acceptance["pass"]
            else "Development/terminal gates do not justify a replacement or blend."
        ),
        "provenance": document["provenance"],
        "case_count": len(full),
        "unused_temporal_cases": len(
            [row for row in rows if row["slice"] == "unused_temporal_full"]
        ),
        "unique_target_observations": len(
            {
                (row["identity"], row["forecast_start"] + h)
                for row in full
                for h in range(len(row["actual"]))
            }
        ),
        "artifact_identities": {
            "default": {k: v for k, v in default_doc.items() if k != "cases"},
            "teammate": vendor_doc["model_identity"],
            "real_lgb": real_doc.get("model_identity", real_doc.get("metadata")),
        },
        "limitations": [
            "Aggregate nominal revenues, not bank transactions; no real expense, repayment, capacity or default labels.",
            "Vendor unknown auxiliary financial/channel/activity fields are missing, not fabricated; mean100 normalization is an experimental revenue-only adaptation, not the product scorer.",
            "Different provider-local time cutoffs; not a globally chronological backtest. Single revised snapshot per provider.",
            "Short-history stress reuses full-panel target observations and must not be counted as independent evidence.",
            "Timing measures local model prediction, excluding API/network/load; different library runtimes.",
        ],
    }
    write(ROOT / "reports/real-model-benchmark.json", result)
    evidence = {
        "protocol_sha256": digest(PROTOCOL),
        "cases": [
            {
                **row,
                "predictions": {
                    name: predictions[row["id"]].tolist()
                    if row["id"] in predictions
                    else None
                    for name, predictions in models.items()
                },
            }
            for row in rows
        ],
    }
    write(ROOT / "reports/real-model-benchmark-predictions.json", evidence)
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "full_common": panels["full"]["common_support"],
                "acceptance": acceptance,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("prepare-development", "select", "prepare-terminal", "report"),
    )
    parser.add_argument(
        "--output", type=Path, default=REPO / "artifacts/model-benchmark"
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=REPO / "artifacts/model-benchmark/frozen/default.joblib",
    )
    args = parser.parse_args()
    if args.command.startswith("prepare-"):
        prepare(args.command.removeprefix("prepare-"), args.output, args.model)
    elif args.command == "select":
        select(args.output)
    else:
        report(args.output)


if __name__ == "__main__":
    main()
