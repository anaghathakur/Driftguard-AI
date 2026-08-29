from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from apps.api.app.core.workspace_context import LOCAL_WORKSPACE_ID
from apps.api.app.domain.analysis import RepositorySourceType
from apps.api.app.domain.automation import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    CheckRunConclusion,
)
from apps.api.app.domain.monitor import ApiMonitor
from apps.api.app.github.consumer_automation import ConsumerAutomationDispatcher
from apps.api.tests.test_phase18_worker import BASE_SHA, NEW_SPEC, OLD_SPEC, _setup


def _archive() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "consumer/src/payment_client.py",
            'import requests\n\ndef create_payment():\n    return requests.post("/payments")\n',
        )
    return output.getvalue()


def test_monitor_dispatch_maps_exact_connected_repository_to_durable_job(tmp_path):
    automation, workspaces, _, _, _, connection = _setup(tmp_path)
    now = datetime.now(UTC)
    monitor = ApiMonitor(
        "monitor-1", "Payments", "https://api.example/openapi.yaml",
        "https://github.com/acme/payments", "main", 60, True,
        "openapi.yaml", OLD_SPEC, "0" * 64, now, now, now,
    )
    dispatcher = ConsumerAutomationDispatcher(automation, workspaces)

    asyncio.run(dispatcher.dispatch(monitor, "analysis-1", BASE_SHA))

    jobs = automation.list_jobs(LOCAL_WORKSPACE_ID)
    assert len(jobs) == 1
    assert jobs[0].job_type is BackgroundJobType.CONSUMER_IMPACT_ANALYSIS
    assert jobs[0].payload_safe["head_sha"] == BASE_SHA
    dependencies = automation.list_dependencies(LOCAL_WORKSPACE_ID, connection.connection_id)
    assert len(dependencies) == 1
    assert dependencies[0].confirmed is True
    assert dependencies[0].evidence_type == "monitor_repository_match"


def test_consumer_job_publishes_action_required_check_from_persisted_impact(tmp_path):
    automation, _, github, worker, installation, connection = _setup(tmp_path)
    analysis = worker.pipeline.analyze_impact(
        old_filename="openapi.yaml",
        old_content=OLD_SPEC,
        new_filename="openapi.yaml",
        new_content=NEW_SPEC,
        repository_filename="consumer.zip",
        repository_content=_archive(),
        repository_source_type=RepositorySourceType.GITHUB,
        repository_url="https://github.com/acme/payments",
        repository_ref="main",
        repository_commit_sha=BASE_SHA,
    )
    automation.enqueue_job(
        BackgroundJob(
            "consumer-job", LOCAL_WORKSPACE_ID,
            BackgroundJobType.CONSUMER_IMPACT_ANALYSIS,
            BackgroundJobStatus.QUEUED,
            {
                "installation_id": installation.installation_id,
                "repository_connection_id": connection.connection_id,
                "monitor_id": "monitor-1",
                "analysis_id": analysis.analysis_id,
                "head_sha": BASE_SHA,
            },
            0, datetime.now(UTC),
        )
    )

    asyncio.run(worker.run_once())

    check = automation.list_checks(LOCAL_WORKSPACE_ID, connection.connection_id)[0]
    assert check.conclusion is CheckRunConclusion.ACTION_REQUIRED
    assert "Impacted files: 1" in check.summary
    assert check.analysis_id == analysis.analysis_id
    assert github.checks[check.github_check_run_id].name == "DriftGuard Consumer API Impact"
