"""Bounded upgrade, development freeze and one untouched-source evaluation."""

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from benchmarks.compare_real_revenue import (
    case_from,
    collect,
    digest,
    label,
    prediction_map,
    qualified,
    read,
    record,
    summary,
    validate_support,
    write,
)
from capacity_ml.forecasting import ForecastModel, MonthlyHistory, normalizer
from capacity_ml.revenue_features import revenue_baselines, revenue_feature_matrix
from final_model.calibration import calibrate, coverage

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "docs/revenue-upgrade-protocol.md"
OUTPUT = ROOT / "artifacts/revenue-upgrade"
DEFAULT = ROOT / "artifacts/model-benchmark/frozen/default.joblib"
TRAINER = ROOT / "teammate-ml-service/benchmark/improved_revenue.py"
PREVIOUS = ROOT / "ml-service/reports/real-model-benchmark-predictions.json"
RESERVATION = ROOT / "ml-service/data/fresh-holdout-reservation.json"
SEED = 20261011


def upgrade_module():
    spec = importlib.util.spec_from_file_location("improved_revenue", TRAINER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fresh_record(case, view="full"):
    row = record(case, view)
    row["provider"] = case.identity.split(":")[0]
    row["group"] = f"{row['provider']}:{case.group}"
    return row


def views(rows):
    result = []
    for source in rows:
        row = dict(source)
        row["slice"] = "full"
        row["id"] = f"{row['identity']}|{label(row['forecast_start'])}|full"
        result.append(row)
        for count in (3, 6, 12):
            if len(row["months"]) < count:
                continue
            result.append(
                {
                    **row,
                    "id": f"{row['identity']}|{label(row['forecast_start'])}|history_{count}",
                    "slice": f"history_{count}",
                    "months": row["months"][-count:],
                    "inflow": row["inflow"][-count:],
                }
            )
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("Duplicate case identities")
    return sorted(result, key=lambda row: row["id"])


def features(row, module):
    history = case_from(row).history
    baselines = revenue_baselines(history)
    return module.make_prediction_case(
        row["id"],
        row["months"],
        row["inflow"],
        row["forecast_start"],
        revenue_feature_matrix(history, baselines),
        baselines,
    ), baselines


def development_rows():
    cases, training, metadata = collect("development")
    rows = [record(case) for case in cases]
    for row in read(PREVIOUS)["cases"]:
        if row["slice"] not in {"full", "unused_temporal_full"}:
            continue
        rows.append({k: v for k, v in row.items() if k != "predictions"})
    from benchmarks.fresh_data import build_fresh_cases, load_fresh_series

    dataset = load_fresh_series()
    fresh_training, train_excluded = build_fresh_cases("train", dataset)
    fresh_development, dev_excluded = build_fresh_cases("development", dataset)
    rows.extend(fresh_record(case) for case in fresh_development)
    metadata["fresh_sources"] = dataset[1]["sources"]
    metadata["fresh_exclusions"] = {
        "train": train_excluded,
        "development": dev_excluded,
    }
    return views(rows), training + fresh_training, metadata


def prepare_predictions(rows, module, model):
    inputs, defaults = [], []
    with threadpool_limits(limits=1):
        for row in rows:
            case = case_from(row)
            payload, baselines = features(row, module)
            inputs.append(payload)
            scale = normalizer(case.history)
            normalized = MonthlyHistory(
                case.history.months,
                case.history.inflow * (100 / scale),
                np.zeros(len(case.history.inflow)),
                case.history.forecast_start,
            )
            prediction = model.public_revenue_model.predict(normalized) * (scale / 100)
            defaults.append(
                {
                    "id": row["id"],
                    "status": "ok",
                    "median": prediction.tolist(),
                    "seasonal_naive": baselines["seasonal_naive"].tolist(),
                }
            )
    return {"cases": inputs}, {
        "cases": defaults,
        "model_artifact_sha256": digest(DEFAULT),
        "model_version": model.version,
    }


def prepare(output):
    if not PROTOCOL.exists() or not RESERVATION.exists():
        raise ValueError("Freeze protocol and fresh target reservation before training")
    from benchmarks.fresh_data import reserve_fresh_holdout

    frozen_reservation = read(RESERVATION)
    if reserve_fresh_holdout(write_manifest=False) != frozen_reservation:
        raise ValueError("Fresh reservation changed")
    if (output / "manifest.json").exists():
        raise ValueError("Preserve the original experiment; preparation is train-once")
    output.mkdir(parents=True, exist_ok=True)
    module = upgrade_module()
    rows, training, provenance = development_rows()
    providers = Counter()
    for case in training:
        providers[
            case.identity.split(":")[0]
            if case.identity.startswith("statcan_wholesale:")
            else record(case)["provider"]
        ] += len(case.actual)
    xs, ys, anchors, weights = [], [], [], []
    unique_targets = set()
    with threadpool_limits(limits=1):
        for case in training:
            row = (
                fresh_record(case)
                if case.identity.startswith("statcan_wholesale:")
                else record(case)
            )
            provider = row["provider"]
            lengths = sorted(
                {
                    min(count, len(row["months"]))
                    for count in (3, 6, 12, len(row["months"]))
                }
            )
            for count in lengths:
                view = {
                    **row,
                    "months": row["months"][-count:],
                    "inflow": row["inflow"][-count:],
                }
                payload, _ = features(view, module)
                scale = payload["scale"]
                xs.append(
                    np.asarray(payload["features"], dtype=float)[: len(case.actual)]
                )
                ys.append(np.asarray(case.actual) / scale)
                anchors.append(
                    np.column_stack(
                        [
                            payload["normalized_baselines"][name][: len(case.actual)]
                            for name in module.ANCHORS
                        ]
                    )
                )
                weights.append(
                    np.full(len(case.actual), 1 / providers[provider] / len(lengths))
                )
            unique_targets.update(
                (case.identity, case.history.forecast_start + h)
                for h in range(len(case.actual))
            )
    np.savez_compressed(
        output / "training.npz",
        features=np.vstack(xs),
        normalized_targets=np.concatenate(ys),
        normalized_baselines=np.vstack(anchors),
        weights=np.concatenate(weights) * sum(providers.values()) / len(providers),
    )
    model = ForecastModel.load(DEFAULT)
    inputs, defaults = prepare_predictions(rows, module, model)
    write(output / "development-cases.json", {"cases": rows, "provenance": provenance})
    write(output / "development-features.json", inputs)
    write(output / "development-default.json", defaults)
    manifest = {
        "protocol_sha256": digest(PROTOCOL),
        "reservation_sha256": digest(RESERVATION),
        "default_artifact_sha256": digest(DEFAULT),
        "previous_predictions_sha256": digest(PREVIOUS),
        "feature_protocol": module.protocol(),
        "feature_source_identity": module.source_identity(),
        "data_snapshots": {
            str(path.relative_to(ROOT)): digest(path)
            for path in sorted((ROOT / "ml-service/data").glob("*.json"))
        },
        "training": {
            "origins": len(training),
            "target_months_before_augmentation": sum(providers.values()),
            "unique_targets": len(unique_targets),
            "augmented_rows": sum(len(y) for y in ys),
            "targets_by_provider": dict(providers),
            "training_sha256": digest(output / "training.npz"),
        },
        "prepared_at_utc": datetime.now(UTC).isoformat(),
    }
    write(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "phase": "development",
                "cases_full": sum(row["slice"] == "full" for row in rows),
                "training": manifest["training"],
            }
        )
    )


