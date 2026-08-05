"""Load the versioned classifier and produce explainable, fail-safe predictions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from apps.api.app.risk.baseline import classify_with_rules
from apps.api.app.risk.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    feature_row,
    generate_features,
)
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.impact import ChangeImpact, ImpactMatch
from apps.api.app.schemas.risk import (
    PredictionSource,
    RiskDriver,
    RiskLevel,
    RiskModelStatus,
    RiskPrediction,
)

RULE_MODEL_NAME = "transparent_rule_baseline"
RULE_MODEL_VERSION = "1.0.0"
_LEVEL_SCORE = {
    RiskLevel.LOW: 12.5,
    RiskLevel.MEDIUM: 37.5,
    RiskLevel.HIGH: 62.5,
    RiskLevel.CRITICAL: 87.5,
}
_FEATURE_DESCRIPTIONS = {
    "is_breaking": "Breaking classification",
    "is_potentially_breaking": "Potentially breaking classification",
    "severity_score": "Contract severity",
    "is_endpoint_removed": "Endpoint removal",
    "is_method_removed": "HTTP method removal",
    "is_auth_change": "Authentication change",
    "is_required_input_added": "Required input addition",
    "is_input_removed_or_renamed": "Input removal, rename, or relocation",
    "is_type_change": "Data type change",
    "is_response_removed": "Response removal",
    "is_enum_value_removed": "Enum value removal",
    "is_non_breaking_addition": "Non-breaking addition",
    "match_count_norm": "Repository match volume",
    "impacted_files_norm": "Impacted file count",
    "high_confidence_ratio": "High-confidence match ratio",
    "subject_depth_norm": "Nested contract subject depth",
}


@dataclass(frozen=True, slots=True)
class LoadedModel:
    model: Any
    metadata: dict[str, Any]


class RiskClassifier:
    def __init__(self, model_path: str | Path, metadata_path: str | Path) -> None:
        self.model_path = Path(model_path)
        self.metadata_path = Path(metadata_path)
        self._load_attempted = False
        self._loaded: LoadedModel | None = None
        self._fallback_reason: str | None = None

    def predict_all(
        self,
        changes: list[ApiChange],
        impacts: list[ChangeImpact],
    ) -> list[RiskPrediction]:
        matches = {impact.change_id: impact.matches for impact in impacts}
        return [
            self.predict(change, list(matches.get(change.change_id, [])))
            for change in changes
        ]

    def predict(self, change: ApiChange, matches: list[ImpactMatch]) -> RiskPrediction:
        features = generate_features(change, matches)
        baseline = classify_with_rules(change, features)
        loaded = self._load()
        if loaded is None:
            return self._fallback_prediction(change, features, baseline)
        try:
            row = np.asarray([feature_row(features)], dtype=np.float64)
            probabilities_raw = loaded.model.predict_proba(row)[0]
            classes = [RiskLevel(value) for value in loaded.model.classes_]
            probabilities = {
                level: round(
                    float(probabilities_raw[classes.index(level)])
                    if level in classes
                    else 0.0,
                    6,
                )
                for level in RiskLevel
            }
            predicted_level = max(probabilities, key=probabilities.get)
            score = round(
                sum(probabilities[level] * _LEVEL_SCORE[level] for level in RiskLevel),
                2,
            )
            metadata = loaded.metadata
            return RiskPrediction(
                change_id=change.change_id,
                risk_level=predicted_level,
                risk_score=score,
                prediction_source=PredictionSource.MODEL,
                model_name=str(metadata["model_name"]),
                model_version=str(metadata["model_version"]),
                baseline_level=baseline.level,
                baseline_score=baseline.score,
                class_probabilities=probabilities,
                features=features,
                reasons=[
                    *baseline.reasons,
                    "The ML classification is reported with its class probabilities and drivers.",
                ],
                top_drivers=_model_drivers(loaded.model, predicted_level, features),
                predicted_at=datetime.now(UTC),
            )
        except Exception:
            self._fallback_reason = "model_prediction_failed"
            return self._fallback_prediction(change, features, baseline)

    def status(self) -> RiskModelStatus:
        loaded = self._load()
        if loaded is None:
            return RiskModelStatus(
                available=False,
                active_source=PredictionSource.DETERMINISTIC_FALLBACK,
                model_name=RULE_MODEL_NAME,
                model_version=RULE_MODEL_VERSION,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                metrics={},
                fallback_reason=self._fallback_reason,
            )
        metadata = loaded.metadata
        return RiskModelStatus(
            available=True,
            active_source=PredictionSource.MODEL,
            model_name=str(metadata["model_name"]),
            model_version=str(metadata["model_version"]),
            feature_schema_version=str(metadata["feature_schema_version"]),
            artifact_sha256=str(metadata["artifact_sha256"]),
            metrics=metadata["metrics"],
        )

    def _load(self) -> LoadedModel | None:
        if self._load_attempted:
            return self._loaded
        self._load_attempted = True
        if not self.model_path.is_file() or not self.metadata_path.is_file():
            self._fallback_reason = "model_artifact_missing"
            return None
        try:
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if not _valid_metadata(metadata):
                self._fallback_reason = "model_metadata_invalid"
                return None
            expected_hash = metadata["artifact_sha256"]
            actual_hash = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                self._fallback_reason = "artifact_hash_mismatch"
                return None
            if (
                tuple(metadata["feature_names"]) != FEATURE_NAMES
                or metadata["feature_schema_version"] != FEATURE_SCHEMA_VERSION
            ):
                self._fallback_reason = "feature_schema_mismatch"
                return None
            bundle = joblib.load(self.model_path)
            if (
                tuple(bundle["feature_names"]) != FEATURE_NAMES
                or bundle["model_version"] != metadata["model_version"]
                or bundle["model_name"] != metadata["model_name"]
            ):
                self._fallback_reason = "model_metadata_mismatch"
                return None
            self._loaded = LoadedModel(model=bundle["model"], metadata=metadata)
        except Exception:
            self._fallback_reason = "model_load_failed"
        return self._loaded

    def _fallback_prediction(self, change, features, baseline) -> RiskPrediction:
        probabilities = {
            level: float(level == baseline.level) for level in RiskLevel
        }
        return RiskPrediction(
            change_id=change.change_id,
            risk_level=baseline.level,
            risk_score=baseline.score,
            prediction_source=PredictionSource.DETERMINISTIC_FALLBACK,
            model_name=RULE_MODEL_NAME,
            model_version=RULE_MODEL_VERSION,
            baseline_level=baseline.level,
            baseline_score=baseline.score,
            class_probabilities=probabilities,
            features=features,
            reasons=list(baseline.reasons),
            top_drivers=_fallback_drivers(features),
            fallback_reason=self._fallback_reason,
            predicted_at=datetime.now(UTC),
        )


def _model_drivers(model, predicted_level, features) -> list[RiskDriver]:
    row = np.asarray(feature_row(features), dtype=np.float64)
    classifier = model.named_steps["classifier"]
    if hasattr(classifier, "coef_"):
        transformed = model.named_steps["scaler"].transform([row])[0]
        class_values = [RiskLevel(value) for value in classifier.classes_]
        class_index = class_values.index(predicted_level)
        influences = classifier.coef_[class_index] * transformed
    else:
        influences = classifier.feature_importances_ * np.abs(row)
    ranked = sorted(
        zip(FEATURE_NAMES, row, influences, strict=True),
        key=lambda item: abs(float(item[2])),
        reverse=True,
    )
    return [
        RiskDriver(
            feature=name,
            value=round(float(value), 6),
            influence=round(float(influence), 6),
            description=_FEATURE_DESCRIPTIONS[name],
        )
        for name, value, influence in ranked[:5]
    ]


def _fallback_drivers(features: dict[str, float]) -> list[RiskDriver]:
    weights = {
        "severity_score": 45,
        "is_breaking": 18,
        "is_endpoint_removed": 17,
        "is_auth_change": 16,
        "is_method_removed": 12,
        "is_response_removed": 12,
        "impacted_files_norm": 12,
        "is_required_input_added": 11,
        "is_type_change": 10,
        "is_enum_value_removed": 10,
        "is_input_removed_or_renamed": 8,
        "is_potentially_breaking": 8,
        "high_confidence_ratio": 5,
        "subject_depth_norm": 3,
        "is_non_breaking_addition": -12,
        "match_count_norm": 0,
    }
    ranked = sorted(
        (
            (name, value, weights[name] * value)
            for name, value in features.items()
            if value
        ),
        key=lambda item: abs(item[2]),
        reverse=True,
    )
    return [
        RiskDriver(
            feature=name,
            value=round(value, 6),
            influence=round(influence, 6),
            description=_FEATURE_DESCRIPTIONS[name],
        )
        for name, value, influence in ranked[:5]
    ]


def _valid_metadata(metadata: Any) -> bool:
    return (
        isinstance(metadata, dict)
        and isinstance(metadata.get("model_name"), str)
        and isinstance(metadata.get("model_version"), str)
        and isinstance(metadata.get("metrics"), dict)
        and isinstance(metadata.get("artifact_sha256"), str)
        and len(metadata["artifact_sha256"]) == 64
        and isinstance(metadata.get("feature_names"), list)
        and isinstance(metadata.get("feature_schema_version"), str)
    )
