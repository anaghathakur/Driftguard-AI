from __future__ import annotations

import json

from apps.api.app.core.dependencies import get_risk_classifier
from apps.api.app.main import app
from apps.api.app.risk.classifier import RiskClassifier


def upload(spec, filename="api.json"):
    return (filename, json.dumps(spec).encode(), "application/json")


def changed_spec(base_spec, clone):
    new = clone(base_spec)
    schema = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    schema = schema["application/json"]["schema"]
    schema["properties"]["customer_id"] = {"type": "string"}
    schema["required"].append("customer_id")
    return new


def test_persisted_risk_list_detail_and_pipeline(client, base_spec, clone):
    response = client.post(
        "/api/v1/specifications/compare",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(changed_spec(base_spec, clone), "new.json"),
        },
    )
    analysis_id = response.json()["analysis_id"]
    changes = client.get(f"/api/v1/analyses/{analysis_id}/changes").json()

    risks_response = client.get(f"/api/v1/analyses/{analysis_id}/risks")
    assert risks_response.status_code == 200
    risks = risks_response.json()
    assert len(risks) == 1
    assert risks[0]["change_id"] == changes[0]["change_id"]
    assert risks[0]["prediction_source"] == "model"
    assert risks[0]["model_version"] == "1.0.0"
    assert risks[0]["baseline_score"] > 0
    assert risks[0]["features"]
    assert risks[0]["reasons"]
    assert risks[0]["top_drivers"]

    detail = client.get(f"/api/v1/analyses/{analysis_id}/risks/{changes[0]['change_id']}")
    assert detail.status_code == 200
    assert detail.json() == risks[0]
    pipeline = client.get(f"/api/v1/analyses/{analysis_id}/pipeline").json()
    assert [stage["stage_name"] for stage in pipeline] == [
        "validate_and_normalize_specifications",
        "compare_contracts",
        "classify_risk",
        "generate_migration_recommendations",
        "persist_results",
    ]


def test_risk_model_status_exposes_metrics_without_training_data(client):
    response = client.get("/api/v1/risk/model")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["active_source"] == "model"
    assert set(body["metrics"]) == {"logistic_regression", "random_forest"}
    assert "dataset" not in body


def test_pipeline_persists_fallback_when_model_is_unavailable(client, base_spec, clone):
    app.dependency_overrides[get_risk_classifier] = lambda: RiskClassifier(
        "missing-model.joblib", "missing-metadata.json"
    )
    response = client.post(
        "/api/v1/specifications/compare",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(changed_spec(base_spec, clone), "new.json"),
        },
    )
    analysis_id = response.json()["analysis_id"]

    risks = client.get(f"/api/v1/analyses/{analysis_id}/risks").json()
    assert risks[0]["prediction_source"] == "deterministic_fallback"
    assert risks[0]["fallback_reason"] == "model_artifact_missing"


def test_unknown_change_risk_returns_safe_not_found(client, base_spec, clone):
    response = client.post(
        "/api/v1/specifications/compare",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(changed_spec(base_spec, clone), "new.json"),
        },
    )
    analysis_id = response.json()["analysis_id"]

    missing = client.get(f"/api/v1/analyses/{analysis_id}/risks/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "risk_prediction_not_found"
