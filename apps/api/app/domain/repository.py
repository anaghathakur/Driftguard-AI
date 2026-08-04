"""Repository source models used by deterministic impact analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScannedSourceFile:
    path: str
    content: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RepositoryScan:
    archive_sha256: str
    archive_entries: int
    files: tuple[ScannedSourceFile, ...]
    skipped_files: int
    skipped_reasons: dict[str, int]

    @property
    def scanned_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files)
