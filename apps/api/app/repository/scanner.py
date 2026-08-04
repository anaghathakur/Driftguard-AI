"""Safely scan source files from an uploaded ZIP without extracting it."""

from __future__ import annotations

import hashlib
import stat
from collections import Counter
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile

SOURCE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".h",
        ".hpp",
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
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".venv",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)


class RepositoryArchiveScanner:
    def __init__(
        self,
        *,
        max_archive_bytes: int = settings.max_repository_archive_bytes,
        max_files: int = settings.max_repository_files,
        max_file_bytes: int = settings.max_repository_file_bytes,
        max_uncompressed_bytes: int = settings.max_repository_uncompressed_bytes,
        max_compression_ratio: int = settings.max_repository_compression_ratio,
    ) -> None:
        self.max_archive_bytes = max_archive_bytes
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_compression_ratio = max_compression_ratio

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
            self._limit_error("archive_entries", self.max_files)

        total_size = 0
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
            _validate_entry_type(entry)
            if entry.flag_bits & 0x1:
                raise DriftGuardError(
                    code="unsafe_repository_archive",
                    message="Encrypted ZIP entries are not supported.",
                )

            total_size += entry.file_size
            if total_size > self.max_uncompressed_bytes:
                self._limit_error("uncompressed_bytes", self.max_uncompressed_bytes)
            if entry.file_size > self.max_file_bytes:
                skipped["file_too_large"] += 1
                continue
            if entry.file_size > self.max_compression_ratio * max(entry.compress_size, 1):
                self._limit_error("compression_ratio", self.max_compression_ratio)
            if _is_ignored(path):
                skipped["ignored_path"] += 1
                continue
            if PurePosixPath(path).suffix.lower() not in SOURCE_EXTENSIONS:
                skipped["unsupported_extension"] += 1
                continue

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


def _validate_entry_type(entry: ZipInfo) -> None:
    mode = entry.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}:
        raise DriftGuardError(
            code="unsafe_repository_archive",
            message="The repository ZIP contains a link or special file.",
        )


def _unsafe_path() -> None:
    raise DriftGuardError(
        code="unsafe_repository_archive",
        message="The repository ZIP contains an unsafe file path.",
    )


def _is_ignored(path: str) -> bool:
    return any(part.casefold() in IGNORED_DIRECTORIES for part in PurePosixPath(path).parts)
