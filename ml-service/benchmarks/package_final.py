"""Package measured local components; never train or change a promotion rule."""

import hashlib
import json
import shutil
from pathlib import Path

from capacity_ml.forecasting import ForecastModel

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "ml-service/final_model/artifacts"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    evidence = ROOT / "ml-service/reports/revenue-upgrade-fresh.json"
    report = json.loads(evidence.read_bytes())
    experiment = ROOT / "artifacts/revenue-upgrade"
    calibration = experiment / "calibration.json"
    baseline = ASSETS / "baseline.joblib"
    if (
        digest(baseline) != report["manifest"]["default_artifact_sha256"]
        or digest(baseline)
        != "31693530f17dbd481752d0996b0d4131c65ee0af859346a8f83aea7f17283b96"
        or digest(calibration) != report["calibration_sha256"]
        or digest(ROOT / "docs/revenue-upgrade-protocol.md")
        != report["protocol_sha256"]
    ):
        raise ValueError("Measured components or preregistered protocol changed")
    calibration_doc = json.loads(calibration.read_bytes())
    if calibration_doc["source_sha256"] != digest(
        ROOT / "ml-service/final_model/calibration.py"
    ):
        raise ValueError("Measured calibration implementation changed")
    baseline_sources = {
        str(path.relative_to(ROOT)): digest(path)
        for path in sorted((ROOT / "ml-service/capacity_ml").glob("*.py"))
    }
    for name, expected in report["manifest"]["feature_source_identity"][
        "base_feature_source_hashes"
    ].items():
        if baseline_sources[f"ml-service/capacity_ml/{name}"] != expected:
            raise ValueError("Measured baseline feature implementation changed")
    vendor_manifest = ROOT / "teammate-ml-service/vendor-manifest.json"
    vendor_expected = json.loads(
        (ROOT / "ml-service/reports/real-model-benchmark.json").read_bytes()
    )["artifact_identities"]["teammate"]
    if digest(vendor_manifest) != vendor_expected["vendor_manifest_sha256"]:
        raise ValueError("Measured vendor manifest changed")
    model = ForecastModel.load(baseline)
    metadata = model.public_revenue_model.metadata
    eligible = report["eligible_for_product_integration"]
    if eligible != all(report["promotion_gates"].values()):
        raise ValueError("Measured qualification is inconsistent")
    shutil.copyfile(calibration, ASSETS / "calibration.json")
    shutil.copyfile(evidence, ASSETS / "fresh-evidence.json")
    bundle = {
        "format": 1,
        "revenue_component": "improved" if eligible else "current",
        "baseline_file": "baseline.joblib",
        "baseline_sha256": digest(baseline),
        "baseline_source_hashes": baseline_sources,
        "vendor_manifest_sha256": digest(vendor_manifest),
        "native_financial_artifact_sha256": vendor_expected["model_artifact_sha256"],
        "calibration_file": "calibration.json",
        "calibration_sha256": digest(calibration),
        "calibration_source_sha256": digest(
            ROOT / "ml-service/final_model/calibration.py"
        ),
        "fresh_report_file": "fresh-evidence.json",
        "fresh_report_sha256": digest(evidence),
        "fresh_revenue_gates_passed": eligible,
        "real_training_targets": metadata["training_examples"],
        "real_training_unique_targets": metadata["training_unique_target_observations"],
        "revenue_candidate": model.public_revenue_model.selected,
        "revenue_version": model.version,
        "sources": [
            {
                key: source[key]
                for key in (
                    "publisher",
                    "title",
                    "landing_url",
                    "license",
                    "units",
                    "units_as_published",
                )
                if key in source
            }
            for source in metadata["sources"]
        ],
        "calibration_support": "Development history views >=3 months; no real expense/repayment/default labels; below-3-month grid extrapolation is disclosed and financial offer is zero.",
        "decision_scope": "Fresh revenue gate decides point forecast only; final 24% APR seasonal financial policy was separately authorized and behavior tested.",
    }
    if eligible:
        selected = report["selection"]["selected"]
        variant = selected["variant"]
        upgrade = experiment / "models" / f"{variant}.txt"
        expected = report["selection"]["model_identity"]["artifact_hashes"][variant]
        if digest(upgrade) != expected:
            raise ValueError("Selected pre-holdout model changed")
        shutil.copyfile(upgrade, ASSETS / "upgrade.txt")
        bundle.update(
            upgrade_file="upgrade.txt",
            upgrade_sha256=expected,
            upgrade_variant=variant,
            upgrade_source_identity=report["selection"]["model_identity"][
                "source_identity"
            ],
            incumbent_weight=selected["incumbent_weight"],
            real_training_targets=report["manifest"]["training"][
                "target_months_before_augmentation"
            ],
            real_training_unique_targets=report["manifest"]["training"][
                "unique_targets"
            ],
            revenue_candidate=f"qualified_real_upgrade_{variant}",
            revenue_version=f"real-upgrade-{expected[:16]}",
        )
    bundle_path = ASSETS / "bundle.json"
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    runtime_versions = {
        "fastapi": "0.143.0",
        "pydantic": "2.14.0",
        "uvicorn": "0.54.0",
        "scikit-learn": "1.9.1",
        "numpy": "2.5.3",
        "joblib": "1.6.0",
        "pandas": "3.0.6",
        "scipy": "1.17.1",
        "lightgbm": "4.7.0",
    }
    release = ROOT / "ml-service/final_model/release.py"
    release.write_text(
        '"""Exact reviewed bundle and measured local runtime dependency pins."""\n\n'
        + f'BUNDLE_SHA256 = "{digest(bundle_path)}"\n'
        + "RUNTIME_VERSIONS = {\n"
        + "".join(
            f"    {json.dumps(key)}: {json.dumps(value)},\n"
            for key, value in runtime_versions.items()
        )
        + "}\n"
    )
    print(
        json.dumps(
            {
                "component": bundle["revenue_component"],
                "bundle_sha256": digest(bundle_path),
            }
        )
    )


if __name__ == "__main__":
    main()
