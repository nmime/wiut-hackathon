"""Research-runner validation; every generated label here is a test fixture."""

from __future__ import annotations

import json

import numpy as np
import pytest

from benchmark.real_lgb_runner import (
    VARIANT_CONFIGS,
    load_training,
    load_variants,
    main,
    predict_case,
    run,
    train_variants,
)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-real-lgb-test-only")
    generator = np.random.default_rng(119)
    features = generator.normal(size=(180, 21))
    targets = 0.15 * features[:, 0] + generator.normal(0, 0.01, size=180)
    training = root / "training.npz"
    np.savez(training, features=features, targets=targets, weights=np.ones(180))
    artifacts = root / "frozen"
    identity = train_variants(training, artifacts)
    return artifacts, identity, training


def case():
    return {
        "id": "test-only-revenue-features",
        "features": np.zeros((12, 21)).tolist(),
        "base_log": [float(np.log(1.05))] * 12,
        "scale": 100.0,
    }


def test_four_fixed_artifacts_have_identical_training_and_prediction_identity(trained):
    artifacts, trained_identity, training = trained
    loaded_identity, models = load_variants(artifacts)
    assert loaded_identity == trained_identity
    assert set(models) == set(VARIANT_CONFIGS)
    result = run(artifacts, {"cases": [case()]})
    assert result["model_identity"] == trained_identity
    assert set(result["variants"]) == set(VARIANT_CONFIGS)
    for variant in result["variants"].values():
        prediction = variant["cases"][0]
        assert prediction["status"] == "ok"
        assert np.isfinite(prediction["predictions"]["median"]).all()
        assert len(prediction["predictions"]["median"]) == 12
        assert np.min(prediction["predictions"]["median"]) >= 0
    with pytest.raises(ValueError, match="empty artifact directory"):
        train_variants(training, artifacts)


def test_frozen_model_change_fails_identity_before_inference(trained, tmp_path):
    import shutil

    artifacts, _, _ = trained
    copied = tmp_path / "copied"
    shutil.copytree(artifacts, copied)
    path = copied / f"{next(iter(VARIANT_CONFIGS))}.txt"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="identity changed"):
        load_variants(copied)


@pytest.mark.parametrize(
    "modification",
    [
        lambda value: value.update(actual=[100] * 12),
        lambda value: value.update(features=[[0] * 20] * 12),
        lambda value: value.update(base_log=[float("nan")] * 12),
        lambda value: value.update(scale=True),
        lambda value: value.update(scale=0),
    ],
)
def test_labels_and_invalid_prediction_fields_are_errors(trained, modification):
    artifacts, _, _ = trained
    _, models = load_variants(artifacts)
    value = case()
    modification(value)
    result = predict_case(next(iter(models.values())), value)
    assert result["status"] == "error"
    assert "predictions" not in result


def test_declared_residual_safety_transform_without_other_clipping():
    class ExtremeResiduals:
        def predict(self, features, num_threads):
            return np.asarray([-9, 9] * 6)

    result = predict_case(ExtremeResiduals(), case())
    expected = (
        np.maximum(np.exp(np.log(1.05) + np.asarray([-3, 3] * 6)) - 0.05, 0) * 100
    )
    assert result["status"] == "ok"
    assert result["clipped_residual_count"] == 12
    np.testing.assert_allclose(result["predictions"]["median"], expected)


def test_training_requires_only_explicit_labels_and_positive_weights(tmp_path):
    path = tmp_path / "invalid.npz"
    np.savez(
        path, features=np.zeros((10, 21)), targets=np.ones(10), weights=np.zeros(10)
    )
    with pytest.raises(ValueError, match="strictly positive"):
        load_training(path)
    np.savez(
        path,
        features=np.zeros((10, 21)),
        targets=np.ones(10),
        weights=np.ones(10),
        future=np.ones(10),
    )
    with pytest.raises(ValueError, match="only features, targets and weights"):
        load_training(path)


def test_missing_features_remain_missing_and_frozen_cli_does_not_train(
    trained, tmp_path
):
    artifacts, identity, _ = trained
    value = case()
    value["features"][0][0] = None
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps({"cases": [value]}))
    assert (
        main(
            [
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--artifact-dir",
                str(artifacts),
            ]
        )
        == 0
    )
    output = json.loads(output_path.read_text())
    assert output["model_identity"] == identity
    assert all(
        variant["cases"][0]["status"] == "ok" for variant in output["variants"].values()
    )
