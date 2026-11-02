from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from google.api_core.exceptions import AlreadyExists

from apps.api.app.domain.automation import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from apps.api.app.infrastructure import firestore_automation_repository as module
from apps.api.app.infrastructure.firestore_automation_repository import (
    FirestoreAutomationRepository,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class Snapshot:
    def __init__(self, reference, data):
        self.reference = reference
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Document:
    def __init__(self, client, path):
        self.client = client
        self.path = path

    def get(self, transaction=None):
        del transaction
        return Snapshot(self, self.client.data.get(self.path))

    def create(self, data):
        if self.path in self.client.data:
            raise AlreadyExists("duplicate")
        self.client.data[self.path] = dict(data)

    def set(self, data):
        self.client.data[self.path] = dict(data)


class Query:
    def __init__(self, client, path, filters=(), order=None, reverse=False, size=None):
        self.client = client
        self.path = path
        self.filters = filters
        self.order = order
        self.reverse = reverse
        self.size = size

    def where(self, field, operator, value):
        return Query(
            self.client,
            self.path,
            (*self.filters, (field, operator, value)),
            self.order,
            self.reverse,
            self.size,
        )

    def order_by(self, field, direction=None):
        return Query(
            self.client,
            self.path,
            self.filters,
            field,
            "DESC" in str(direction),
            self.size,
        )

    def limit(self, size):
        return Query(
            self.client,
            self.path,
            self.filters,
            self.order,
            self.reverse,
            size,
        )

    def stream(self):
        values = []
        for path, data in self.client.data.items():
            if len(path) != len(self.path) + 1 or path[:-1] != self.path:
                continue
            matches = all(
                _matches(data.get(field), operator, value)
                for field, operator, value in self.filters
            )
            if matches:
                values.append(Snapshot(Document(self.client, path), data))
        if self.order:
            values.sort(key=lambda item: item.to_dict()[self.order], reverse=self.reverse)
        return values[: self.size] if self.size is not None else values


class Collection(Query):
    def document(self, identifier):
        return Document(self.client, (*self.path, identifier))


class Transaction:
    def set(self, reference, data):
        reference.set(data)


class Client:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return Collection(self, (name,))

    def transaction(self):
        return Transaction()


def _matches(current, operator, expected):
    if operator == "==":
        return current == expected
    if operator == "<=":
        return current is not None and current <= expected
    raise AssertionError(f"Unsupported test query operator: {operator}")


@pytest.fixture(autouse=True)
def plain_transactional(monkeypatch):
    monkeypatch.setattr(module.firestore, "transactional", lambda function: function)


def job(*, status=BackgroundJobStatus.QUEUED, **updates):
    value = BackgroundJob(
        "job-1",
        "workspace-1",
        BackgroundJobType.GITHUB_PUSH_SCAN,
        status,
        {"repository_connection_id": "repo-1"},
        0,
        NOW,
    )
    return replace(value, **updates)


def test_delivery_is_idempotent_and_jobs_are_claimed_once():
    repository = FirestoreAutomationRepository(client=Client())
    delivery = WebhookDelivery(
        "delivery-1",
        "github-delivery-1",
        "push",
        None,
        1,
        2,
        NOW,
        WebhookDeliveryStatus.RECEIVED,
    )

    assert repository.create_delivery(delivery) is True
    assert repository.create_delivery(delivery) is False
    assert repository.get_delivery("github-delivery-1") == delivery

    repository.enqueue_job(job())
    first = repository.claim_due_jobs(NOW)
    second = repository.claim_due_jobs(NOW)

    assert len(first) == 1
    assert first[0].status is BackgroundJobStatus.RUNNING
    assert first[0].attempt_count == 1
    assert second == []


def test_retry_and_stale_recovery_are_durable():
    repository = FirestoreAutomationRepository(client=Client())
    retry = job(
        status=BackgroundJobStatus.RETRY_SCHEDULED,
        next_attempt_at=NOW - timedelta(seconds=1),
    )
    repository.enqueue_job(retry)
    assert repository.claim_due_jobs(NOW)[0].status is BackgroundJobStatus.RUNNING

    stale = job(
        job_id="job-stale",
        status=BackgroundJobStatus.RUNNING,
        attempt_count=1,
        started_at=NOW - timedelta(minutes=5),
    )
    repository.enqueue_job(stale)
    recovered = repository.recover_stale_jobs(
        NOW,
        retry_limit=3,
        stale_after_seconds=60,
    )

    assert [item.job_id for item in recovered] == ["job-stale"]
    assert recovered[0].status is BackgroundJobStatus.RETRY_SCHEDULED
    assert recovered[0].failure_code == "worker_interrupted"
