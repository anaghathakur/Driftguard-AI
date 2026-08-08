from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.monitoring.specification_source import OpenApiSpecificationSource


def specification(*, version: str = "1.0.0") -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Remote API", "version": version},
            "paths": {},
        }
    ).encode()


async def public_resolver(_hostname: str):
    return ("93.184.216.34",)


def fetch(
    handler,
    url: str = "https://api.example.com/openapi.json",
    *,
    resolver=public_resolver,
    max_bytes: int = 1024 * 1024,
    max_redirects: int = 3,
):
    source = OpenApiSpecificationSource(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
    )
    return asyncio.run(source.fetch(url))


def test_fetch_accepts_valid_public_https_openapi():
    result = fetch(lambda _request: httpx.Response(200, content=specification()))

    assert result.filename == "openapi.json"
    assert result.content == specification()
    assert len(result.sha256) == 64


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/openapi.json",
        "file:///etc/passwd",
        "ftp://api.example.com/openapi.json",
        "https://user:secret@api.example.com/openapi.json",
        "https://api.example.com:443/openapi.json",
        "https://api.example.com/openapi.json#fragment",
        "https://localhost/openapi.json",
        "https://service.local/openapi.json",
        "https://metadata.google.internal/openapi.json",
        "https://127.0.0.1/openapi.json",
        "https://[::1]/openapi.json",
        "https://10.0.0.1/openapi.json",
        "https://172.16.0.1/openapi.json",
        "https://192.168.1.1/openapi.json",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_fetch_rejects_unsafe_urls_without_http_request(url):
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=specification())

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, url)

    assert error.value.code in {
        "invalid_remote_specification_url",
        "unsafe_remote_specification_destination",
    }
    assert calls == 0


@pytest.mark.parametrize(
    "resolved_address",
    [
        "127.0.0.1",
        "::1",
        "10.1.2.3",
        "172.20.1.2",
        "192.168.2.4",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
    ],
)
def test_fetch_rejects_hostnames_resolving_to_non_public_addresses(resolved_address):
    async def resolver(_hostname: str):
        return (resolved_address,)

    with pytest.raises(DriftGuardError) as error:
        fetch(
            lambda _request: httpx.Response(200, content=specification()),
            resolver=resolver,
        )

    assert error.value.code == "unsafe_remote_specification_destination"


def test_fetch_accepts_safe_redirect_after_revalidating_dns():
    resolved: list[str] = []

    async def resolver(hostname: str):
        resolved.append(hostname)
        return ("93.184.216.34",)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.example.com":
            return httpx.Response(
                302,
                headers={"location": "https://cdn.example.net/contracts/openapi.yaml"},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/yaml"},
            content=specification(),
        )

    result = fetch(handler, resolver=resolver)

    assert result.source_url == "https://cdn.example.net/contracts/openapi.yaml"
    assert resolved == ["api.example.com", "cdn.example.net"]


def test_fetch_rejects_redirect_to_private_destination():
    async def resolver(hostname: str):
        return ("10.0.0.2",) if hostname == "private.example" else ("93.184.216.34",)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://private.example/openapi.json"},
        )

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, resolver=resolver)

    assert error.value.code == "unsafe_remote_specification_destination"


def test_fetch_enforces_redirect_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        step = int(request.url.params.get("step", "0"))
        return httpx.Response(
            302,
            headers={"location": f"https://api.example.com/openapi.json?step={step + 1}"},
        )

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, max_redirects=2)

    assert error.value.code == "remote_spec_redirect_limit_exceeded"


@pytest.mark.parametrize(
    ("upstream_error", "expected_code"),
    [
        (httpx.ReadTimeout("timeout"), "remote_specification_timeout"),
        (httpx.ConnectError("network detail"), "remote_specification_request_failed"),
    ],
)
def test_fetch_maps_timeout_and_network_errors(upstream_error, expected_code):
    def handler(request: httpx.Request) -> httpx.Response:
        upstream_error.request = request
        raise upstream_error

    with pytest.raises(DriftGuardError) as error:
        fetch(handler)

    assert error.value.code == expected_code
    assert "network detail" not in error.value.message


def test_fetch_rejects_oversized_content_length_without_reading():
    class UnreadStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("body should not be read")
            yield b""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "11"},
            stream=UnreadStream(),
        )

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, max_bytes=10)

    assert error.value.code == "remote_specification_too_large"


def test_fetch_rejects_oversized_stream_without_content_length():
    class ChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123456"
            yield b"78901"

    with pytest.raises(DriftGuardError) as error:
        fetch(
            lambda _request: httpx.Response(200, stream=ChunkStream()),
            max_bytes=10,
        )

    assert error.value.code == "remote_specification_too_large"


@pytest.mark.parametrize(
    ("content", "content_type", "url", "expected_code"),
    [
        (
            b"{bad",
            "application/json",
            "https://api.example.com/openapi.json",
            "invalid_specification_syntax",
        ),
        (
            b'{"hello": "world"}',
            "application/json",
            "https://api.example.com/openapi.json",
            "unsupported_openapi_version",
        ),
        (
            b"hello: world",
            "application/yaml",
            "https://api.example.com/openapi",
            "unsupported_openapi_version",
        ),
    ],
)
def test_fetch_rejects_invalid_or_non_openapi_content(
    content,
    content_type,
    url,
    expected_code,
):
    with pytest.raises(DriftGuardError) as error:
        fetch(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": content_type},
                content=content,
            ),
            url,
        )

    assert error.value.code == expected_code
