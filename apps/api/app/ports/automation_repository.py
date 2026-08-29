"""Persistence port for durable GitHub-native automation state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from apps.api.app.domain.automation import (
    ApiDependency,
    BackgroundJob,
    GitHubCheckRecord,
    RepositoryContract,
    WebhookDelivery,
)


class AutomationRepository(ABC):
    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def create_delivery(self, delivery: WebhookDelivery) -> bool: ...

    @abstractmethod
    def get_delivery(self, github_delivery_id: str) -> WebhookDelivery | None: ...

    @abstractmethod
    def get_delivery_by_id(self, delivery_id: str) -> WebhookDelivery | None: ...

    @abstractmethod
    def save_delivery(self, delivery: WebhookDelivery) -> None: ...

    @abstractmethod
    def enqueue_job(self, job: BackgroundJob) -> BackgroundJob: ...

    @abstractmethod
    def claim_due_jobs(self, now: datetime, limit: int = 10) -> list[BackgroundJob]: ...

    @abstractmethod
    def save_job(self, job: BackgroundJob) -> None: ...

    @abstractmethod
    def get_job(self, job_id: str, workspace_id: str | None = None) -> BackgroundJob | None: ...

    @abstractmethod
    def list_jobs(self, workspace_id: str, limit: int = 50) -> list[BackgroundJob]: ...

    @abstractmethod
    def upsert_contract(self, contract: RepositoryContract) -> RepositoryContract: ...

    @abstractmethod
    def get_contract(self, contract_id: str) -> RepositoryContract | None: ...

    @abstractmethod
    def list_contracts(self, workspace_id: str, repository_id: str) -> list[RepositoryContract]: ...

    @abstractmethod
    def save_dependency(self, dependency: ApiDependency) -> ApiDependency: ...

    @abstractmethod
    def list_dependencies(self, workspace_id: str, repository_id: str) -> list[ApiDependency]: ...

    @abstractmethod
    def upsert_check(self, check: GitHubCheckRecord) -> GitHubCheckRecord: ...

    @abstractmethod
    def get_check_by_logical_key(
        self, workspace_id: str, logical_key: str
    ) -> GitHubCheckRecord | None: ...

    @abstractmethod
    def list_checks(self, workspace_id: str, repository_id: str) -> list[GitHubCheckRecord]: ...