def verify(output, selection=False):
    manifest = read(output / "manifest.json")
    checks = {
        PROTOCOL: manifest["protocol_sha256"],
        RESERVATION: manifest["reservation_sha256"],
        DEFAULT: manifest["default_artifact_sha256"],
        PREVIOUS: manifest["previous_predictions_sha256"],
        output / "training.npz": manifest["training"]["training_sha256"],
    }
    checks.update(
        {ROOT / path: expected for path, expected in manifest["data_snapshots"].items()}
    )
    for path, expected in checks.items():
        if digest(path) != expected:
            raise ValueError(f"Frozen input changed: {path.name}")
    if upgrade_module().source_identity() != manifest["feature_source_identity"]:
        raise ValueError("Feature/trainer source changed after preparation")
    if selection:
        selected = read(output / "selection.json")
        for name, expected in selected["input_hashes"].items():
            if digest(output / name) != expected:
                raise ValueError("Development evidence changed after selection")
    return manifest


def compact_scores(rows, predictions):
    result = summary(rows, predictions)
    return {
        "cases": result["supported_cases"],
        "provider_balanced_normalized_mae": result["provider_balanced_normalized_mae"],
        "providers": {
            name: {
                "macro_case_normalized_mae": score["macro_case_normalized_mae"],
                "cases": score["cases"],
            }
            for name, score in result["providers"].items()
        },
    }


