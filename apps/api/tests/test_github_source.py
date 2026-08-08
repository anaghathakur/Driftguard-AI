from __future__ import annotations

import asyncio
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.repository.github_source import (
    GitHubRepositorySource,
    parse_github_repository_url,
    validate_github_ref,
)


def repository_archive() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("demo/client.py", 'requests.post("/payments")\n')
    return output.getvalue()


def fetch(
    handler,
    *,
    ref: str | None = None,
    max_archive_bytes: int = 1024 * 1024,
):
    source = GitHubRepositorySource(
        transport=httpx.MockTransport(handler),
        max_archive_bytes=max_archive_bytes,
    )
    return asyncio.run(
        source.fetch(
            "https://github.com/example/repository",
            ref=ref,
        )
    )


def test_parse_github_repository_url_accepts_public_repository_and_git_suffix():
    plain = parse_github_repository_url("https://github.com/example/repository")
    suffixed = parse_github_repository_url(
        "https://github.com/example/repository.git/"
    )

    assert (plain.owner, plain.repository) == ("example", "repository")
    assert suffixed == plain


@pytest.mark.parametrize(
    "repository_url",
    [
        "http://github.com/example/repository",
        "https://evil.com/example/repository",
        "https://github.com.evil.com/example/repository",
        "https://user:secret@github.com/example/repository",
        "https://github.com:443/example/repository",
        "https://github.com:bad/example/repository",
        "https://github.com/example",
        "https://github.com/example/repository/issues",
        "https://github.com//example/repository",
        "https://github.com/example/repository?ref=main",
    ],
)
def test_parse_github_repository_url_rejects_unsafe_values(repository_url):
    with pytest.raises(DriftGuardError) as error:
        parse_github_repository_url(repository_url)

    assert error.value.code == "invalid_github_repository_url"


def test_validate_github_ref_supports_default_branch_tag_and_sha():
    assert validate_github_ref(None) is None
    assert validate_github_ref("  ") is None
    assert validate_github_ref("feature/payments") == "feature/payments"
    assert validate_github_ref("v2.0.0") == "v2.0.0"
    assert validate_github_ref("a" * 40) == "a" * 40


@pytest.mark.parametrize(
    "ref",
    [
        "../main",
        "feature//payments",
        "feature/.hidden",
        "refs/heads/main.lock",
        "main.",
        "main branch",
        "main~1",
        "@{upstream}",
    ],
)
def test_validate_github_ref_rejects_unsafe_values(ref):
    with pytest.raises(DriftGuardError) as error:
        validate_github_ref(ref)

    assert error.value.code == "invalid_github_ref"


def test_fetch_downloads_only_the_validated_codeload_redirect():
    content = repository_archive()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/"
                        "legacy.zip/refs/heads/feature/payments"
                    )
                },
            )
        return httpx.Response(200, content=content)

    result = fetch(handler, ref="feature/payments")

    assert result.content == content
    assert result.filename == "github-example-repository-feature-payments.zip"
    assert result.ref == "feature/payments"
    assert [request.url.host for request in requests] == [
        "api.github.com",
        "codeload.github.com",
    ]
    assert requests[0].url.raw_path.endswith(b"feature%2Fpayments")


def test_fetch_uses_the_repository_default_branch_when_ref_is_omitted():
    content = repository_archive()
    api_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            api_paths.append(request.url.path)
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/archive.zip"
                    )
                },
            )
        return httpx.Response(200, content=content)

    result = fetch(handler)

    assert api_paths == ["/repos/example/repository/zipball"]
    assert result.ref is None
    assert result.filename == "github-example-repository-default.zip"


@pytest.mark.parametrize(
    "location",
    [
        "",
        "https://evil.com/example/repository/archive.zip",
        "https://codeload.github.com.evil.com/example/repository/archive.zip",
        "http://codeload.github.com/example/repository/archive.zip",
        "https://user@codeload.github.com/example/repository/archive.zip",
        "https://codeload.github.com/other/repository/archive.zip",
    ],
)
def test_fetch_rejects_untrusted_archive_redirects(location):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(DriftGuardError) as error:
        fetch(handler)

    assert error.value.code == "unsafe_github_redirect"


@pytest.mark.parametrize(
    ("status_code", "ref", "expected_code", "expected_status"),
    [
        (404, None, "github_repository_not_found", 404),
        (404, "missing-ref", "github_ref_not_found", 404),
        (403, None, "github_request_denied", 429),
        (429, None, "github_request_denied", 429),
    ],
)
def test_fetch_maps_github_api_failures(
    status_code,
    ref,
    expected_code,
    expected_status,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if ref is not None and not request.url.path.endswith("zipball/missing-ref"):
            return httpx.Response(200)
        return httpx.Response(status_code)

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, ref=ref)

    assert error.value.code == expected_code
    assert error.value.status_code == expected_status


def test_fetch_distinguishes_a_missing_repository_when_a_ref_was_supplied():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, ref="missing-ref")

    assert error.value.code == "github_repository_not_found"


@pytest.mark.parametrize(
    ("repository_status", "expected_code", "expected_status"),
    [
        (200, "github_ref_not_found", 404),
        (404, "github_repository_not_found", 404),
        (500, "github_archive_unavailable", 502),
    ],
)
def test_fetch_maps_codeload_404_after_redirect(
    repository_status,
    expected_code,
    expected_status,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "codeload.github.com":
            return httpx.Response(404)
        if request.url.path.endswith("/zipball/missing-ref"):
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/archive.zip"
                    )
                },
            )
        return httpx.Response(repository_status)

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, ref="missing-ref")

    assert error.value.code == expected_code
    assert error.value.status_code == expected_status


def test_fetch_keeps_genuine_codeload_failure_as_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/archive.zip"
                    )
                },
            )
        return httpx.Response(500)

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, ref="main")

    assert error.value.code == "github_archive_download_failed"
    assert error.value.status_code == 502


@pytest.mark.parametrize(
    ("upstream_error", "expected_code"),
    [
        (httpx.ReadTimeout("timed out"), "github_timeout"),
        (httpx.ConnectError("connection failed"), "github_request_failed"),
    ],
)
def test_fetch_maps_timeout_and_network_failure(upstream_error, expected_code):
    def handler(request: httpx.Request) -> httpx.Response:
        upstream_error.request = request
        raise upstream_error

    with pytest.raises(DriftGuardError) as error:
        fetch(handler)

    assert error.value.code == expected_code
    assert "connection failed" not in error.value.message


def test_fetch_rejects_oversized_content_length_before_reading():
    class UnreadStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("oversized response body should not be read")
            yield b""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/archive.zip"
                    )
                },
            )
        return httpx.Response(
            200,
            headers={"content-length": "11"},
            stream=UnreadStream(),
        )

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, max_archive_bytes=10)

    assert error.value.code == "github_repository_too_large"


def test_fetch_rejects_oversized_stream_without_content_length():
    class ChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123456"
            yield b"78901"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/archive.zip"
                    )
                },
            )
        return httpx.Response(200, stream=ChunkStream())

    with pytest.raises(DriftGuardError) as error:
        fetch(handler, max_archive_bytes=10)

    assert error.value.code == "github_repository_too_large"


def test_fetch_rejects_an_unreadable_zip_response():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://codeload.github.com/example/repository/archive.zip"
                    )
                },
            )
        return httpx.Response(200, content=b"PK-not-a-valid-zip")

    with pytest.raises(DriftGuardError) as error:
        fetch(handler)

    assert error.value.code == "invalid_github_archive"
