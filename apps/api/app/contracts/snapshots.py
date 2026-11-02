"""Integrity checks for private, bounded contract snapshots."""

import hashlib

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError


def verify_sources(analysis, old: bytes, new: bytes) -> None:
    if analysis is None:
        raise DriftGuardError(
            code="analysis_not_found", message="The requested analysis does not exist.",
            status_code=404,
        )
    for content, expected in (
        (old, analysis.old_file_sha256), (new, analysis.new_file_sha256)
    ):
        if (
            len(content) > settings.max_graphql_document_bytes
            or hashlib.sha256(content).hexdigest() != expected
        ):
            raise DriftGuardError(
                code="contract_snapshot_mismatch",
                message="The stored contract does not match this analysis. Run a new analysis.",
                status_code=409,
            )
