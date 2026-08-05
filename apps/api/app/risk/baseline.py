"""Transparent rule-based baseline used for explanation and safe fallback."""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.risk import RiskLevel


@dataclass(frozen=True, slots=True)
class BaselineResult:
    level: RiskLevel
    score: float
    reasons: tuple[str, ...]


def classify_with_rules(change: ApiChange, features: dict[str, float]) -> BaselineResult:
    score = 10 + features["severity_score"] * 45
    reasons = [f"Contract severity is {change.severity.value}."]

    contributions = (
        ("is_breaking", 18, "The contract differ classified this change as breaking."),
        (
            "is_potentially_breaking",
            8,
            "The change is potentially breaking and requires consumer review.",
        ),
        ("is_endpoint_removed", 17, "An entire endpoint was removed."),
        ("is_method_removed", 12, "An HTTP method was removed."),
        ("is_auth_change", 16, "Authentication requirements changed."),
        ("is_required_input_added", 11, "A new required input must be supplied."),
        (
            "is_input_removed_or_renamed",
            8,
            "A request input was removed, renamed, or relocated.",
        ),
        ("is_type_change", 10, "A data type changed."),
        ("is_response_removed", 12, "A response status or field was removed."),
        ("is_enum_value_removed", 10, "An accepted enum value was removed."),
    )
    for feature, points, explanation in contributions:
        if features[feature]:
            score += points
            reasons.append(explanation)

    if features["is_non_breaking_addition"]:
        score -= 12
        reasons.append("The change is an additive, non-breaking contract expansion.")
    if features["impacted_files_norm"]:
        points = features["impacted_files_norm"] * 12
        score += points
        reasons.append("Repository usage was found in one or more source files.")
    if features["high_confidence_ratio"]:
        score += features["high_confidence_ratio"] * 5
        reasons.append("At least one repository match has high confidence.")

    bounded_score = round(max(0.0, min(100.0, score)), 2)
    return BaselineResult(
        level=level_for_score(bounded_score),
        score=bounded_score,
        reasons=tuple(reasons),
    )


def level_for_score(score: float) -> RiskLevel:
    if score < 25:
        return RiskLevel.LOW
    if score < 50:
        return RiskLevel.MEDIUM
    if score < 75:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL
