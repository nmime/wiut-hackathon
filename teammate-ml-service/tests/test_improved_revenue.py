"""Synthetic-only checks of feature isolation and frozen experimental inference."""

from __future__ import annotations

import copy
import json
import shutil

import numpy as np
import pytest

from benchmark.improved_revenue import (
    ANCHORS,
    BASELINES,
    EXTRA_FEATURE_NAMES,
    FEATURE_COUNT,
    VARIANT_CONFIGS,
    enriched_features,
    load_models,
    load_training,
    make_prediction_case,
    predict_case,
    run,
    train,
)


def history(count=36, scale=1.0, shift=0):
    months = np.arange(2024 * 12 - count, 2024 * 12) + shift
    values = scale * (100 + 15 * np.sin(np.arange(count) * 2 * np.pi / 12))
    base_features = np.ones((12, 21))
    baselines = {name: np.linspace(95, 105, 12) * scale for name in BASELINES}
    return months, values, 2024 * 12 + shift, base_features, baselines


def prepared(count=36):
    return make_prediction_case("test-only-improved-revenue", *history(count))


def test_history_features_are_shift_and_scale_invariant():
    first, scale = enriched_features(*history())
    shifted, shifted_scale = enriched_features(*history(shift=5))
    scaled, other_scale = enriched_features(*history(scale=1e6))
    np.testing.assert_allclose(first, shifted, equal_nan=True, rtol=1e-12)
    np.testing.assert_allclose(first, scaled, equal_nan=True, rtol=1e-12, atol=1e-12)
    assert scale == shifted_scale
    assert other_scale == pytest.approx(scale * 1e6)
    assert first.shape == (12, FEATURE_COUNT)


def test_three_month_history_uses_unknown_seasonal_evidence_and_json_null():
    case = prepared(count=3)
    seasonal_growth = 21 + EXTRA_FEATURE_NAMES.index("target_same_month_log_growth")
    assert all(row[seasonal_growth] is None for row in case["features"])
    json.dumps(case, allow_nan=False)
    assert set(case["normalized_baselines"]) == set(ANCHORS)


def test_feature_construction_rejects_unobserved_calendar_and_invented_rows():
    months, values, start, base, baselines = history()
    months[3] += 1
    with pytest.raises(ValueError, match="continuous"):
        enriched_features(months, values, start, base, baselines)
    with pytest.raises(ValueError, match="immediately follow"):
        enriched_features(*history()[:2], start + 1, base, baselines)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("improved-synthetic-fixtures-only")
    generator = np.random.default_rng(129)
    features = generator.normal(size=(180, FEATURE_COUNT))
    targets = 1 + 0.15 * features[:, 0]
    targets = np.maximum(targets, 0)
    baselines = np.ones((180, 2))
    path = root / "training.npz"
    np.savez(
        path,
        features=features,
        normalized_targets=targets,
        normalized_baselines=baselines,
        weights=np.ones(180),
    )
    data_manifest = root / "data.json"
    data_manifest.write_text(json.dumps({"source": "test-only-synthetic-fixture"}))
    artifacts = root / "models"
    identity = train(path, artifacts, data_manifest)
    return artifacts, identity, path


def test_fixed_eight_configs_and_train_once_frozen_identity(trained):
    artifacts, identity, path = trained
    assert len(VARIANT_CONFIGS) == 8
    assert {config["num_boost_round"] for config in VARIANT_CONFIGS.values()} == {400}
    loaded, models = load_models(artifacts)
    assert identity == loaded
    assert set(models) == set(VARIANT_CONFIGS)
    assert identity["training_data_manifest_sha256"]
    output = run(artifacts, {"cases": [prepared()]})
    assert all(row["cases"][0]["status"] == "ok" for row in output["variants"].values())
    with pytest.raises(ValueError, match="empty artifact directory"):
        train(path, artifacts)


def test_selected_inference_evaluates_only_one_frozen_variant(trained):
    artifacts, identity, _ = trained
    name = next(iter(VARIANT_CONFIGS))
    selected = run(artifacts, {"cases": [prepared(count=3)]}, name)
    assert selected["model_identity"] == identity
    assert set(selected["variants"]) == {name}
    assert selected["selected_variant_only"] == name
    assert selected["variants"][name]["cases"][0]["status"] == "ok"


def test_altered_frozen_model_is_rejected_before_prediction(trained, tmp_path):
    artifacts, _, _ = trained
    copied = tmp_path / "copy"
    shutil.copytree(artifacts, copied)
    path = copied / f"{next(iter(VARIANT_CONFIGS))}.txt"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="bytes changed"):
        load_models(copied)


@pytest.mark.parametrize(
    "objective,bound", [("log_residual", 3), ("linear_residual", 5)]
)
def test_objective_specific_declared_reconstruction(objective, bound):
    class ExtremeModel:
        def predict(self, features, num_threads):
            return np.asarray([-10, 10] * 6)

    case = prepared()
    config = {"anchor": "damped_seasonal", "objective_transform": objective}
    result = predict_case(ExtremeModel(), config, case)
    residual = np.asarray([-bound, bound] * 6)
    base = np.asarray(case["normalized_baselines"]["damped_seasonal"])
    expected = (
        np.maximum(np.exp(np.log(base + 0.05) + residual) - 0.05, 0)
        if objective == "log_residual"
        else np.maximum(base + residual, 0)
    )
    assert result["status"] == "ok"
    assert result["clipped_residual_count"] == 12
    np.testing.assert_allclose(
        result["predictions"]["median"], expected * case["scale"]
    )


def test_prediction_forbids_labels_and_does_not_mutate_inputs(trained):
    artifacts, _, _ = trained
    _, models = load_models(artifacts)
    name, model = next(iter(models.items()))
    case = prepared()
    original = copy.deepcopy(case)
    assert predict_case(model, VARIANT_CONFIGS[name], case)["status"] == "ok"
    assert case == original
    case["actual"] = [100] * 12
    result = predict_case(model, VARIANT_CONFIGS[name], case)
    assert result["status"] == "error"
    assert "future labels" in result["reason"]["detail"]
    assert "predictions" not in result


def test_training_schema_requires_real_targets_and_positive_weights(tmp_path):
    path = tmp_path / "invalid.npz"
    np.savez(
        path,
        features=np.zeros((10, FEATURE_COUNT)),
        normalized_targets=np.ones(10),
        normalized_baselines=np.ones((10, 2)),
        weights=np.zeros(10),
    )
    with pytest.raises(ValueError, match="strictly positive"):
        load_training(path)
