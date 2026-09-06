"""Trusted validation, in-memory application, and unified diff rendering."""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.redaction import redact_secrets
from apps.api.app.domain.repository import RepositoryScan
from apps.api.app.graphql.validation import validate_graphql_document
from apps.api.app.repository.code_analyzer import validate_javascript_syntax
from apps.api.app.schemas.patch import (
    GeneratedPatchContent,
    PatchValidationResult,
    StructuredPatchFile,
)

_JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}


@dataclass(frozen=True, slots=True)
class ValidatedPatch:
    files: list[StructuredPatchFile]
    unified_diff: str
    validation: PatchValidationResult
    modified_sources: dict[str, str]


def validate_patch(
    generated: GeneratedPatchContent,
    repository: RepositoryScan,
    allowed_files: set[str],
    *,
    max_files: int = settings.max_patch_files,
    max_edits: int = settings.max_patch_edits,
    max_replacement_bytes: int = settings.max_patch_replacement_bytes,
    max_diff_bytes: int = settings.max_patch_diff_bytes,
) -> ValidatedPatch:
    if len(generated.files) > max_files:
        _limit("files", max_files)
    edit_count = sum(len(file.edits) for file in generated.files)
    if edit_count > max_edits:
        _limit("edits", max_edits)

    source_map = {source.path: source.content for source in repository.files}
    seen_paths: set[str] = set()
    modified: dict[str, str] = {}
    diffs: list[str] = []
    validated_files: list[StructuredPatchFile] = []

    for patch_file in sorted(generated.files, key=lambda item: item.file_path):
        path = _validated_patch_path(patch_file.file_path)
        if path in seen_paths:
            _error("patch_edit_conflict", "The proposal contains duplicate file entries.")
        seen_paths.add(path)
        if path not in source_map:
            _error("patch_edit_not_applicable", "A proposed patch target does not exist.")
        if path not in allowed_files:
            _error(
                "patch_target_not_allowed",
                "A proposed patch target is outside the detected impact scope.",
            )

        original = source_map[path]
        spans: list[tuple[int, int, object]] = []
        seen_edits: set[tuple[str, str]] = set()
        for edit in patch_file.edits:
            pair = (edit.expected_original, edit.replacement)
            if pair in seen_edits:
                _error("patch_edit_conflict", "The proposal contains a duplicate edit.")
            seen_edits.add(pair)
            if len(edit.replacement.encode("utf-8")) > max_replacement_bytes:
                _limit("replacement_bytes", max_replacement_bytes)
            if redact_secrets(edit.expected_original)[1] or redact_secrets(edit.replacement)[1]:
                _error(
                    "patch_output_invalid",
                    "The proposed edit contains secret-like source data.",
                )
            occurrences = original.count(edit.expected_original)
            if occurrences == 0:
                _error(
                    "patch_edit_not_applicable",
                    "The expected original source text was not found.",
                )
            if occurrences > 1:
                _error(
                    "patch_edit_ambiguous",
                    "The expected original source text is not unique.",
                )
            start = original.index(edit.expected_original)
            end = start + len(edit.expected_original)
            spans.append((start, end, edit))

        spans.sort(key=lambda item: (item[0], item[1]))
        for previous, current in zip(spans, spans[1:], strict=False):
            if current[0] < previous[1]:
                _error("patch_edit_conflict", "The proposal contains overlapping edits.")

        changed = original
        for start, end, edit in reversed(spans):
            changed = changed[:start] + edit.replacement + changed[end:]
        if changed == original:
            _error("patch_validation_failed", "The proposed patch makes no source change.")
        _validate_language(path, changed)
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                changed.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="\n",
            )
        )
        diffs.append(diff)
        modified[path] = changed
        validated_files.append(patch_file.model_copy(update={"file_path": path}))

    unified_diff = "".join(diffs)
    if not unified_diff:
        _error("patch_validation_failed", "The proposal did not produce a diff.")
    if len(unified_diff.encode("utf-8")) > max_diff_bytes:
        _limit("diff_bytes", max_diff_bytes)
    return ValidatedPatch(
        files=validated_files,
        unified_diff=unified_diff,
        modified_sources=modified,
        validation=PatchValidationResult(
            source_snapshot_verified=True,
            paths_safe=True,
            allowed_scope_verified=True,
            edit_anchors_verified=True,
            syntax_valid=True,
            limits_valid=True,
            warnings=[],
        ),
    )


def _validated_patch_path(path: str) -> str:
    if not path or "\\" in path or path.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", path):
        _unsafe_path()
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _unsafe_path()
    normalized = PurePosixPath(*parts).as_posix()
    if normalized != path:
        _unsafe_path()
    return normalized


def _validate_language(path: str, content: str) -> None:
    suffix = PurePosixPath(path).suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(content, filename=path)
        elif suffix in _JS_SUFFIXES:
            validate_javascript_syntax(content)
        elif suffix in {".graphql", ".gql"}:
            validate_graphql_document(content)
        else:
            _error(
                "patch_validation_failed",
                "The proposed patch language does not support static syntax validation.",
            )
    except (SyntaxError, ValueError) as exc:
        raise DriftGuardError(
            code="patch_validation_failed",
            message="The proposed patch did not pass static syntax validation.",
            status_code=422,
        ) from exc


def _unsafe_path() -> None:
    _error("patch_target_not_allowed", "The proposed patch contains an unsafe path.")


def _limit(limit: str, maximum: int) -> None:
    raise DriftGuardError(
        code="patch_limit_exceeded",
        message="The proposed patch exceeds a configured safety limit.",
        status_code=413,
        details={"limit": limit, "maximum": maximum},
    )


def _error(code: str, message: str) -> None:
    raise DriftGuardError(code=code, message=message, status_code=422)
