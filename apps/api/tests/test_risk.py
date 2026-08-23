from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from apps.api.app.openapi.differ import ContractDiffer
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.risk.baseline import classify_with_rules
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.risk.features import FEATURE_NAMES, generate_features
from apps.api.app.risk.synthetic import generate_synthetic_dataset
from apps.api.app.schemas.comparison import ChangeType
from apps.api.app.schemas.impact import ImpactMatch, MatchConfidence, MatchKind

MODEL_DIRECTORY = Path("apps/api/models/risk/v1.0.0")


def one_change(old, new):
    return ContractDiffer().compare(normalize_openapi(old), normalize_openapi(new))[0]


def test_feature_generation_is_deterministic_and_bounded(base_spec, clone):
    new = clone(base_spec)
    new["paths"] = {}
    change = one_change(base_spec, new)
    matches = [
        ImpactMatch(
            file_path="src/client.py",
            line=1,
            column=1,
            match_kind=MatchKind.PATH_AND_METHOD,
            confidence=MatchConfidence.HIGH,
            evidence='requests.post("/payments")',
        )
    ]

    first = generate_features(change, matches)
    second = generate_features(change, matches)

    assert first == second
    assert tuple(first) == FEATURE_NAMES
    assert first["is_breaking"] == 1
    assert first["is_endpoint_removed"] == 1
    assert first["match_count_norm"] == 0.1
    assert first["impacted_files_norm"] == 0.2
    assert first["high_confidence_ratio"] == 1
    assert all(0 <= value <= 1 for value in first.values())


def test_rule_baseline_is_transparent_for_critical_and_low_changes(base_spec, clone):
    removed = clone(base_spec)
    removed["paths"] = {}
    removal = one_change(base_spec, removed)
    removal_result = classify_with_rules(removal, generate_features(removal))

    added = clone(base_spec)
    added["paths"]["/health"] = {
        "get": {"responses": {"200": {"description": "ok"}}}
    }
    addition = next(
        change
        for change in ContractDiffer().compare(
            normalize_openapi(base_spec), normalize_openapi(added)
        )
        if change.change_type == ChangeType.ENDPOINT_ADDED
    )
    addition_result = classify_with_rules(addition, generate_features(addition))

    assert removal_result.level.value == "critical"
    assert any("endpoint was removed" in reason.lower() for reason in removal_result.reasons)
    assert addition_result.level.value == "low"
    assert addition_result.score < removal_result.score


def test_synthetic_dataset_is_reproducible_and_contains_all_classes():
    first = generate_synthetic_dataset(size=500, seed=42)
    second = generate_synthetic_dataset(size=500, seed=42)
    changed_seed = generate_synthetic_dataset(size=500, seed=43)

    assert first.sha256 == second.sha256
    assert np.array_equal(first.features, second.features)
    assert np.array_equal(first.labels, second.labels)
    assert first.sha256 != changed_seed.sha256
    assert set(first.labels) == {"low", "medium", "high", "critical"}


def test_versioned_metadata_compares_both_candidate_models():
    metadata = json.loads((MODEL_DIRECTORY / "metadata.json").read_text(encoding="utf-8"))
    generated = generate_synthetic_dataset()
    artifact_hash = hashlib.sha256(
        (MODEL_DIRECTORY / "risk_model.joblib").read_bytes()
    ).hexdigest()

    assert metadata["model_version"] == "1.0.0"
    assert metadata["dataset"]["seed"] == 42
    assert metadata["dataset"]["size"] == 4000
    assert metadata["dataset"]["sha256"] == generated.sha256
    assert sum(metadata["dataset"]["class_distribution"].values()) == 4000
    assert metadata["artifact_sha256"] == artifact_hash
    assert set(metadata["metrics"]) == {"logistic_regression", "random_forest"}
    assert metadata["model_name"] == max(
        metadata["metrics"], key=lambda name: metadata["metrics"][name]["macro_f1"]
    )


def test_trained_model_returns_probabilities_and_explanations(base_spec, clone):
    new = clone(base_spec)
    new["paths"] = {}
    change = one_change(base_spec, new)
    classifier = RiskClassifier(
        MODEL_DIRECTORY / "risk_model.joblib", MODEL_DIRECTORY / "metadata.json"
    )

    prediction = classifier.predict(change, [])

    assert prediction.prediction_source.value == "model"
    assert prediction.model_version == "1.0.0"
    assert abs(sum(prediction.class_probabilities.values()) - 1) < 0.0001
    assert prediction.reasons
    assert prediction.top_drivers
    assert classifier.status().available is True


def test_missing_model_uses_safe_deterministic_fallback(base_spec, clone):
    new = clone(base_spec)
    new["paths"] = {}
    change = one_change(base_spec, new)
    classifier = RiskClassifier("missing-model.joblib", "missing-metadata.json")

    first = classifier.predict(change, [])
    second = classifier.predict(change, [])

    assert first.risk_level == second.risk_level
    assert first.risk_score == second.risk_score
    assert first.prediction_source.value == "deterministic_fallback"
    assert first.fallback_reason == "model_artifact_missing"
    assert classifier.status().available is False


def test_checksum_mismatch_uses_fallback_without_loading_artifact(
    tmp_path, base_spec, clone
):
    artifact_path = tmp_path / "tampered.joblib"
    metadata_path = tmp_path / "tampered.json"
    artifact_path.write_bytes(b"untrusted bytes that must not be deserialized")
    metadata_path.write_text(
        json.dumps(
            {
                "model_name": "test",
                "model_version": "1.0.0",
                "metrics": {},
                "artifact_sha256": "0" * 64,
                "feature_names": list(FEATURE_NAMES),
                "feature_schema_version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    try:
        new = clone(base_spec)
        new["paths"] = {}
        change = one_change(base_spec, new)
        prediction = RiskClassifier(artifact_path, metadata_path).predict(change, [])
        assert prediction.prediction_source.value == "deterministic_fallback"
        assert prediction.fallback_reason == "artifact_hash_mismatch"
    finally:
        artifact_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
