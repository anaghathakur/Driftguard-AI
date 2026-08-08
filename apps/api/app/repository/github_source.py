"""Fetch public GitHub repositories as bounded ZIP archives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote, urlparse
from zipfile import is_zipfile

import httpx

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError

_GITHUB_HOST = "github.com"
_GITHUB_API_HOST = "api.github.com"
_GITHUB_ARCHIVE_HOST = "codeload.github.com"
_GITHUB_API_VERSION = "2026-03-10"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


@dataclass(frozen=True, slots=True)
class GitHubRepositoryArchive:
    owner: str
    repository: str
    ref: str | None
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    repository: str


def parse_github_repository_url(repository_url: str) -> GitHubRepository:
    value = repository_url.strip()
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise _invalid_repository_url() from exc

    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != _GITHUB_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _invalid_repository_url()

    path_match = re.fullmatch(r"/([^/]+)/([^/]+)/?", parsed.path)
    if path_match is None:
        raise _invalid_repository_url()

    owner, repository = path_match.groups()
    if repository.endswith(".git"):
        repository = repository[:-4]

    if (
        not _OWNER_PATTERN.fullmatch(owner)
        or not _REPOSITORY_PATTERN.fullmatch(repository)
        or repository in {".", ".."}
    ):
        raise _invalid_repository_url()

    return GitHubRepository(owner=owner, repository=repository)


def validate_github_ref(ref: str | None) -> str | None:
    if ref is None:
        return None

    value = ref.strip()
    if not value:
        return None

    components = value.split("/")
    if (
        not _REF_PATTERN.fullmatch(value)
        or value.endswith(("/", "."))
        or ".." in value
        or "//" in value
        or "@{" in value
        or any(
            component.startswith(".") or component.endswith(".lock")
            for component in components
        )
    ):
        raise DriftGuardError(
            code="invalid_github_ref",
            message="The GitHub branch, tag, or ref is invalid.",
            status_code=422,
        )

    return value


class GitHubRepositorySource:
    def __init__(
        self,
        *,
        timeout_seconds: float = settings.github_timeout_seconds,
        max_archive_bytes: int = settings.max_repository_archive_bytes,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_archive_bytes = max_archive_bytes
        self.transport = transport

    async def fetch(
        self,
        repository_url: str,
        ref: str | None = None,
    ) -> GitHubRepositoryArchive:
        repository = parse_github_repository_url(repository_url)
        validated_ref = validate_github_ref(ref)
        api_url = self._archive_api_url(repository, validated_ref)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DriftGuard-AI/0.1",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get(api_url, headers=headers)
                if response.status_code == 404:
                    await self._raise_not_found(
                        client,
                        repository=repository,
                        ref=validated_ref,
                        headers=headers,
                    )
                redirect_url = self._validate_archive_response(
                    response,
                    repository=repository,
                )
                content = await self._download_archive(
                    client,
                    redirect_url,
                    repository=repository,
                    ref=validated_ref,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise DriftGuardError(
                code="github_timeout",
                message="GitHub did not respond before the configured timeout.",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            raise DriftGuardError(
                code="github_request_failed",
                message="The GitHub repository could not be downloaded.",
                status_code=502,
            ) from exc

        ref_label = _safe_filename_part(validated_ref or "default")
        filename = (
            f"github-{_safe_filename_part(repository.owner)}-"
            f"{_safe_filename_part(repository.repository)}-{ref_label}.zip"
        )
        return GitHubRepositoryArchive(
            owner=repository.owner,
            repository=repository.repository,
            ref=validated_ref,
            filename=filename,
            content=content,
        )

    @staticmethod
    def _archive_api_url(repository: GitHubRepository, ref: str | None) -> str:
        owner = quote(repository.owner, safe="")
        repo = quote(repository.repository, safe="")
        base = f"https://{_GITHUB_API_HOST}/repos/{owner}/{repo}/zipball"
        if ref is None:
            return base
        return f"{base}/{quote(ref, safe='')}"

    async def _raise_not_found(
        self,
        client: httpx.AsyncClient,
        *,
        repository: GitHubRepository,
        ref: str | None,
        headers: dict[str, str],
    ) -> None:
        if ref is None:
            raise DriftGuardError(
                code="github_repository_not_found",
                message="The public GitHub repository was not found.",
                status_code=404,
            )

        owner = quote(repository.owner, safe="")
        repo = quote(repository.repository, safe="")
        response = await client.get(
            f"https://{_GITHUB_API_HOST}/repos/{owner}/{repo}",
            headers=headers,
        )
        if response.status_code == 200:
            raise DriftGuardError(
                code="github_ref_not_found",
                message="The requested GitHub branch, tag, or ref was not found.",
                status_code=404,
            )
        if response.status_code == 404:
            raise DriftGuardError(
                code="github_repository_not_found",
                message="The public GitHub repository was not found.",
                status_code=404,
            )
        self._raise_for_api_rejection(response.status_code)

    def _validate_archive_response(
        self,
        response: httpx.Response,
        *,
        repository: GitHubRepository,
    ) -> str:
        self._raise_for_api_rejection(response.status_code)

        if response.status_code not in _REDIRECT_STATUSES:
            raise DriftGuardError(
                code="github_archive_unavailable",
                message="GitHub did not return a repository archive.",
                status_code=502,
                details={"github_status": response.status_code},
            )

        location = response.headers.get("location", "")
        try:
            parsed = urlparse(location)
            port = parsed.port
        except ValueError as exc:
            raise DriftGuardError(
                code="unsafe_github_redirect",
                message="GitHub returned an unexpected repository archive location.",
                status_code=502,
            ) from exc

        redirect_parts = [part for part in parsed.path.split("/") if part]
        expected_prefix = [repository.owner.casefold(), repository.repository.casefold()]
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != _GITHUB_ARCHIVE_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or len(redirect_parts) < 3
            or [part.casefold() for part in redirect_parts[:2]] != expected_prefix
        ):
            raise DriftGuardError(
                code="unsafe_github_redirect",
                message="GitHub returned an unexpected repository archive location.",
                status_code=502,
            )

        return location

    @staticmethod
    def _raise_for_api_rejection(status_code: int) -> None:
        if status_code in {401, 403, 429}:
            raise DriftGuardError(
                code="github_request_denied",
                message=(
                    "GitHub denied the repository request. "
                    "The public API rate limit may have been reached."
                ),
                status_code=429,
            )
        if status_code not in {200, *_REDIRECT_STATUSES}:
            raise DriftGuardError(
                code="github_archive_unavailable",
                message="GitHub did not return a repository archive.",
                status_code=502,
                details={"github_status": status_code},
            )

    async def _download_archive(
        self,
        client: httpx.AsyncClient,
        archive_url: str,
        *,
        repository: GitHubRepository,
        ref: str | None,
        headers: dict[str, str],
    ) -> bytes:
        async with client.stream("GET", archive_url, headers=headers) as response:
            if response.status_code == 404 and ref is not None:
                await self._raise_not_found(
                    client,
                    repository=repository,
                    ref=ref,
                    headers=headers,
                )
            if response.status_code != 200:
                raise DriftGuardError(
                    code="github_archive_download_failed",
                    message="The GitHub repository archive could not be downloaded.",
                    status_code=502,
                    details={"github_status": response.status_code},
                )

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = 0
                if declared_size > self.max_archive_bytes:
                    self._archive_too_large()

            chunks: list[bytes] = []
            total_bytes = 0
            async for chunk in response.aiter_bytes():
                total_bytes += len(chunk)
                if total_bytes > self.max_archive_bytes:
                    self._archive_too_large()
                chunks.append(chunk)

        content = b"".join(chunks)
        if not is_zipfile(BytesIO(content)):
            raise DriftGuardError(
                code="invalid_github_archive",
                message="GitHub returned data that is not a readable ZIP archive.",
                status_code=502,
            )
        return content

    def _archive_too_large(self) -> None:
        raise DriftGuardError(
            code="github_repository_too_large",
            message="The GitHub repository archive exceeds the configured size limit.",
            status_code=413,
            details={"max_bytes": self.max_archive_bytes},
        )


def _safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")[:100] or "default"


def _invalid_repository_url() -> DriftGuardError:
    return DriftGuardError(
        code="invalid_github_repository_url",
        message=(
            "Repository URL must be an HTTPS GitHub repository URL such as "
            "https://github.com/owner/repository."
        ),
        status_code=422,
    )
