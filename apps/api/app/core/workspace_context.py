"""Server-resolved workspace identity for repository isolation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

LOCAL_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
LOCAL_WORKSPACE_NAME = "Local Workspace"
LOCAL_WORKSPACE_SLUG = "local"


@dataclass(frozen=True, slots=True)
class WorkspacePrincipal:
    workspace_id: str
    user_id: str | None = None
    github_login: str | None = None
    local: bool = False


_principal: ContextVar[WorkspacePrincipal] = ContextVar(
    "driftguard_workspace_principal",
    default=WorkspacePrincipal(workspace_id=LOCAL_WORKSPACE_ID, local=True),  # noqa: B039
)


def current_principal() -> WorkspacePrincipal:
    return _principal.get()


def current_workspace_id() -> str:
    return current_principal().workspace_id


def set_principal(principal: WorkspacePrincipal) -> Token[WorkspacePrincipal]:
    return _principal.set(principal)


def reset_principal(token: Token[WorkspacePrincipal]) -> None:
    _principal.reset(token)


@contextmanager
def workspace_scope(principal: WorkspacePrincipal) -> Iterator[None]:
    token = set_principal(principal)
    try:
        yield
    finally:
        reset_principal(token)
