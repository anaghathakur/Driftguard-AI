"""Replaceable deterministic and Gemini structured patch providers."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from apps.api.app.migration.provider import MigrationProviderError
from apps.api.app.patches.context import PatchGenerationContext, PatchPrompt
from apps.api.app.schemas.comparison import ChangeType
from apps.api.app.schemas.patch import (
    GeneratedPatchContent,
    PatchProvider,
    PatchProviderMode,
    StructuredPatchEdit,
    StructuredPatchFile,
)

JsonSender = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class PatchProviderError(RuntimeError):
    """Safe patch provider failure."""


class PatchGenerationProvider(ABC):
    name: PatchProvider
    model_name: str
    mode: PatchProviderMode

    @abstractmethod
    def generate(
        self,
        context: PatchGenerationContext,
        prompt: PatchPrompt,
    ) -> GeneratedPatchContent:
        """Return strict structured edits, never a raw diff."""

    @property
    def available(self) -> bool:
        return True

    @property
    def warning(self) -> str | None:
        return None


class MockPatchGenerationProvider(PatchGenerationProvider):
    """Useful zero-cost provider for conservative request-field migrations."""

    name = PatchProvider.MOCK
    model_name = "deterministic-patch-mock-v1"
    mode = PatchProviderMode.DETERMINISTIC_MOCK

    def generate(
        self,
        context: PatchGenerationContext,
        prompt: PatchPrompt,
    ) -> GeneratedPatchContent:
        del prompt
        migration_change_ids = {item.change_id for item in context.migrations}
        removed = sorted(
            (
                change
                for change in context.changes
                if change.change_type == ChangeType.REQUEST_FIELD_REMOVED
                and change.subject
                and change.change_id in migration_change_ids
            ),
            key=lambda change: (change.path, change.method, change.subject or ""),
        )
        required = sorted(
            (
                change
                for change in context.changes
                if change.change_type == ChangeType.REQUIRED_REQUEST_FIELD_ADDED
                and change.subject
                and change.change_id in migration_change_ids
            ),
            key=lambda change: (change.path, change.method, change.subject or ""),
        )
        direct_paths = {
            match.file_path
            for match in context.matches
            if match.impact_depth == 0
        }
        files: list[StructuredPatchFile] = []
        for source in sorted(context.source_files, key=lambda item: item.path):
            if source.path not in direct_paths:
                continue
            language = _language(source.path)
            if language is None:
                continue
            edits: list[StructuredPatchEdit] = []
            pair = _matching_pair(removed, required)
            if pair is not None:
                old_change, new_change = pair
                edits = _rename_field_edits(
                    source.content,
                    language,
                    old_change.subject or "",
                    new_change.subject or "",
                    [old_change.change_id, new_change.change_id],
                )
            elif removed:
                change = removed[0]
                edits = _remove_field_edits(
                    source.content,
                    language,
                    change.subject or "",
                    [change.change_id],
                )
            elif required:
                change = required[0]
                edits = _add_field_edits(
                    source.content,
                    language,
                    change.subject or "",
                    [change.change_id],
                )
            if edits:
                symbol = next(
                    (
                        match.symbol
                        for match in context.matches
                        if match.file_path == source.path and match.impact_depth == 0
                    ),
                    None,
                )
                files.append(
                    StructuredPatchFile(
                        file_path=source.path,
                        language=language,
                        related_symbol=symbol,
                        edits=edits,
                    )
                )
                break
        if not files:
            raise PatchProviderError(
                "No conservative request-field patch pattern was applicable."
            )
        return GeneratedPatchContent(
            summary="Update the direct API client for the changed request fields.",
            files=files,
            warnings=[
                "This proposed patch is static and has not been executed or tested."
            ],
        )


class GeminiPatchGenerationProvider(PatchGenerationProvider):
    """Optional Gemini provider with strict structured output."""

    name = PatchProvider.GEMINI
    mode = PatchProviderMode.EXTERNAL

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        max_retries: int,
        sender: JsonSender,
    ) -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name.strip() or "configured-gemini-model"
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(0, min(int(max_retries), 2))
        self._sender = sender

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def warning(self) -> str | None:
        if self.available:
            return None
        return "Gemini patch generation is configured without an API key."

    def generate(
        self,
        context: PatchGenerationContext,
        prompt: PatchPrompt,
    ) -> GeneratedPatchContent:
        del context
        if not self.api_key:
            raise PatchProviderError("Gemini API key is not configured.")
        payload = {
            "systemInstruction": {"parts": [{"text": prompt.system_instruction}]},
            "contents": [
                {"role": "user", "parts": [{"text": prompt.user_prompt}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": patch_content_json_schema(),
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent"
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._sender(
                    url,
                    {"Content-Type": "application/json", "x-goog-api-key": self.api_key},
                    payload,
                    self.timeout_seconds,
                )
                text = _extract_text(response)
                return GeneratedPatchContent.model_validate_json(text)
            except (PatchProviderError, ValidationError, MigrationProviderError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(0.15 * (attempt + 1))
            except Exception as exc:
                last_error = exc
                break
        raise PatchProviderError("Gemini did not return a valid patch proposal.") from last_error


def patch_content_json_schema() -> dict[str, Any]:
    string = {"type": "string"}
    edit = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "expected_original": {**string, "minLength": 1, "maxLength": 50_000},
            "replacement": {**string, "maxLength": 50_000},
            "reason": {**string, "minLength": 1, "maxLength": 500},
            "related_change_ids": {
                "type": "array",
                "items": string,
                "minItems": 1,
                "maxItems": 10,
            },
        },
        "required": [
            "expected_original",
            "replacement",
            "reason",
            "related_change_ids",
        ],
    }
    patch_file = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "file_path": {**string, "minLength": 1, "maxLength": 500},
            "language": {**string, "minLength": 1, "maxLength": 30},
            "related_symbol": {**string, "maxLength": 500},
            "edits": {
                "type": "array",
                "items": edit,
                "minItems": 1,
                "maxItems": 50,
            },
        },
        "required": ["file_path", "language", "related_symbol", "edits"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {**string, "minLength": 1, "maxLength": 500},
            "files": {
                "type": "array",
                "items": patch_file,
                "minItems": 1,
                "maxItems": 20,
            },
            "warnings": {
                "type": "array",
                "items": {**string, "maxLength": 500},
                "maxItems": 10,
            },
        },
        "required": ["summary", "files", "warnings"],
    }


def _extract_text(response: dict[str, Any]) -> str:
    try:
        text = response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PatchProviderError("Gemini response did not contain structured output.") from exc
    if not isinstance(text, str) or not text.strip():
        raise PatchProviderError("Gemini response output was empty.")
    return text


def _matching_pair(removed: list[Any], required: list[Any]) -> tuple[Any, Any] | None:
    for old in removed:
        for new in required:
            if old.path == new.path and old.method == new.method:
                return old, new
    return None


def _language(path: str) -> str | None:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
    }.get(suffix)


def _rename_field_edits(
    source: str,
    language: str,
    old_name: str,
    new_name: str,
    change_ids: list[str],
) -> list[StructuredPatchEdit]:
    old_identifier = old_name if language == "python" else _camel(old_name)
    new_identifier = new_name if language == "python" else _camel(new_name)
    edits: list[StructuredPatchEdit] = []
    signature = _signature_line(source, old_identifier, language)
    if signature:
        edits.append(
            _edit(
                signature,
                _replace_token(signature, old_identifier, new_identifier),
                f"Rename the request value from {old_name} to {new_name}.",
                change_ids,
            )
        )
    payload = _payload_line(source, old_name, old_identifier)
    if payload:
        replacement = _replace_payload(
            payload,
            old_name,
            new_name,
            old_identifier,
            new_identifier,
        )
        edits.append(
            _edit(
                payload,
                replacement,
                f"Send the required '{new_name}' field instead of '{old_name}'.",
                change_ids,
            )
        )
    return edits if payload and len(edits) >= 1 else []


def _remove_field_edits(
    source: str,
    language: str,
    name: str,
    change_ids: list[str],
) -> list[StructuredPatchEdit]:
    identifier = name if language == "python" else _camel(name)
    edits: list[StructuredPatchEdit] = []
    signature = _signature_line(source, identifier, language)
    if signature:
        replacement = re.sub(rf",\s*{re.escape(identifier)}\b", "", signature, count=1)
        if replacement == signature:
            replacement = re.sub(
                rf"\b{re.escape(identifier)}\s*,\s*", "", signature, count=1
            )
        if replacement != signature:
            edits.append(_edit(signature, replacement, f"Remove '{name}' input.", change_ids))
    payload = _payload_line(source, name, identifier)
    if payload:
        edits.append(_edit(payload, "", f"Stop sending removed field '{name}'.", change_ids))
    return edits if payload else []


def _add_field_edits(
    source: str,
    language: str,
    name: str,
    change_ids: list[str],
) -> list[StructuredPatchEdit]:
    identifier = name if language == "python" else _camel(name)
    signature = _first_matching_line(
        source,
        lambda line: ("def " in line if language == "python" else "function " in line)
        and ")" in line,
    )
    payload_open = _first_matching_line(
        source,
        lambda line: re.search(r"\bpayload\b\s*=\s*\{", line) is not None,
    )
    if not signature or not payload_open:
        return []
    opening = signature.index("(")
    closing = signature.index(")", opening)
    parameters = signature[opening + 1 : closing].strip()
    added_parameters = f"{parameters}, {identifier}" if parameters else identifier
    signature_replacement = (
        signature[: opening + 1] + added_parameters + signature[closing:]
    )
    indentation = re.match(r"\s*", payload_open).group(0) + "    "
    value = f'"{name}": {identifier},' if language == "python" else f"{name}: {identifier},"
    payload_replacement = payload_open + indentation + value + "\n"
    return [
        _edit(signature, signature_replacement, f"Accept required field '{name}'.", change_ids),
        _edit(payload_open, payload_replacement, f"Send required field '{name}'.", change_ids),
    ]


def _signature_line(source: str, identifier: str, language: str) -> str | None:
    return _first_matching_line(
        source,
        lambda line: ("def " in line if language == "python" else "function " in line)
        and re.search(rf"\b{re.escape(identifier)}\b", line) is not None,
    )


def _payload_line(source: str, field: str, identifier: str) -> str | None:
    field_pattern = rf"(?:['\"]{re.escape(field)}['\"]|\b{re.escape(field)}\b)\s*:"
    identifier_pattern = re.compile(rf"\b{re.escape(identifier)}\b")
    return _first_matching_line(
        source,
        lambda line: re.search(field_pattern, line) is not None
        and (
            re.search(rf"['\"]{re.escape(field)}['\"]\s*:", line) is not None
            or len(identifier_pattern.findall(line)) >= 2
        ),
    )


def _first_matching_line(source: str, predicate: Callable[[str], bool]) -> str | None:
    matches = [line for line in source.splitlines(keepends=True) if predicate(line)]
    return matches[0] if len(matches) == 1 else None


def _replace_token(value: str, old: str, new: str) -> str:
    return re.sub(rf"\b{re.escape(old)}\b", new, value)


def _replace_payload(
    value: str,
    old_field: str,
    new_field: str,
    old_identifier: str,
    new_identifier: str,
) -> str:
    replaced = re.sub(
        rf"(['\"]){re.escape(old_field)}\1",
        lambda match: f"{match.group(1)}{new_field}{match.group(1)}",
        value,
        count=1,
    )
    if replaced == value:
        replaced = re.sub(rf"\b{re.escape(old_field)}\b(?=\s*:)", new_field, value, count=1)
    return re.sub(
        rf"(?<=:)\s*{re.escape(old_identifier)}\b",
        lambda match: match.group(0).replace(old_identifier, new_identifier),
        replaced,
        count=1,
    )


def _edit(
    original: str,
    replacement: str,
    reason: str,
    change_ids: list[str],
) -> StructuredPatchEdit:
    return StructuredPatchEdit(
        expected_original=original,
        replacement=replacement,
        reason=reason,
        related_change_ids=sorted(set(change_ids)),
    )


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)