def gain(candidate, reference):
    return 100 * (
        1
        - candidate["provider_balanced_normalized_mae"]
        / reference["provider_balanced_normalized_mae"]
    )


def mix(rows, incumbent, candidate, weight):
    return {
        row["id"]: weight * incumbent[row["id"]] + (1 - weight) * candidate[row["id"]]
        for row in rows
    }


def select(output):
    manifest = verify(output)
    rows = read(output / "development-cases.json")["cases"]
    default_doc, candidate_doc = (
        read(output / "development-default.json"),
        read(output / "development-improved.json"),
    )
    identity = candidate_doc["model_identity"]
    module = upgrade_module()
    if (
        candidate_doc["schema_version"] != module.SCHEMA_VERSION
        or candidate_doc["selected_variant_only"] is not None
        or default_doc["model_artifact_sha256"] != manifest["default_artifact_sha256"]
        or identity != read(output / "models" / module.MANIFEST_NAME)
        or identity["training_npz_sha256"] != manifest["training"]["training_sha256"]
        or identity["training_data_manifest_sha256"] != digest(output / "manifest.json")
        or identity["training_rows"] != manifest["training"]["augmented_rows"]
        or identity["source_identity"] != manifest["feature_source_identity"]
        or identity["protocol"] != manifest["feature_protocol"]
        or set(candidate_doc["variants"]) != set(module.VARIANT_CONFIGS)
        or set(identity["artifact_hashes"]) != set(module.VARIANT_CONFIGS)
        or identity["lightgbm_version"] != "4.7.0"
    ):
        raise ValueError(
            "Development model differs from frozen training inputs/protocol"
        )
    for variant, document in candidate_doc["variants"].items():
        component = document["model_identity"]
        if (
            digest(output / "models" / f"{variant}.txt")
            != identity["artifact_hashes"][variant]
            or component["training_npz_sha256"] != identity["training_npz_sha256"]
            or component["artifact_sha256"] != identity["artifact_hashes"][variant]
            or component["config"] != module.VARIANT_CONFIGS[variant]
            or component["source_identity"] != identity["source_identity"]
        ):
            raise ValueError("Development variant differs from frozen model identity")
    validate_support(rows, default_doc)
    incumbent = prediction_map(default_doc)
    full = [row for row in rows if row["slice"] == "full"]
    stresses = {
        str(n): [row for row in rows if row["slice"] == f"history_{n}"]
        for n in (3, 6, 12)
    }
    reference = compact_scores(full, incumbent)
    reference_stress = {
        name: compact_scores(subset, incumbent) for name, subset in stresses.items()
    }
    trials = {}
    for variant, document in sorted(candidate_doc["variants"].items()):
        validate_support(rows, document)
        candidate = prediction_map(document)
        for weight in (0, 0.25, 0.5, 0.75):
            predictions = mix(rows, incumbent, candidate, weight)
            metrics = compact_scores(full, predictions)
            stress_metrics = {
                name: compact_scores(subset, predictions)
                for name, subset in stresses.items()
            }
            guarded = qualified(metrics, reference) and all(
                score["provider_balanced_normalized_mae"]
                <= reference_stress[name]["provider_balanced_normalized_mae"] * 1.02
                for name, score in stress_metrics.items()
            )
            name = f"{variant}|incumbent_{weight:g}"
            trials[name] = {
                "variant": variant,
                "incumbent_weight": weight,
                "metrics": metrics,
                "stress_metrics": stress_metrics,
                "gain_pct": gain(metrics, reference),
                "guard_pass": guarded,
                "development_eligible": guarded and gain(metrics, reference) >= 5,
            }
    guarded = [name for name, trial in trials.items() if trial["guard_pass"]]
    eligible = [name for name, trial in trials.items() if trial["development_eligible"]]
    winner = min(
        eligible or guarded or list(trials),
        key=lambda name: (
            round(trials[name]["metrics"]["provider_balanced_normalized_mae"], 12),
            -trials[name]["incumbent_weight"],
            trials[name]["variant"],
        ),
    )
    selected = {
        "selected": trials[winner],
        "selected_name": winner,
        "development_eligible": bool(eligible),
        "reference": reference,
        "reference_stresses": reference_stress,
        "trials": trials,
        "unique_candidates_including_incumbent": 33,
        "model_identity": candidate_doc["model_identity"],
        "manifest": manifest,
        "input_hashes": {
            name: digest(output / name)
            for name in (
                "manifest.json",
                "development-cases.json",
                "development-features.json",
                "development-default.json",
                "development-improved.json",
            )
        },
        "frozen_before_holdout_inference": True,
        "selected_at_utc": datetime.now(UTC).isoformat(),
    }
    external = {
        (row["identity"], row["forecast_start"])
        for row in read(PREVIOUS)["cases"]
        if row["slice"] == "full" and row["provider"] in {"eurostat", "ons"}
    }
    calibration_rows = [
        row for row in rows if (row["identity"], row["forecast_start"]) not in external
    ]
    frozen_candidate = mix(
        rows,
        incumbent,
        prediction_map(candidate_doc, trials[winner]["variant"]),
        trials[winner]["incumbent_weight"],
    )
    grids = {
        "current": calibrate(calibration_rows, incumbent),
        "improved": calibrate(calibration_rows, frozen_candidate),
    }
    calibration = {
        "models": grids,
        "excluded_external_windows": len(external),
        "excluded_external_target_keys": sorted([list(key) for key in external]),
        "calibration_rows": len(calibration_rows),
        "calibration_input_sha256": digest(output / "development-cases.json"),
        "model_identity": candidate_doc["model_identity"],
        "default_artifact_sha256": digest(DEFAULT),
        "protocol_sha256": digest(PROTOCOL),
        "source_sha256": digest(ROOT / "ml-service/final_model/calibration.py"),
    }
    write(output / "calibration.json", calibration)
    selected["input_hashes"]["calibration.json"] = digest(output / "calibration.json")
    audit_rows = [
        row for row in full if (row["identity"], row["forecast_start"]) in external
    ]
    selected["external_interval_diagnostic"] = {
        "scope": "68 previously consumed external-audit windows; excluded from residual calibration, not fresh confirmatory evidence.",
        "current": coverage(audit_rows, incumbent, grids["current"]),
        "improved": coverage(audit_rows, frozen_candidate, grids["improved"]),
    }
    write(output / "selection.json", selected)
    print(
        json.dumps(
            {
                "variant": trials[winner]["variant"],
                "incumbent_weight": trials[winner]["incumbent_weight"],
                "development_gain_pct": trials[winner]["gain_pct"],
                "development_eligible": bool(eligible),
            }
        )
    )


