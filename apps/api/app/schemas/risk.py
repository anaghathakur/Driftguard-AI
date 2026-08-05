"""Public schemas for explainable risk predictions and model status."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PredictionSource(StrEnum):
    MODEL = "model"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class RiskDriver(BaseModel):
    feature: str
    value: float
    influence: float
    description: str


class RiskPrediction(BaseModel):
    analysis_id: str | None = None
    change_id: str
    risk_level: RiskLevel
    risk_score: float = Field(ge=0, le=100)
    prediction_source: PredictionSource
    model_name: str
    model_version: str
    baseline_level: RiskLevel
    baseline_score: float = Field(ge=0, le=100)
    class_probabilities: dict[RiskLevel, float]
    features: dict[str, float]
    reasons: list[str]
    top_drivers: list[RiskDriver]
    fallback_reason: str | None = None
    predicted_at: datetime


class RiskModelStatus(BaseModel):
    available: bool
    active_source: PredictionSource
    model_name: str
    model_version: str
    feature_schema_version: str
    artifact_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    metrics: dict[str, dict[str, float]]
    fallback_reason: str | None = None
