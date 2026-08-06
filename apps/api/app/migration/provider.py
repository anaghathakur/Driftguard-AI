"""Replaceable mock and Gemini migration recommendation providers."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from apps.api.app.migration.context import (
    MigrationContext,
    PromptBuildResult,
)
from apps.api.app.migration.fallback import (
    deterministic_recommendation,
)
from apps.api.app.schemas.migration import (
    GeneratedMigrationContent,
    MigrationProvider,
)

JsonSender = Callable[
    [str, dict[str, str], dict[str, Any], float],
    dict[str, Any],
]


class MigrationProviderError(RuntimeError):
    """Safe base error for provider failures."""

    retryable = False


class MigrationTransportError(MigrationProviderError):
    """Network or remote provider status error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)

        self.status_code = status_code
        self.retryable = retryable


class MigrationResponseError(MigrationProviderError):
    """Provider output could not be validated."""

    retryable = True


class MigrationRecommendationProvider(ABC):
    """Shared interface implemented by all providers."""

    name: MigrationProvider
    model_name: str

    @abstractmethod
    def generate(
        self,
        context: MigrationContext,
        prompt: PromptBuildResult,
    ) -> GeneratedMigrationContent:
        """Generate one validated recommendation."""

    @property
    def available(self) -> bool:
        """Whether the provider is ready."""

        return True

    @property
    def warning(self) -> str | None:
        """Safe configuration warning."""

        return None


class MockMigrationRecommendationProvider(
    MigrationRecommendationProvider
):
    """Offline deterministic provider used by default."""

    name = MigrationProvider.MOCK
    model_name = "deterministic-mock-v1"

    def generate(
        self,
        context: MigrationContext,
        prompt: PromptBuildResult,
    ) -> GeneratedMigrationContent:
        del prompt

        return deterministic_recommendation(context)


class GeminiMigrationRecommendationProvider(
    MigrationRecommendationProvider
):
    """Optional Gemini provider with validated JSON output."""

    name = MigrationProvider.GEMINI

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float = 20,
        max_retries: int = 1,
        sender: JsonSender | None = None,
    ) -> None:
        self.api_key = api_key.strip()

        self.model_name = (
            model_name.strip()
            or "configured-gemini-model"
        )

        self.timeout_seconds = max(
            1.0,
            float(timeout_seconds),
        )

        self.max_retries = max(
            0,
            min(int(max_retries), 2),
        )

        self._sender = sender or _send_json

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def warning(self) -> str | None:
        if self.api_key:
            return None

        return (
            "Gemini is configured but "
            "DRIFTGUARD_GEMINI_API_KEY is missing."
        )

    def generate(
        self,
        context: MigrationContext,
        prompt: PromptBuildResult,
    ) -> GeneratedMigrationContent:
        del context

        if not self.api_key:
            raise MigrationProviderError(
                "Gemini API key is not configured."
            )

        url = (
            "https://generativelanguage.googleapis.com/"
            "v1beta/models/"
            f"{self.model_name}:generateContent"
        )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": prompt.system_instruction,
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt.user_prompt,
                        }
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": migration_content_json_schema(),
            },
        }

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._sender(
                    url,
                    headers,
                    payload,
                    self.timeout_seconds,
                )

                text = _extract_text(response)

                try:
                    return (
                        GeneratedMigrationContent
                        .model_validate_json(text)
                    )
                except ValidationError as exc:
                    raise MigrationResponseError(
                        
                            "Gemini output did not match "
                            "the migration schema."
                        
                    ) from exc

            except Exception as exc:
                last_error = exc

                if (
                    attempt >= self.max_retries
                    or not _retryable(exc)
                ):
                    break

                time.sleep(0.15 * (attempt + 1))

        raise MigrationProviderError(
            
                "Gemini did not return a valid "
                "migration recommendation."
            
        ) from last_error


def migration_content_json_schema() -> dict[str, Any]:
    """Return the JSON schema expected from Gemini."""

    string_array = {
        "type": "array",
        "items": {
            "type": "string",
            "maxLength": 500,
        },
        "maxItems": 8,
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {
                "type": "string",
                "maxLength": 500,
            },
            "why_it_matters": {
                "type": "string",
                "maxLength": 1_000,
            },
            "affected_code_explanation": {
                "type": "string",
                "maxLength": 1_000,
            },
            "migration_steps": string_array,
            "suggested_tests": string_array,
            "code_example": {
                "type": "string",
                "maxLength": 2_000,
            },
            "assumptions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "maxLength": 500,
                },
                "maxItems": 6,
            },
            "warnings": string_array,
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "required": [
            "summary",
            "why_it_matters",
            "affected_code_explanation",
            "migration_steps",
            "suggested_tests",
            "code_example",
            "assumptions",
            "warnings",
            "confidence",
        ],
    }


def _send_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(  # noqa: S310
            request,
            timeout=timeout,
        ) as response:
            return json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        raise MigrationTransportError(
            f"Gemini HTTP status {exc.code}",
            status_code=exc.code,
            retryable=exc.code
            in {
                408,
                429,
                500,
                502,
                503,
                504,
            },
        ) from exc

    except (
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise MigrationTransportError(
            "Gemini network request failed.",
            retryable=True,
        ) from exc

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise MigrationResponseError(
            "Gemini returned an invalid JSON envelope."
        ) from exc


def _extract_text(
    response: dict[str, Any],
) -> str:
    try:
        parts = response["candidates"][0]["content"]["parts"]

        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
        )

    except (
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise MigrationResponseError(
            "Gemini response did not contain text output."
        ) from exc

    if not text.strip():
        raise MigrationResponseError(
            "Gemini response text was empty."
        )

    return text


def _retryable(
    exc: Exception,
) -> bool:
    return bool(
        getattr(exc, "retryable", False)
    )