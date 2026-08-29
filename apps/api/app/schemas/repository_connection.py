"""Workspace GitHub App onboarding response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class InstallationConnectRequest(BaseModel):
    github_installation_id: int


class InstallationResponse(BaseModel):
    id: str
    github_installation_id: int
    account_id: int
    account_login: str
    account_type: str
    connected_at: datetime
    revoked: bool


class RepositoryConnectionResponse(BaseModel):
    id: str
    installation_id: str
    github_repository_id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool
    html_url: str
    enabled: bool
    last_synced_at: datetime
    removed: bool


class RepositoryEnableRequest(BaseModel):
    enabled: bool
