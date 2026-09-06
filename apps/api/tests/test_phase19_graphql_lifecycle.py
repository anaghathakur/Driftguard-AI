from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from apps.api.app.domain.automation import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    CheckRunConclusion,
    ContractKind,
)
from apps.api.app.github.contracts import is_contract_candidate
from apps.api.tests.test_phase18_worker import BASE_SHA, HEAD_SHA, _pr_job, _setup
from apps.api.tests.test_phase19_graphql import (
    NEW_SCHEMA,
    OLD_SCHEMA,
    _graphql_upload,
    _repository_upload,
)


def test_graphql_patch_validation_and_report_lifecycle(client):
    repository = _repository_upload()
    impact = client.post(
        "/api/v1/impact/analyze",
        files={
            "old_spec": _graphql_upload("old.graphql", OLD_SCHEMA),
            "new_spec": _graphql_upload("new.graphql", NEW_SCHEMA),
            "repository": repository,
        },
        data={"contract_type": "graphql"},
    )
    assert impact.status_code == 200, impact.text
    analysis_id = impact.json()["analysis_id"]

    generated = client.post(
        f"/api/v1/analyses/{analysis_id}/patches",
        files={"repository": repository},
    )
    assert generated.status_code == 200, generated.text
    patch = generated.json()
    assert patch["files_changed"] == 1
    assert patch["files"][0]["file_path"] == "src/paymentClient.ts"
    assert "$customerId: ID!" in patch["unified_diff"]
    assert "customerId: $customerId" in patch["unified_diff"]
    assert "src/checkout.ts" not in patch["unified_diff"]

    validated = client.post(
        f"/api/v1/analyses/{analysis_id}/patches/{patch['patch_id']}/validations",
        files={"repository": repository},
    )
    assert validated.status_code == 200, validated.text
    validation = validated.json()
    assert validation["readiness"] in {"ready_for_review", "needs_review"}
    assert validation["static_only"] is True
    assert all(item["status"] != "fail" for item in validation["contract_findings"])

    report = client.get(f"/api/v1/analyses/{analysis_id}/report")
    assert report.status_code == 200
    report_body = report.json()
    assert {item["contract_type"] for item in report_body["changes"]} == {"graphql"}
    assert any(
        item["operation_identifier"] == "Mutation.createPayment" for item in report_body["changes"]
    )
    pdf = client.get(f"/api/v1/analyses/{analysis_id}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")


def test_graphql_contract_discovery_and_pull_request_check(tmp_path):
    automation, _, github, worker, installation, connection = _setup(tmp_path)
    path = "graphql/schema.graphql"
    github.snapshots[(connection.github_repository_id, BASE_SHA)] = {path: OLD_SCHEMA}
    github.snapshots[(connection.github_repository_id, HEAD_SHA)] = {path: NEW_SCHEMA}
    _pr_job(automation, installation, connection)

    assert asyncio.run(worker.run_once()) == 1
    job = automation.get_job("job-1", connection.workspace_id)
    assert job is not None and job.status is BackgroundJobStatus.SUCCEEDED
    contract = automation.list_contracts(connection.workspace_id, connection.connection_id)[0]
    assert contract.path == path
    assert contract.contract_kind is ContractKind.GRAPHQL
    check = automation.list_checks(connection.workspace_id, connection.connection_id)[0]
    assert check.conclusion is CheckRunConclusion.ACTION_REQUIRED
    assert "Contract type: Graphql" in check.summary
    assert "Mutation.createPayment" in check.summary
    assert [name for name, _ in github.calls].count("create_check") == 1
    assert [name for name, _ in github.calls].count("update_check") == 1


def test_graphql_consumer_impact_job_uses_existing_check_worker(tmp_path):
    automation, _, github, worker, installation, connection = _setup(tmp_path)
    repository = _repository_upload()
    analysis = worker.pipeline.analyze_impact(
        old_filename="old.graphql",
        old_content=OLD_SCHEMA,
        new_filename="new.graphql",
        new_content=NEW_SCHEMA,
        repository_filename=repository[0],
        repository_content=repository[1],
        contract_type="graphql",
    )
    automation.enqueue_job(
        BackgroundJob(
            "consumer-graphql",
            connection.workspace_id,
            BackgroundJobType.CONSUMER_IMPACT_ANALYSIS,
            BackgroundJobStatus.QUEUED,
            {
                "installation_id": installation.installation_id,
                "repository_connection_id": connection.connection_id,
                "monitor_id": "graphql-contract",
                "analysis_id": analysis.analysis_id,
                "head_sha": HEAD_SHA,
            },
            0,
            datetime.now(UTC),
        )
    )

    assert asyncio.run(worker.run_once()) == 1
    job = automation.get_job("consumer-graphql", connection.workspace_id)
    assert job is not None and job.status is BackgroundJobStatus.SUCCEEDED
    check = automation.list_checks(connection.workspace_id, connection.connection_id)[0]
    assert check.analysis_id == analysis.analysis_id
    assert check.conclusion is CheckRunConclusion.ACTION_REQUIRED
    assert check.name == "DriftGuard Consumer API Impact"
    assert [name for name, _ in github.calls].count("create_check") == 1


def test_contract_candidate_and_generic_openapi_alias_are_backward_compatible(client, base_spec):
    assert is_contract_candidate("schema.graphql")
    assert is_contract_candidate("graphql/payments.gql")
    assert not is_contract_candidate("src/query.graphql")

    content = json.dumps(base_spec).encode()
    response = client.post(
        "/api/v1/contracts/compare",
        files={
            "old_contract": ("old.json", content, "application/json"),
            "new_contract": ("new.json", content, "application/json"),
        },
        data={"contract_type": "openapi"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["old_contract"]["contract_type"] == "openapi"
    assert response.json()["summary"]["total_changes"] == 0
