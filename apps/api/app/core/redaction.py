"""Shared secret redaction used before provider calls and persistence."""

from __future__ import annotations

import re

_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            (
                r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
                r"-----END [A-Z0-9 ]*PRIVATE KEY-----"
            ),
            re.IGNORECASE | re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(
            r"\bBearer\s+[A-Za-z0-9._~+\-/]+=*",
            re.IGNORECASE,
        ),
        "Bearer [REDACTED_TOKEN]",
    ),
    (
        re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "[REDACTED_ACCESS_KEY]",
    ),
    (
        re.compile(
            r"(?i)([\"'])"
            r"(api[_-]?key|secret|password|passwd|token|connection[_-]?string)"
            r"\1(\s*:\s*)([\"'])([^\"'\r\n]{4,})\4"
        ),
        r"\1\2\1\3\4[REDACTED]\4",
    ),
    (
        re.compile(
            r"(?i)\b"
            r"(api[_-]?key|secret|password|passwd|token|connection[_-]?string)"
            r"\b(\s*[:=]\s*)"
            r"([\"'][^\"'\r\n]{4,}[\"']|[^\s,;]{8,})"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s\"']+"),
        "[REDACTED_CONNECTION_STRING]",
    ),
)


def redact_secrets(text: str) -> tuple[str, int]:
    """
    Redact likely credentials from text.

    Returns:
        A tuple containing the safe text and the number of replacements.
    """

    result = text
    total = 0

    for pattern, replacement in _REDACTION_RULES:
        result, count = pattern.subn(replacement, result)
        total += count

    return result, total