def terminal(output):
    verify(output, selection=True)
    from benchmarks.fresh_data import build_fresh_cases, load_fresh_series

    dataset = load_fresh_series()
    cases, exclusions = build_fresh_cases("holdout", dataset)
    rows = views([fresh_record(case) for case in cases])
    for row in rows:
        row["audit_only"] = (
            row["identity"]
            in dataset[1]["protocols"][row["provider"]]["audit_only_sectors"]
        )
        row["target_block"] = row["forecast_start"] // 12
    inputs, defaults = prepare_predictions(
        rows, upgrade_module(), ForecastModel.load(DEFAULT)
    )
    write(
        output / "holdout-cases.json",
        {"cases": rows, "exclusions": exclusions, "sources": dataset[1]["sources"]},
    )
    write(output / "holdout-features.json", inputs)
    write(output / "holdout-default.json", defaults)
    previous_inputs = []
    for row in rows:
        history = case_from(row).history
        baselines = revenue_baselines(history)
        scale = normalizer(history)
        previous_inputs.append(
            {
                "id": row["id"],
                "features": revenue_feature_matrix(history, baselines).tolist(),
                "base_log": np.log(
                    baselines["damped_seasonal"] / scale + 0.05
                ).tolist(),
                "scale": scale,
            }
        )
    write(output / "holdout-previous-features.json", {"cases": previous_inputs})
    print(
        json.dumps(
            {
                "phase": "holdout",
                "full_cases": len(cases),
                "exclusions": len(exclusions),
                "selection_sha256": digest(output / "selection.json"),
            }
        )
    )


