"""Securely fetch bounded OpenAPI documents from public HTTPS endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.openapi.parser import SUPPORTED_EXTENSIONS, parse_openapi_document

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
    }
)

AddressResolver = Callable[[str], Awaitable[Iterable[str]]]


@dataclass(frozen=True, slots=True)
class RemoteSpecification:
    source_url: str
    filename: str
    content_type: str
    content: bytes
    sha256: str


class OpenApiSpecificationSource:
    def __init__(
        self,
        *,
        timeout_seconds: float = settings.remote_spec_timeout_seconds,
        max_bytes: int = settings.max_spec_file_bytes,
        max_redirects: int = settings.remote_spec_max_redirects,
        resolver: AddressResolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver or _resolve_public_addresses
        self.transport = transport

    async def fetch(self, specification_url: str) -> RemoteSpecification:
        current_url = specification_url.strip()
        headers = {
            "Accept": "application/json, application/yaml, text/yaml, */*;q=0.1",
            "User-Agent": "DriftGuard-AI/0.1",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                for redirect_count in range(self.max_redirects + 1):
                    await self._validate_url(current_url)
                    async with client.stream(
                        "GET",
                        current_url,
                        headers=headers,
                    ) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            if redirect_count >= self.max_redirects:
                                raise DriftGuardError(
                                    code="remote_spec_redirect_limit_exceeded",
                                    message=(
                                        "The OpenAPI URL exceeded the allowed redirect limit."
                                    ),
                                    status_code=502,
                                )
                            location = response.headers.get("location")
                            if not location:
                                raise DriftGuardError(
                                    code="unsafe_remote_spec_redirect",
                                    message="The OpenAPI URL returned an invalid redirect.",
                                    status_code=502,
                                )
                            current_url = urljoin(current_url, location)
                            continue

                        if response.status_code != 200:
                            raise DriftGuardError(
                                code="remote_specification_unavailable",
                                message="The remote OpenAPI specification could not be fetched.",
                                status_code=502,
                                details={"upstream_status": response.status_code},
                            )

                        content = await self._read_bounded(response)
                        content_type = response.headers.get("content-type", "")
                        filename = _specification_filename(
                            current_url,
                            content_type,
                            content,
                        )
                        document = parse_openapi_document(filename, content)
                        normalize_openapi(document)
                        return RemoteSpecification(
                            source_url=current_url,
                            filename=filename,
                            content_type=content_type[:200],
                            content=content,
                            sha256=hashlib.sha256(content).hexdigest(),
                        )
        except httpx.TimeoutException as exc:
            raise DriftGuardError(
                code="remote_specification_timeout",
                message="The OpenAPI endpoint did not respond before the timeout.",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            raise DriftGuardError(
                code="remote_specification_request_failed",
                message="The remote OpenAPI specification could not be fetched.",
                status_code=502,
            ) from exc

        raise DriftGuardError(
            code="remote_specification_unavailable",
            message="The remote OpenAPI specification could not be fetched.",
            status_code=502,
        )

    async def _validate_url(self, value: str) -> None:
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError as exc:
            raise _invalid_url() from exc

        hostname = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.fragment
        ):
            raise _invalid_url()

        normalized_host = _normalized_hostname(hostname)
        if (
            normalized_host in _BLOCKED_HOSTNAMES
            or normalized_host.endswith((".localhost", ".local", ".internal"))
        ):
            raise _unsafe_destination()

        try:
            literal = ipaddress.ip_address(normalized_host)
        except ValueError:
            try:
                addresses = tuple(await self.resolver(normalized_host))
            except (OSError, UnicodeError) as exc:
                raise DriftGuardError(
                    code="remote_specification_dns_failed",
                    message="The OpenAPI hostname could not be resolved safely.",
                    status_code=502,
                ) from exc
            if not addresses:
                raise DriftGuardError(
                    code="remote_specification_dns_failed",
                    message="The OpenAPI hostname could not be resolved safely.",
                    status_code=502,
                ) from None
            for address in addresses:
                try:
                    resolved = ipaddress.ip_address(address)
                except ValueError as exc:
                    raise _unsafe_destination() from exc
                if not _is_public_address(resolved):
                    raise _unsafe_destination() from None
        else:
            if not _is_public_address(literal):
                raise _unsafe_destination()

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > self.max_bytes:
                self._too_large()

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                self._too_large()
            chunks.append(chunk)
        return b"".join(chunks)

    def _too_large(self) -> None:
        raise DriftGuardError(
            code="remote_specification_too_large",
            message="The remote OpenAPI specification exceeds the configured size limit.",
            status_code=413,
            details={"max_bytes": self.max_bytes},
        )


async def _resolve_public_addresses(hostname: str) -> tuple[str, ...]:
    def resolve() -> tuple[str, ...]:
        records = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
        return tuple(sorted({record[4][0] for record in records}))

    return await asyncio.to_thread(resolve)


def _normalized_hostname(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise _invalid_url() from exc


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def _specification_filename(url: str, content_type: str, content: bytes) -> str:
    path_name = PurePosixPath(urlparse(url).path).name
    if PurePosixPath(path_name).suffix.lower() in SUPPORTED_EXTENSIONS:
        return path_name[:255]
    lowered_type = content_type.lower()
    if "yaml" in lowered_type or not content.lstrip().startswith((b"{", b"[")):
        return "openapi.yaml"
    return "openapi.json"


def _invalid_url() -> DriftGuardError:
    return DriftGuardError(
        code="invalid_remote_specification_url",
        message="The OpenAPI URL must be a public HTTPS URL without credentials or ports.",
        status_code=422,
    )


def _unsafe_destination() -> DriftGuardError:
    return DriftGuardError(
        code="unsafe_remote_specification_destination",
        message="The OpenAPI URL resolves to a non-public network destination.",
        status_code=422,
    )
