from __future__ import annotations

import stat
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.repository.scanner import RepositoryArchiveScanner


def make_zip(files: dict[str, bytes], *, compression: int = ZIP_DEFLATED) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_scans_supported_utf8_source_and_skips_irrelevant_files():
    archive = make_zip(
        {
            "repo/src/client.py": b'requests.post("/payments")\n',
            "repo/node_modules/client.js": b'fetch("/payments")\n',
            "repo/README.md": b"documentation",
            "repo/src/image.py": b"\x00binary",
        }
    )
    result = RepositoryArchiveScanner().scan("repository.zip", archive)

    assert [file.path for file in result.files] == ["repo/src/client.py"]
    assert result.skipped_reasons == {
        "binary_file": 1,
        "ignored_path": 1,
        "unsupported_extension": 1,
    }
    assert len(result.archive_sha256) == 64


@pytest.mark.parametrize("path", ["../secret.py", "/absolute.py", "C:\\secret.py"])
def test_rejects_unsafe_archive_paths(path):
    with pytest.raises(DriftGuardError) as error:
        RepositoryArchiveScanner().scan("repository.zip", make_zip({path: b"pass"}))
    assert error.value.code == "unsafe_repository_archive"


def test_rejects_symbolic_links():
    output = BytesIO()
    link = ZipInfo("repo/link.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(output, "w") as archive:
        archive.writestr(link, "target.py")

    with pytest.raises(DriftGuardError) as error:
        RepositoryArchiveScanner().scan("repository.zip", output.getvalue())
    assert error.value.code == "unsafe_repository_archive"


def test_rejects_suspicious_compression_ratio():
    archive = make_zip({"repo/client.py": b"a" * 10_000})
    scanner = RepositoryArchiveScanner(max_compression_ratio=5)

    with pytest.raises(DriftGuardError) as error:
        scanner.scan("repository.zip", archive)
    assert error.value.code == "repository_scan_limit_exceeded"
    assert error.value.details["limit"] == "compression_ratio"


def test_enforces_archive_and_entry_limits_in_scanner():
    archive = make_zip({"one.py": b"pass", "two.py": b"pass"})

    with pytest.raises(DriftGuardError) as error:
        RepositoryArchiveScanner(max_archive_bytes=len(archive) - 1).scan(
            "repository.zip", archive
        )
    assert error.value.details["limit"] == "archive_bytes"

    with pytest.raises(DriftGuardError) as error:
        RepositoryArchiveScanner(max_files=1).scan("repository.zip", archive)
    assert error.value.details["limit"] == "archive_entries"


def test_rejects_non_zip_and_wrong_extension():
    scanner = RepositoryArchiveScanner()
    with pytest.raises(DriftGuardError) as error:
        scanner.scan("repository.tar", b"not an archive")
    assert error.value.code == "unsupported_repository_format"

    with pytest.raises(DriftGuardError) as error:
        scanner.scan("repository.zip", b"not an archive")
    assert error.value.code == "invalid_repository_archive"
