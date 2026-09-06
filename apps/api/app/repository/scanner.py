"""Safely scan source files from an uploaded ZIP without extracting it."""

from __future__ import annotations

import hashlib
import stat
from collections import Counter
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

from apps.api.app.core import config
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.repository.policy import RepositoryFilteringPolicy

SOURCE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".gql",
        ".h",
        ".hpp",
        ".graphql",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".svelte",
        ".swift",
        ".ts",
        ".tsx",
        ".vue",
    }
)

VALIDATION_CONFIG_FILENAMES = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "pytest.ini",
        "requirements.txt",
        "setup.cfg",
        "tox.ini",
    }
)


class RepositoryArchiveScanner:
    def __init__(
        self,
        *,
        max_archive_bytes: int | None = None,
        max_files: int | None = None,
        max_file_bytes: int | None = None,
        max_uncompressed_bytes: int | None = None,
        max_compression_ratio: int | None = None,
        max_source_files: int | None = None,
        max_source_bytes: int | None = None,
    ) -> None:
        runtime = config.settings
        self.max_archive_bytes = (
            runtime.max_repository_archive_bytes
            if max_archive_bytes is None
            else max_archive_bytes
        )
        self.max_files = runtime.max_repository_files if max_files is None else max_files
        self.max_file_bytes = (
            runtime.max_repository_file_bytes if max_file_bytes is None else max_file_bytes
        )
        self.max_uncompressed_bytes = (
            runtime.max_repository_uncompressed_bytes
            if max_uncompressed_bytes is None
            else max_uncompressed_bytes
        )
        self.max_compression_ratio = (
            runtime.max_repository_compression_ratio
            if max_compression_ratio is None
            else max_compression_ratio
        )
        self.max_source_files = (
            runtime.max_repository_source_files
            if max_source_files is None
            else max_source_files
        )
        self.max_source_bytes = (
            runtime.max_repository_source_bytes
            if max_source_bytes is None
            else max_source_bytes
        )
        self.policy = RepositoryFilteringPolicy(SOURCE_EXTENSIONS)

    def scan(self, filename: str, content: bytes) -> RepositoryScan:
        if len(content) > self.max_archive_bytes:
            self._limit_error("archive_bytes", self.max_archive_bytes)
        if not filename.lower().endswith(".zip"):
            raise DriftGuardError(
                code="unsupported_repository_format",
                message="The repository upload must be a ZIP archive.",
            )
        try:
            with ZipFile(BytesIO(content), mode="r") as archive:
                return self._scan_archive(archive, content)
        except (BadZipFile, LargeZipFile, EOFError, NotImplementedError) as exc:
            raise DriftGuardError(
                code="invalid_repository_archive",
                message="The uploaded repository ZIP cannot be read.",
            ) from exc

    def _scan_archive(self, archive: ZipFile, content: bytes) -> RepositoryScan:
        entries = archive.infolist()
        if len(entries) > self.max_files:
            raise DriftGuardError(
                code="repository_file_limit_exceeded",
                message="Repository archive exceeds the configured entry limit.",
                status_code=413,
                details={
                    "limit": "archive_entries",
                    "actual_entries": len(entries),
                    "configured_max_entries": self.max_files,
                    "configuration": "DRIFTGUARD_MAX_REPOSITORY_FILES",
                },
            )

        total_size = 0
        source_bytes = 0
        seen_paths: set[str] = set()
        source_files: list[ScannedSourceFile] = []
        skipped: Counter[str] = Counter()

        for entry in entries:
            path = _validated_path(entry)
            path_key = path.casefold()
            if path_key in seen_paths:
                raise DriftGuardError(
                    code="unsafe_repository_archive",
                    message="The repository ZIP contains duplicate file paths.",
                )
            seen_paths.add(path_key)
            if entry.is_dir():
                continue
            if _has_unsupported_entry_type(entry):
                skipped["link_or_special_file"] += 1
                continue
            if entry.flag_bits & 0x1:
                raise DriftGuardError(
                    code="unsafe_repository_archive",
                    message="Encrypted ZIP entries are not supported.",
                )

            total_size += entry.file_size
            if total_size > self.max_uncompressed_bytes:
                self._limit_error("uncompressed_bytes", self.max_uncompressed_bytes)
            if entry.file_size > self.max_compression_ratio * max(entry.compress_size, 1):
                self._limit_error("compression_ratio", self.max_compression_ratio)
            policy_reason = self.policy.reason_to_skip(path)
            skip_reason = (
                None
                if (
                    PurePosixPath(path).name.casefold() in VALIDATION_CONFIG_FILENAMES
                    and policy_reason != "ignored_path"
                )
                else policy_reason
            )
            if skip_reason:
                skipped[skip_reason] += 1
                continue
            if entry.file_size > self.max_file_bytes:
                raise DriftGuardError(
                    code="repository_too_large",
                    message="A source file exceeds the per-file analysis limit.",
                    status_code=413,
                    details={"limit": "source_file_bytes", "maximum": self.max_file_bytes},
                )

            raw = archive.read(entry)
            if len(raw) > self.max_file_bytes:
                self._limit_error("file_bytes", self.max_file_bytes)
            if b"\x00" in raw:
                skipped["binary_file"] += 1
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                skipped["non_utf8_file"] += 1
                continue
            source_files.append(ScannedSourceFile(path=path, content=text, size_bytes=len(raw)))
            source_bytes += len(raw)
            if len(source_files) > self.max_source_files:
                raise DriftGuardError(
                    code="repository_source_limit_exceeded",
                    message="Repository contains too many source files to analyze safely.",
                    status_code=413,
                    details={
                        "limit": "source_files",
                        "actual_files": len(source_files),
                        "configured_max_files": self.max_source_files,
                        "configuration": "DRIFTGUARD_MAX_REPOSITORY_SOURCE_FILES",
                    },
                )
            if source_bytes > self.max_source_bytes:
                raise DriftGuardError(
                    code="repository_source_limit_exceeded",
                    message="Repository source content exceeds the aggregate analysis limit.",
                    status_code=413,
                    details={
                        "limit": "source_bytes",
                        "actual_bytes": source_bytes,
                        "configured_max_bytes": self.max_source_bytes,
                        "configuration": "DRIFTGUARD_MAX_REPOSITORY_SOURCE_BYTES",
                    },
                )

        return RepositoryScan(
            archive_sha256=hashlib.sha256(content).hexdigest(),
            archive_entries=len(entries),
            files=tuple(sorted(source_files, key=lambda file: file.path)),
            skipped_files=sum(skipped.values()),
            skipped_reasons=dict(sorted(skipped.items())),
        )

    @staticmethod
    def _limit_error(limit: str, maximum: int) -> None:
        raise DriftGuardError(
            code="repository_scan_limit_exceeded",
            message="The repository ZIP exceeds a configured scanning limit.",
            status_code=413,
            details={"limit": limit, "maximum": maximum},
        )


def _validated_path(entry: ZipInfo) -> str:
    raw_path = entry.filename.replace("\\", "/")
    if not raw_path or "\x00" in raw_path or raw_path.startswith("/"):
        _unsafe_path()
    parts = PurePosixPath(raw_path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _unsafe_path()
    if ":" in parts[0]:
        _unsafe_path()
    return PurePosixPath(*parts).as_posix()


def _has_unsupported_entry_type(entry: ZipInfo) -> bool:
    mode = entry.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    return bool(file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR})


def _unsafe_path() -> None:
    raise DriftGuardError(
        code="unsafe_repository_archive",
        message="The repository ZIP contains an unsafe file path.",
    )
