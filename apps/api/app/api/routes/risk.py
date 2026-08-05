"""Active risk-model status endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.api.app.core.dependencies import get_risk_classifier
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.schemas.risk import RiskModelStatus

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/model", response_model=RiskModelStatus)
def get_risk_model_status(
    classifier: Annotated[RiskClassifier, Depends(get_risk_classifier)],
) -> RiskModelStatus:
    return classifier.status()