def block_interval(rows, challenger, incumbent):
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        n, scale = len(row["actual"]), float(np.mean(row["inflow"][-12:]))
        actual = np.asarray(row["actual"])
        groups[row["provider"]][row["target_block"]].append(
            [
                float(np.mean(np.abs(actual - challenger[row["id"]][:n])) / scale),
                float(np.mean(np.abs(actual - incumbent[row["id"]][:n])) / scale),
            ]
        )
    blocks = sorted(set.intersection(*(set(parts) for parts in groups.values())))
    if len(blocks) < 2 or any(set(parts) != set(blocks) for parts in groups.values()):
        raise ValueError(
            "Paired annual-block inference needs aligned multi-year panels"
        )
    sums = np.asarray(
        [
            [np.sum(parts[block], axis=0) for block in blocks]
            for _, parts in sorted(groups.items())
        ]
    )
    counts = np.asarray(
        [[len(parts[block]) for block in blocks] for _, parts in sorted(groups.items())]
    )
    samples = np.random.default_rng(SEED).integers(0, len(blocks), (2000, len(blocks)))
    sampled = (
        sums[:, samples, :].sum(axis=2) / counts[:, samples].sum(axis=2)[:, :, None]
    ).mean(axis=0)
    improvements = (1 - sampled[:, 0] / sampled[:, 1]) * 100
    point = (sums.sum(axis=1) / counts.sum(axis=1)[:, None]).mean(axis=0)
    return {
        "improvement_pct": float((1 - point[0] / point[1]) * 100),
        "descriptive_95pct_interval": np.quantile(
            improvements, [0.025, 0.975]
        ).tolist(),
        "paired_annual_blocks": blocks,
        "replicates": 2000,
        "seed": SEED,
        "limitation": "Nine revised-vintage annual blocks and two countries; paired year draws retain within-year cross-country shocks. Serial and survey-revision dependence can remain; no independent-borrower or prospective guarantee.",
    }


