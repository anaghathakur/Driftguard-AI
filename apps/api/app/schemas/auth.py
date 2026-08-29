"""Browser authentication and workspace API schemas."""

from __future__ import annotations

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


class AuthStatusResponse(BaseModel):
    mode: str
    authenticated: bool
    user: UserResponse | None = None
    workspace: WorkspaceResponse | None = None
    workspaces: list[WorkspaceResponse] = []
    csrf_token: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class WorkspaceSwitchRequest(BaseModel):
    workspace_id: str
