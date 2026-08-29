"""Reusable untrusted-repository filtering and bounded-source policy."""

from __future__ import annotations

from pathlib import PurePosixPath

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".venv",
        "__pycache__",
        "bin",
        "build",
        "coverage",
        "dist",
        "env",
        "node_modules",
        "obj",
        "out",
        "target",
        "vendor",
        "venv",
    }
)

IGNORED_FILE_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dylib",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".lock",
        ".map",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".tar",
        ".tgz",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".zip",
    }
)


class RepositoryFilteringPolicy:
    def __init__(self, source_extensions: frozenset[str]) -> None:
        self.source_extensions = source_extensions

    def reason_to_skip(self, path: str) -> str | None:
        normalized = PurePosixPath(path.replace("\\", "/"))
        if any(part.casefold() in IGNORED_DIRECTORY_NAMES for part in normalized.parts):
            return "ignored_path"
        suffix = normalized.suffix.casefold()
        if suffix in IGNORED_FILE_SUFFIXES:
            return "ignored_artifact"
        if suffix not in self.source_extensions:
            return "unsupported_extension"
        return None

    def includes(self, path: str) -> bool:
        return self.reason_to_skip(path) is None
