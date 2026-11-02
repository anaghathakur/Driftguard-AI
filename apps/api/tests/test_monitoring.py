from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.monitor import (
    ApiMonitor,
    ContractSourceType,
    MonitorCheckRecord,
    MonitorCheckStatus,
)
from apps.api.app.monitoring.scheduler import MonitorScheduler
from apps.api.app.monitoring.service import ApiMonitorService, MonitorCheckService
from apps.api.app.monitoring.specification_source import RemoteSpecification
from apps.api.app.ports.monitor_repository import ApiMonitorRepository
from apps.api.app.repository.github_source import GitHubRepositoryArchive
from apps.api.app.schemas.monitor import MonitorCreateRequest, MonitorUpdateRequest

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def spec(version: str) -> RemoteSpecification:
    content = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Payments", "version": version},
            "paths": {},
        }
    ).encode()
    return RemoteSpecification(
        source_url="https://api.example.com/openapi.json",
        filename="openapi.json",
        content_type="application/json",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


class MemoryMonitorRepository(ApiMonitorRepository):
    def __init__(self) -> None:
        self.monitors: dict[str, ApiMonitor] = {}
        self.checks: dict[str, list[MonitorCheckRecord]] = {}

    def initialize(self) -> None:
        return None

    def create(self, monitor: ApiMonitor) -> None:
        self.monitors[monitor.monitor_id] = monitor

    def save(self, monitor: ApiMonitor) -> None:
        self.monitors[monitor.monitor_id] = monitor

    def get(self, monitor_id: str) -> ApiMonitor | None:
        return self.monitors.get(monitor_id)

    def list(self) -> list[ApiMonitor]:
        return sorted(self.monitors.values(), key=lambda item: item.created_at, reverse=True)

    def list_due(self, now: datetime) -> list[ApiMonitor]:
        return [
            monitor
            for monitor in self.list()
            if monitor.enabled
            and (monitor.last_checked_at or monitor.created_at)
            + timedelta(minutes=monitor.check_interval_minutes)
            <= now
        ]

    def delete(self, monitor_id: str) -> bool:
        if monitor_id not in self.monitors:
            return False
        del self.monitors[monitor_id]
        self.checks.pop(monitor_id, None)
        return True

    def start_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        self.save(monitor)
        self.checks.setdefault(monitor.monitor_id, []).append(check)

    def finish_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        self.save(monitor)
        records = self.checks[monitor.monitor_id]
        records[-1] = check

    def list_checks(self, monitor_id: str) -> list[MonitorCheckRecord]:
        return list(reversed(self.checks.get(monitor_id, [])))


class FakeSpecificationSource:
    def __init__(self, *specifications: RemoteSpecification) -> None:
        self.specifications = list(specifications)
        self.calls: list[str] = []

    async def fetch(self, url: str) -> RemoteSpecification:
        self.calls.append(url)
        if len(self.specifications) > 1:
            return self.specifications.pop(0)
        return self.specifications[0]


class FakeGitHubSource:
    def __init__(self, *, failure: DriftGuardError | None = None) -> None:
        self.failure = failure
        self.calls = 0

    async def fetch(self, repository_url: str, ref: str | None = None):
        self.calls += 1
        if self.failure is not None:
            failure = self.failure
            self.failure = None
            raise failure
        return GitHubRepositoryArchive(
            owner="example",
            repository="client",
            ref=ref,
            filename="github-example-client-default.zip",
            content=b"valid archive bytes for fake pipeline",
        )


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze_impact(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(analysis_id="analysis-1")

    def compare(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(analysis_id="comparison-1")


def monitor(baseline: RemoteSpecification, **updates) -> ApiMonitor:
    value = ApiMonitor(
        monitor_id="monitor-1",
        name="Payments API",
        specification_url="https://api.example.com/openapi.json",
        repository_url="https://github.com/example/client",
        repository_ref=None,
        check_interval_minutes=60,
        enabled=True,
        baseline_filename=baseline.filename,
        baseline_content=baseline.content,
        baseline_sha256=baseline.sha256,
        baseline_observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    return replace(value, **updates)


def test_monitor_creation_fetches_and_persists_baseline_without_analysis():
    repository = MemoryMonitorRepository()
    source = FakeSpecificationSource(spec("1.0.0"))
    service = ApiMonitorService(repository, source, clock=lambda: NOW)

    response = asyncio.run(
        service.create(
            MonitorCreateRequest(
                name=" Payments API ",
                specification_url="https://api.example.com/openapi.json",
                repository_url="https://github.com/example/client.git",
                check_interval_minutes=60,
            )
        )
    )

    stored = repository.get(response.monitor_id)
    assert response.name == "Payments API"
    assert response.repository_url == "https://github.com/example/client"
    assert stored is not None
    assert stored.baseline_content == spec("1.0.0").content
    assert response.baseline_sha256 == spec("1.0.0").sha256
    assert repository.list_checks(response.monitor_id) == []


def test_specification_url_update_establishes_a_new_baseline_without_check():
    repository = MemoryMonitorRepository()
    repository.create(monitor(spec("1.0.0")))
    source = FakeSpecificationSource(spec("2.0.0"))
    service = ApiMonitorService(repository, source, clock=lambda: NOW + timedelta(hours=1))

    response = asyncio.run(
        service.update(
            "monitor-1",
            MonitorUpdateRequest(specification_url="https://new.example.com/openapi.json"),
        )
    )

    assert response.baseline_sha256 == spec("2.0.0").sha256
    assert response.specification_url == "https://new.example.com/openapi.json"
    assert response.last_check_status is None
    assert repository.list_checks("monitor-1") == []


def test_unchanged_check_skips_github_and_analysis_pipeline():
    repository = MemoryMonitorRepository()
    repository.create(monitor(spec("1.0.0")))
    github = FakeGitHubSource()
    pipeline = FakePipeline()
    service = MonitorCheckService(
        repository,
        FakeSpecificationSource(spec("1.0.0")),
        github,
        pipeline,
        clock=lambda: NOW + timedelta(hours=1),
    )

    response = asyncio.run(service.check("monitor-1"))

    assert response.status == MonitorCheckStatus.UNCHANGED
    assert github.calls == 0
    assert pipeline.calls == []
    assert repository.get("monitor-1").baseline_sha256 == spec("1.0.0").sha256


def test_changed_check_uses_github_pipeline_and_advances_baseline():
    repository = MemoryMonitorRepository()
    repository.create(monitor(spec("1.0.0")))
    github = FakeGitHubSource()
    pipeline = FakePipeline()
    service = MonitorCheckService(
        repository,
        FakeSpecificationSource(spec("2.0.0")),
        github,
        pipeline,
        clock=lambda: NOW + timedelta(hours=1),
    )

    response = asyncio.run(service.check("monitor-1"))
    stored = repository.get("monitor-1")

    assert response.status == MonitorCheckStatus.CHANGED
    assert response.analysis_id == "analysis-1"
    assert github.calls == 1
    assert pipeline.calls[0]["old_content"] == spec("1.0.0").content
    assert pipeline.calls[0]["new_content"] == spec("2.0.0").content
    assert stored.baseline_sha256 == spec("2.0.0").sha256
    assert stored.last_successful_analysis_id == "analysis-1"


def test_changed_contract_without_repository_persists_comparison_only():
    repository = MemoryMonitorRepository()
    repository.create(monitor(spec("1.0.0"), repository_url=""))
    github = FakeGitHubSource()
    pipeline = FakePipeline()
    service = MonitorCheckService(
        repository,
        FakeSpecificationSource(spec("2.0.0")),
        github,
        pipeline,
        clock=lambda: NOW + timedelta(hours=1),
    )

    response = asyncio.run(service.check("monitor-1"))

    assert response.status == MonitorCheckStatus.CHANGED
    assert response.analysis_id == "comparison-1"
    assert github.calls == 0
    assert "repository_content" not in pipeline.calls[0]
    assert repository.get("monitor-1").last_successful_analysis_id == "comparison-1"


def test_github_file_subscription_uses_connected_repository_source_at_baseline():
    repository = MemoryMonitorRepository()
    source = FakeSpecificationSource(spec("1.0.0"))
    connected_repository = SimpleNamespace(html_url="https://github.com/acme/payments")

    class GitHubFileSource:
        calls: list[tuple[str, str, str | None]] = []

        async def fetch(self, connection_id: str, path: str, ref: str | None):
            self.calls.append((connection_id, path, ref))
            return SimpleNamespace(
                specification=spec("1.0.0"),
                repository=connected_repository,
                commit_sha="a" * 40,
            )

    github_file_source = GitHubFileSource()
    service = ApiMonitorService(
        repository,
        source,
        github_file_source,
        clock=lambda: NOW,
    )

    response = asyncio.run(
        service.create(
            MonitorCreateRequest(
                name="Payments schema",
                source_type=ContractSourceType.GITHUB_FILE,
                source_path="contracts/payment.graphql",
                repository_connection_id="connection-1",
                check_interval_minutes=60,
            )
        )
    )

    assert github_file_source.calls == [
        ("connection-1", "contracts/payment.graphql", None)
    ]
    assert response.source_type is ContractSourceType.GITHUB_FILE
    assert response.repository_url == "https://github.com/acme/payments"
    assert response.repository_ref is None
    assert response.contract_type.value == "openapi"


def test_github_file_check_keeps_branch_ref_but_records_immutable_analysis_commit():
    repository = MemoryMonitorRepository()
    repository.create(
        monitor(
            spec("1.0.0"),
            source_type=ContractSourceType.GITHUB_FILE,
            source_path="contracts/openapi.yaml",
            repository_connection_id="connection-1",
            repository_url="https://github.com/acme/payments",
            repository_ref="main",
        )
    )
    connected_repository = SimpleNamespace(html_url="https://github.com/acme/payments")

    class GitHubFileSource:
        calls: list[tuple[str, str, str | None]] = []

        async def fetch(self, connection_id: str, path: str, ref: str | None):
            self.calls.append((connection_id, path, ref))
            return SimpleNamespace(
                specification=spec("2.0.0"),
                repository=connected_repository,
                commit_sha="b" * 40,
            )

        async def fetch_repository(self, _repository, commit_sha: str):
            assert commit_sha == "b" * 40
            return GitHubRepositoryArchive(
                owner="acme",
                repository="payments",
                ref="main",
                filename="payments.zip",
                content=b"archive",
                commit_sha=commit_sha,
            )

    github_file_source = GitHubFileSource()
    pipeline = FakePipeline()
    service = MonitorCheckService(
        repository,
        FakeSpecificationSource(spec("1.0.0")),
        FakeGitHubSource(),
        pipeline,
        github_file_source,
        clock=lambda: NOW + timedelta(hours=1),
    )

    response = asyncio.run(service.check("monitor-1"))

    assert response.status is MonitorCheckStatus.CHANGED
    assert github_file_source.calls == [("connection-1", "contracts/openapi.yaml", "main")]
    assert pipeline.calls[0]["repository_commit_sha"] == "b" * 40
    assert repository.get("monitor-1").repository_ref == "main"


def test_failed_changed_check_preserves_baseline_and_can_retry():
    repository = MemoryMonitorRepository()
    repository.create(monitor(spec("1.0.0")))
    github = FakeGitHubSource(
        failure=DriftGuardError(
            code="github_timeout",
            message="GitHub timed out.",
            status_code=504,
        )
    )
    pipeline = FakePipeline()
    service = MonitorCheckService(
        repository,
        FakeSpecificationSource(spec("2.0.0")),
        github,
        pipeline,
        clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(DriftGuardError) as error:
        asyncio.run(service.check("monitor-1"))

    assert error.value.code == "github_timeout"
    assert repository.get("monitor-1").baseline_sha256 == spec("1.0.0").sha256
    assert repository.list_checks("monitor-1")[0].status == MonitorCheckStatus.FAILED

    retry = asyncio.run(service.check("monitor-1"))
    assert retry.status == MonitorCheckStatus.CHANGED
    assert github.calls == 2
    assert repository.get("monitor-1").baseline_sha256 == spec("2.0.0").sha256


def test_overlapping_check_for_same_monitor_is_rejected():
    async def exercise():
        repository = MemoryMonitorRepository()
        repository.create(monitor(spec("1.0.0")))
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingSource:
            async def fetch(self, _url: str):
                started.set()
                await release.wait()
                return spec("1.0.0")

        service = MonitorCheckService(
            repository,
            BlockingSource(),
            FakeGitHubSource(),
            FakePipeline(),
            clock=lambda: NOW + timedelta(hours=1),
        )
        first = asyncio.create_task(service.check("monitor-1"))
        await started.wait()
        with pytest.raises(DriftGuardError) as error:
            await service.check("monitor-1")
        assert error.value.code == "monitor_check_in_progress"
        release.set()
        assert (await first).status == MonitorCheckStatus.UNCHANGED

    asyncio.run(exercise())


def test_sqlite_monitor_repository_crud_due_and_history(analysis_repository):
    from apps.api.app.infrastructure.sqlite_monitor_repository import (
        SQLiteMonitorRepository,
    )

    repository = SQLiteMonitorRepository(analysis_repository.database_path)
    repository.initialize()
    stored = monitor(spec("1.0.0"), created_at=NOW - timedelta(hours=2))
    repository.create(stored)

    assert repository.get("monitor-1") == stored
    assert repository.list_due(NOW) == [stored]

    check = MonitorCheckRecord(
        check_id="check-1",
        monitor_id="monitor-1",
        status=MonitorCheckStatus.CHECKING,
        checked_at=NOW,
        completed_at=None,
        duration_ms=None,
        previous_spec_hash=stored.baseline_sha256,
        observed_spec_hash=None,
        analysis_id=None,
        error_code=None,
        error_message=None,
    )
    repository.start_check(replace(stored, last_check_status=MonitorCheckStatus.CHECKING), check)
    finished = replace(
        check,
        status=MonitorCheckStatus.UNCHANGED,
        completed_at=NOW,
        duration_ms=5,
        observed_spec_hash=stored.baseline_sha256,
    )
    repository.finish_check(
        replace(stored, last_checked_at=NOW, last_check_status=MonitorCheckStatus.UNCHANGED),
        finished,
    )

    assert repository.list_checks("monitor-1") == [finished]
    assert repository.list_due(NOW) == []
    assert repository.delete("monitor-1") is True
    assert repository.get("monitor-1") is None


def test_sqlite_monitor_check_lease_allows_one_worker_and_recovers_after_expiry(
    analysis_repository,
):
    from apps.api.app.infrastructure.sqlite_monitor_repository import (
        SQLiteMonitorRepository,
    )

    repository = SQLiteMonitorRepository(analysis_repository.database_path)
    repository.initialize()
    stored = monitor(spec("1.0.0"))
    repository.create(stored)

    first = repository.claim_check(
        stored.monitor_id,
        now=NOW,
        lease_expires_at=NOW + timedelta(minutes=15),
    )
    assert first is not None
    assert first.check_lease_expires_at == NOW + timedelta(minutes=15)
    assert (
        repository.claim_check(
            stored.monitor_id,
            now=NOW + timedelta(minutes=1),
            lease_expires_at=NOW + timedelta(minutes=16),
        )
        is None
    )

    recovered = repository.claim_check(
        stored.monitor_id,
        now=NOW + timedelta(minutes=16),
        lease_expires_at=NOW + timedelta(minutes=31),
    )
    assert recovered is not None
    assert recovered.check_lease_expires_at == NOW + timedelta(minutes=31)


def test_firestore_monitor_repository_chunks_baseline_and_updates_check_atomically(monkeypatch):
    from apps.api.app.infrastructure import firestore_monitor_repository as module
    from apps.api.app.infrastructure.firestore_monitor_repository import (
        FirestoreMonitorRepository,
    )

    monkeypatch.setattr(module.firestore, "transactional", lambda function: function)

    class Snapshot:
        def __init__(self, reference, data):
            self.reference = reference
            self._data = data
            self.exists = data is not None

        def to_dict(self):
            return self._data

    class Document:
        def __init__(self, client, path):
            self.client = client
            self.path = path

        def get(self, transaction=None):
            return Snapshot(self, self.client.data.get(self.path))

        def collection(self, name):
            return Collection(self.client, (*self.path, name))

    class Collection:
        def __init__(self, client, path):
            self.client = client
            self.path = path
            self.order_field = None
            self.reverse = False

        def document(self, name):
            return Document(self.client, (*self.path, name))

        def order_by(self, field, direction=None):
            self.order_field = field
            self.reverse = "DESC" in str(direction)
            return self

        def stream(self):
            snapshots = [
                Snapshot(Document(self.client, path), data)
                for path, data in self.client.data.items()
                if len(path) == len(self.path) + 1 and path[:-1] == self.path
            ]
            if self.order_field:
                snapshots.sort(
                    key=lambda snapshot: snapshot.to_dict()[self.order_field],
                    reverse=self.reverse,
                )
            return snapshots

    class Batch:
        def __init__(self, client):
            self.client = client
            self.operations = []

        def create(self, reference, data):
            self.operations.append(("create", reference, data))

        def set(self, reference, data):
            self.operations.append(("set", reference, data))

        def delete(self, reference):
            self.operations.append(("delete", reference, None))

        def commit(self):
            for operation, reference, data in self.operations:
                if operation == "create" and reference.path in self.client.data:
                    raise RuntimeError("already exists")
                if operation == "delete":
                    self.client.data.pop(reference.path, None)
                else:
                    self.client.data[reference.path] = dict(data)

    class Client:
        def __init__(self):
            self.data = {}

        def collection(self, name):
            return Collection(self, (name,))

        def batch(self):
            return Batch(self)

        def transaction(self):
            return Transaction(self)

        def recursive_delete(self, reference):
            for path in list(self.data):
                if path[: len(reference.path)] == reference.path:
                    del self.data[path]

    class Transaction:
        def __init__(self, client):
            self.client = client

        def update(self, reference, values):
            self.client.data[reference.path].update(values)

    client = Client()
    repository = FirestoreMonitorRepository(client=client)
    first_content = b"a" * 1_400_001
    stored = replace(
        monitor(spec("1.0.0")),
        baseline_content=first_content,
        baseline_sha256=hashlib.sha256(first_content).hexdigest(),
    )
    repository.create(stored)
    assert repository.get("monitor-1") == stored
    lease_expiry = NOW + timedelta(minutes=15)
    claimed = repository.claim_check(
        "monitor-1",
        now=NOW,
        lease_expires_at=lease_expiry,
    )
    assert claimed is not None
    assert claimed.check_lease_expires_at == lease_expiry
    assert (
        repository.claim_check(
            "monitor-1",
            now=NOW + timedelta(minutes=1),
            lease_expires_at=NOW + timedelta(minutes=16),
        )
        is None
    )

    check = MonitorCheckRecord(
        check_id="check-firestore",
        monitor_id="monitor-1",
        status=MonitorCheckStatus.CHECKING,
        checked_at=NOW,
        completed_at=None,
        duration_ms=None,
        previous_spec_hash=stored.baseline_sha256,
        observed_spec_hash=None,
        analysis_id=None,
        error_code=None,
        error_message=None,
    )
    repository.start_check(stored, check)
    second_content = b"b" * 900_001
    changed = replace(
        stored,
        baseline_content=second_content,
        baseline_sha256=hashlib.sha256(second_content).hexdigest(),
        last_check_status=MonitorCheckStatus.CHANGED,
    )
    finished = replace(
        check,
        status=MonitorCheckStatus.CHANGED,
        completed_at=NOW,
        duration_ms=10,
        observed_spec_hash=changed.baseline_sha256,
    )
    repository.finish_check(changed, finished)

    assert repository.get("monitor-1") == changed
    assert repository.list_checks("monitor-1") == [finished]
    assert repository.delete("monitor-1") is True


def test_scheduler_checks_only_due_enabled_monitors_and_continues_after_failure():
    repository = MemoryMonitorRepository()
    repository.create(monitor(spec("1.0.0"), created_at=NOW - timedelta(hours=2)))
    repository.create(
        replace(
            monitor(spec("1.0.0")),
            monitor_id="disabled",
            enabled=False,
            created_at=NOW - timedelta(hours=2),
        )
    )
    repository.create(replace(monitor(spec("1.0.0")), monitor_id="not-due", created_at=NOW))
    repository.create(
        replace(
            monitor(spec("1.0.0")),
            monitor_id="due-after-failure",
            created_at=NOW - timedelta(hours=2),
        )
    )

    class FakeCheckService:
        def __init__(self):
            self.calls: list[str] = []

        async def check(self, monitor_id: str):
            self.calls.append(monitor_id)
            if monitor_id == "monitor-1":
                raise DriftGuardError(code="failure", message="failed")

    check_service = FakeCheckService()
    scheduler = MonitorScheduler(
        repository,
        check_service,
        enabled=True,
        poll_seconds=30,
    )

    asyncio.run(scheduler.run_once(now=NOW))

    assert check_service.calls == ["monitor-1", "due-after-failure"]


def test_scheduler_disabled_and_clean_start_stop():
    async def exercise():
        repository = MemoryMonitorRepository()

        class FakeCheckService:
            async def check(self, _monitor_id: str):
                raise AssertionError("no monitor should run")

        disabled = MonitorScheduler(
            repository,
            FakeCheckService(),
            enabled=False,
            poll_seconds=0.01,
        )
        disabled.start()
        assert disabled._task is None

        enabled = MonitorScheduler(
            repository,
            FakeCheckService(),
            enabled=True,
            poll_seconds=0.01,
        )
        enabled.start()
        await asyncio.sleep(0)
        await enabled.stop()
        assert enabled._task is None

    asyncio.run(exercise())
