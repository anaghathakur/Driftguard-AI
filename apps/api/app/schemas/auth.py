"""Browser authentication and workspace API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class UserResponse(BaseModel):
    id: str
    github_login: str
    github_display_name: str | None
    avatar_url: str | None
    auth_provider: str = "github"
    email: str | None = None


class AuthStatusResponse(BaseModel):
    mode: str
    authenticated: bool
    development_auth: bool = False
    github_auth_configured: bool = False
    google_auth_configured: bool = False
    user: UserResponse | None = None
    workspace: WorkspaceResponse | None = None
    workspaces: list[WorkspaceResponse] = Field(default_factory=list)
    csrf_token: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class WorkspaceSwitchRequest(BaseModel):
    workspace_id: str


WorkspaceRoleValue = Literal["owner", "admin", "developer", "viewer"]


class WorkspaceMemberResponse(BaseModel):
    user_id: str
    github_login: str
    github_display_name: str | None
    avatar_url: str | None
    email: str | None
    role: WorkspaceRoleValue
    joined_at: datetime


class WorkspaceMemberRoleRequest(BaseModel):
    role: WorkspaceRoleValue


class AuditEventResponse(BaseModel):
    id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    metadata: dict[str, object]
    created_at: datetime
