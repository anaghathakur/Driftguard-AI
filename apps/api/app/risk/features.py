"""Deterministic feature generation for individual API changes."""

from __future__ import annotations

from apps.api.app.schemas.comparison import ApiChange, ChangeCategory, ChangeType, Severity
from apps.api.app.schemas.impact import ImpactMatch

FEATURE_SCHEMA_VERSION = "1.0.0"
FEATURE_NAMES = (
    "is_breaking",
    "is_potentially_breaking",
    "severity_score",
    "is_endpoint_removed",
    "is_method_removed",
    "is_auth_change",
    "is_required_input_added",
    "is_input_removed_or_renamed",
    "is_type_change",
    "is_response_removed",
    "is_enum_value_removed",
    "is_non_breaking_addition",
    "match_count_norm",
    "impacted_files_norm",
    "high_confidence_ratio",
    "subject_depth_norm",
)

_SEVERITY_SCORE = {
    Severity.LOW: 0.0,
    Severity.MEDIUM: 1 / 3,
    Severity.HIGH: 2 / 3,
    Severity.CRITICAL: 1.0,
}
_AUTH_CHANGES = {ChangeType.AUTHENTICATION_ADDED, ChangeType.AUTHENTICATION_CHANGED}
_REQUIRED_INPUT = {
    ChangeType.REQUIRED_PARAMETER_ADDED,
    ChangeType.REQUIRED_REQUEST_FIELD_ADDED,
    ChangeType.REQUIRED_ARGUMENT_ADDED,
    ChangeType.REQUIRED_INPUT_FIELD_ADDED,
}
_INPUT_REMOVED_OR_RENAMED = {
    ChangeType.PARAMETER_REMOVED,
    ChangeType.PARAMETER_RENAMED,
    ChangeType.PARAMETER_LOCATION_CHANGED,
    ChangeType.REQUEST_FIELD_REMOVED,
    ChangeType.ARGUMENT_REMOVED,
    ChangeType.INPUT_FIELD_REMOVED,
}
_TYPE_CHANGES = {
    ChangeType.PARAMETER_TYPE_CHANGED,
    ChangeType.REQUEST_FIELD_TYPE_CHANGED,
    ChangeType.RESPONSE_FIELD_TYPE_CHANGED,
    ChangeType.GRAPHQL_INPUT_TYPE_CHANGED,
    ChangeType.GRAPHQL_RETURN_TYPE_CHANGED,
    ChangeType.NULLABILITY_TIGHTENED,
    ChangeType.NULLABILITY_RELAXED,
}
_RESPONSE_REMOVED = {
    ChangeType.RESPONSE_STATUS_REMOVED,
    ChangeType.RESPONSE_FIELD_REMOVED,
}
_NON_BREAKING_ADDITIONS = {
    ChangeType.ENDPOINT_ADDED,
    ChangeType.HTTP_METHOD_ADDED,
    ChangeType.OPTIONAL_PARAMETER_ADDED,
    ChangeType.REQUEST_FIELD_ADDED,
    ChangeType.RESPONSE_STATUS_ADDED,
    ChangeType.RESPONSE_FIELD_ADDED,
    ChangeType.ENUM_VALUE_ADDED,
    ChangeType.TYPE_ADDED,
    ChangeType.FIELD_ADDED,
    ChangeType.ARGUMENT_ADDED,
    ChangeType.INPUT_FIELD_ADDED,
    ChangeType.NULLABILITY_RELAXED,
}


def generate_features(
    change: ApiChange, matches: list[ImpactMatch] | tuple[ImpactMatch, ...] = ()
) -> dict[str, float]:
    impacted_files = {match.file_path for match in matches}
    high_confidence = sum(match.confidence.value == "high" for match in matches)
    match_count = len(matches)
    subject_depth = (change.subject or "").count(".")
    values = {
        "is_breaking": float(change.breaking),
        "is_potentially_breaking": float(change.category == ChangeCategory.POTENTIALLY_BREAKING),
        "severity_score": _SEVERITY_SCORE[change.severity],
        "is_endpoint_removed": float(change.change_type == ChangeType.ENDPOINT_REMOVED),
        "is_method_removed": float(change.change_type == ChangeType.HTTP_METHOD_REMOVED),
        "is_auth_change": float(change.change_type in _AUTH_CHANGES),
        "is_required_input_added": float(change.change_type in _REQUIRED_INPUT),
        "is_input_removed_or_renamed": float(change.change_type in _INPUT_REMOVED_OR_RENAMED),
        "is_type_change": float(change.change_type in _TYPE_CHANGES),
        "is_response_removed": float(change.change_type in _RESPONSE_REMOVED),
        "is_enum_value_removed": float(change.change_type == ChangeType.ENUM_VALUE_REMOVED),
        "is_non_breaking_addition": float(change.change_type in _NON_BREAKING_ADDITIONS),
        "match_count_norm": min(match_count, 10) / 10,
        "impacted_files_norm": min(len(impacted_files), 5) / 5,
        "high_confidence_ratio": high_confidence / match_count if match_count else 0.0,
        "subject_depth_norm": min(subject_depth, 4) / 4,
    }
    return {name: float(values[name]) for name in FEATURE_NAMES}


def feature_row(features: dict[str, float]) -> list[float]:
    return [features[name] for name in FEATURE_NAMES]