def report(output):
    manifest = verify(output, selection=True)
    selection = read(output / "selection.json")
    document = read(output / "holdout-cases.json")
    rows = document["cases"]
    default_doc = read(output / "holdout-default.json")
    improved_doc = read(output / "holdout-improved.json")
    variant = selection["selected"]["variant"]
    module = upgrade_module()
    if (
        set(improved_doc["variants"]) != {variant}
        or improved_doc["model_identity"] != selection["model_identity"]
        or improved_doc["schema_version"] != module.SCHEMA_VERSION
        or improved_doc["selected_variant_only"] != variant
        or default_doc["model_artifact_sha256"] != manifest["default_artifact_sha256"]
        or improved_doc["variants"][variant]["model_identity"]
        != read(output / "development-improved.json")["variants"][variant][
            "model_identity"
        ]
    ):
        raise ValueError(
            "Only the frozen selected configuration may receive holdout scores"
        )
    validate_support(rows, default_doc)
    validate_support(rows, improved_doc["variants"][variant])
    previous_doc = read(output / "holdout-previous.json")
    previous_variant = "real_lgb_leaves31_rounds400"
    validate_support(rows, previous_doc["variants"][previous_variant])
    original_identity = read(ROOT / "ml-service/reports/real-model-benchmark.json")[
        "artifact_identities"
    ]["real_lgb"]
    if previous_doc["model_identity"] != original_identity:
        raise ValueError("Previous third model artifact changed")
    incumbent = prediction_map(default_doc)
    challenger = mix(
        rows,
        incumbent,
        prediction_map(improved_doc, variant),
        selection["selected"]["incumbent_weight"],
    )
    predictions = {
        "current": incumbent,
        "improved": challenger,
        "previous_third": prediction_map(previous_doc, previous_variant),
        "seasonal_naive": {
            row["id"]: np.asarray(row["seasonal_naive"]) for row in default_doc["cases"]
        },
    }
    full = [row for row in rows if row["slice"] == "full"]
    primary = [row for row in full if row["audit_only"]]
    latest_year = max(row["target_block"] for row in full)
    latest = [row for row in full if row["target_block"] == latest_year]
    panels = {"fresh_multi_era_audit": primary, "fresh_latest": latest}
    panels.update(
        {
            f"history_{n}": [
                row
                for row in rows
                if row["audit_only"] and row["slice"] == f"history_{n}"
            ]
            for n in (3, 6, 12)
        }
    )
    metrics = {
        name: {model: summary(subset, values) for model, values in predictions.items()}
        for name, subset in panels.items()
    }
    calibration = read(output / "calibration.json")
    interval_coverage = {
        panel: {
            model: coverage(subset, predictions[model], calibration["models"][model])
            for model in ("current", "improved")
        }
        for panel, subset in panels.items()
    }
    bootstrap = block_interval(primary, challenger, incumbent)
    tests = {
        "development_eligible": selection["development_eligible"],
        "primary_gain_at_least_5pct": gain(
            metrics["fresh_multi_era_audit"]["improved"],
            metrics["fresh_multi_era_audit"]["current"],
        )
        >= 5,
        "block_interval_lower_above_zero": bootstrap["descriptive_95pct_interval"][0]
        > 0,
        "primary_each_provider_at_most_2pct_regression": qualified(
            metrics["fresh_multi_era_audit"]["improved"],
            metrics["fresh_multi_era_audit"]["current"],
        ),
        "latest_gain_at_least_5pct": gain(
            metrics["fresh_latest"]["improved"], metrics["fresh_latest"]["current"]
        )
        >= 5,
        "latest_each_provider_at_most_2pct_regression": qualified(
            metrics["fresh_latest"]["improved"], metrics["fresh_latest"]["current"]
        ),
        "all_short_history_guards": all(
            metrics[f"history_{n}"]["improved"]["provider_balanced_normalized_mae"]
            <= metrics[f"history_{n}"]["current"]["provider_balanced_normalized_mae"]
            * 1.02
            for n in (3, 6, 12)
        ),
        "all_outputs_valid": True,
    }
    result = {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": digest(PROTOCOL),
        "reservation": read(RESERVATION),
        "manifest": manifest,
        "selection": selection,
        "panels": metrics,
        "paired_annual_block_interval": bootstrap,
        "revenue_interval_coverage": interval_coverage,
        "external_interval_diagnostic": selection["external_interval_diagnostic"],
        "calibration_sha256": digest(output / "calibration.json"),
        "promotion_gates": tests,
        "eligible_for_product_integration": all(tests.values()),
        "decision": "eligible_for_product_integration"
        if all(tests.values())
        else "retain_current_default",
        "sources": document["sources"],
        "exclusions": document["exclusions"],
        "evidence_consumed_after_this_measurement": True,
        "limitations": [
            "Aggregate nominal turnover and NZ electronic card-spend proxy; no real expenses, repayment or default outcomes.",
            "Fresh provider/sector labels are revised-vintage retrospective measurements, not historical-vintage prospective validation.",
            "Earlier terminal and temporal labels were explicitly consumed development evidence.",
            "Only one frozen upgrade configuration was evaluated on final targets; no post-final tuning or threshold relaxation.",
            "Raw CAD and NZD values are never pooled as money or used as borrower currency without conversion.",
        ],
        "evaluator_source_sha256": digest(Path(__file__)),
    }
    write(ROOT / "ml-service/reports/revenue-upgrade-fresh.json", result)
    write(
        ROOT / "ml-service/reports/revenue-upgrade-fresh-predictions.json",
        {
            "protocol_sha256": digest(PROTOCOL),
            "selection_sha256": digest(output / "selection.json"),
            "cases": [
                {
                    **row,
                    "predictions": {
                        name: values[row["id"]].tolist()
                        for name, values in predictions.items()
                    },
                }
                for row in rows
            ],
        },
    )
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "development_gain_pct": selection["selected"]["gain_pct"],
                "fresh_primary_gain_pct": gain(
                    metrics["fresh_multi_era_audit"]["improved"],
                    metrics["fresh_multi_era_audit"]["current"],
                ),
                "fresh_latest_gain_pct": gain(
                    metrics["fresh_latest"]["improved"],
                    metrics["fresh_latest"]["current"],
                ),
                "interval": bootstrap["descriptive_95pct_interval"],
                "gates": tests,
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "select", "terminal", "report"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    {"prepare": prepare, "select": select, "terminal": terminal, "report": report}[
        args.phase
    ](args.output)


if __name__ == "__main__":
    main()
