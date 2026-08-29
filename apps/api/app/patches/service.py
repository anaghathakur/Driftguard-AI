"""Orchestrate snapshot-grounded, review-only patch proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.redaction import redact_secrets
from apps.api.app.domain.analysis import AnalysisKind, AnalysisStatus, RepositorySourceType
from apps.api.app.patches.context import (
    PatchGenerationContext,
    build_patch_prompt,
)
from apps.api.app.patches.provider import PatchGenerationProvider, PatchProviderError
from apps.api.app.patches.validator import validate_patch
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.repository.github_source import GitHubRepositorySource
from apps.api.app.repository.scanner import RepositoryArchiveScanner
from apps.api.app.schemas.analysis import PersistedMatchResponse
from apps.api.app.schemas.patch import (
    GeneratedPatchContent,
    PatchProposal,
    PatchProposalListItem,
    PatchStatus,
)

PATCH_PROFILE_VERSION = "1.0.0"


class PatchProposalService:
    def __init__(
        self,
        repository: AnalysisRepository,
        provider: PatchGenerationProvider,
        github_source: GitHubRepositorySource,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.github_source = github_source

    async def generate(
        self,
        analysis_id: str,
        *,
        repository_content: bytes | None = None,
        repository_filename: str | None = None,
    ) -> PatchProposal:
        analysis = self._require_eligible_analysis(analysis_id)
        scan = await self._verified_source(
            analysis,
            repository_content=repository_content,
            repository_filename=repository_filename,
        )
        changes = self.repository.get_changes(analysis_id)
        matches = tuple(
            PersistedMatchResponse.model_validate(asdict(item))
            for item in self.repository.get_matches(analysis_id)
        )
        migrations = tuple(self.repository.get_migration_recommendations(analysis_id))
        risks = tuple(self.repository.get_risk_predictions(analysis_id))
        if not migrations:
            raise DriftGuardError(
                code="patch_generation_failed",
                message="No migration recommendation is available to ground a safe patch.",
                status_code=422,
            )
        direct_files = {match.file_path for match in matches if match.impact_depth == 0}
        allowed_files = tuple(sorted(direct_files or {match.file_path for match in matches}))
        if not allowed_files:
            raise DriftGuardError(
                code="patch_generation_failed",
                message="No impacted source file is available for a safe proposed patch.",
                status_code=422,
            )
        fingerprint = _patch_fingerprint(
            analysis_id=analysis_id,
            repository_hash=scan.archive_sha256,
            provider=self.provider.name.value,
            model=self.provider.model_name,
            migration_ids=[item.recommendation_id for item in migrations],
            change_ids=[item.change_id for item in changes],
        )
        existing = self.repository.get_patch_by_fingerprint(analysis_id, fingerprint)
        if existing is not None:
            return existing

        context = PatchGenerationContext(
            analysis_id=analysis_id,
            changes=tuple(changes),
            matches=matches,
            migrations=migrations,
            risks=risks,
            source_files=scan.files,
            allowed_files=allowed_files,
        )
        try:
            prompt = build_patch_prompt(
                context,
                max_context_bytes=settings.max_patch_context_bytes,
            )
        except ValueError as exc:
            raise DriftGuardError(
                code="patch_limit_exceeded",
                message="The bounded patch context exceeds its configured limit.",
                status_code=413,
            ) from exc
        try:
            generated = self.provider.generate(context, prompt)
        except PatchProviderError as exc:
            raise DriftGuardError(
                code="patch_generation_failed",
                message="No safe proposed patch could be generated for this analysis.",
                status_code=422,
            ) from exc
        generated, output_redactions = _sanitize_generated(generated)
        validated = validate_patch(
            generated,
            scan,
            set(allowed_files),
        )
        warnings = list(
            dict.fromkeys(
                [
                    *generated.warnings,
                    *prompt.warnings,
                    *validated.validation.warnings,
                    *([self.provider.warning] if self.provider.warning else []),
                ]
            )
        )[:10]
        proposal = PatchProposal(
            patch_id=str(uuid5(NAMESPACE_URL, f"driftguard-patch:{fingerprint}")),
            analysis_id=analysis_id,
            created_at=datetime.now(UTC),
            status=PatchStatus.VALIDATED,
            summary=generated.summary,
            provider=self.provider.name,
            provider_model=self.provider.model_name,
            provider_mode=self.provider.mode,
            patch_profile_version=PATCH_PROFILE_VERSION,
            source_repository_hash=scan.archive_sha256,
            request_fingerprint=fingerprint,
            files_changed=len(validated.files),
            edit_count=sum(len(item.edits) for item in validated.files),
            validation=validated.validation,
            warnings=warnings,
            unified_diff=validated.unified_diff,
            files=validated.files,
            redactions_applied=prompt.redactions_applied + output_redactions,
        )
        return self.repository.save_patch_proposal(proposal)

    def list(self, analysis_id: str) -> list[PatchProposalListItem]:
        self._require_analysis(analysis_id)
        return [
            PatchProposalListItem.model_validate(
                proposal.model_dump(
                    include={
                        "patch_id",
                        "analysis_id",
                        "created_at",
                        "status",
                        "summary",
                        "provider",
                        "provider_model",
                        "files_changed",
                        "edit_count",
                    }
                )
            )
            for proposal in self.repository.list_patch_proposals(analysis_id)
        ]

    def get(self, analysis_id: str, patch_id: str) -> PatchProposal:
        self._require_analysis(analysis_id)
        proposal = self.repository.get_patch_proposal(analysis_id, patch_id)
        if proposal is None:
            raise DriftGuardError(
                code="patch_proposal_not_found",
                message="The requested patch proposal does not exist.",
                status_code=404,
            )
        return proposal

    def _require_analysis(self, analysis_id: str):
        analysis = self.repository.get_analysis(analysis_id)
        if analysis is None:
            raise DriftGuardError(
                code="analysis_not_found",
                message="The requested analysis does not exist.",
                status_code=404,
            )
        return analysis

    def _require_eligible_analysis(self, analysis_id: str):
        analysis = self._require_analysis(analysis_id)
        if analysis.status != AnalysisStatus.SUCCEEDED or analysis.kind != AnalysisKind.IMPACT:
            raise DriftGuardError(
                code="patch_generation_failed",
                message="Only a completed repository-impact analysis can generate a patch.",
                status_code=409,
            )
        if not analysis.repository_file_sha256:
            raise DriftGuardError(
                code="repository_source_required",
                message="The original repository source is required to generate a patch.",
                status_code=422,
            )
        return analysis

    async def _verified_source(
        self,
        analysis,
        *,
        repository_content: bytes | None,
        repository_filename: str | None,
    ):
        source_type = analysis.repository_source_type or RepositorySourceType.ZIP
        if source_type == RepositorySourceType.GITHUB:
            if not analysis.repository_url:
                raise DriftGuardError(
                    code="repository_source_required",
                    message="The original GitHub source metadata is unavailable.",
                    status_code=422,
                )
            archive = await self.github_source.fetch(
                analysis.repository_url,
                ref=analysis.repository_ref,
            )
            filename = archive.filename
            content = archive.content
        else:
            if repository_content is None:
                raise DriftGuardError(
                    code="repository_source_required",
                    message="Upload the original repository ZIP to generate a patch.",
                    status_code=422,
                )
            filename = repository_filename or analysis.repository_filename or "repository.zip"
            content = repository_content
        scan = RepositoryArchiveScanner().scan(filename, content)
        if scan.archive_sha256 != analysis.repository_file_sha256:
            raise DriftGuardError(
                code="repository_snapshot_mismatch",
                message=(
                    "The repository has changed since this analysis was created. "
                    "Run a new DriftGuard analysis before generating a patch."
                ),
                status_code=409,
            )
        return scan


def _patch_fingerprint(
    *,
    analysis_id: str,
    repository_hash: str,
    provider: str,
    model: str,
    migration_ids: list[str],
    change_ids: list[str],
) -> str:
    payload = json.dumps(
        {
            "analysis_id": analysis_id,
            "repository_hash": repository_hash,
            "patch_profile_version": PATCH_PROFILE_VERSION,
            "provider": provider,
            "model": model,
            "migration_ids": sorted(migration_ids),
            "change_ids": sorted(change_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sanitize_generated(
    generated: GeneratedPatchContent,
) -> tuple[GeneratedPatchContent, int]:
    total = 0

    def clean(value: str, maximum: int) -> str:
        nonlocal total
        safe, count = redact_secrets(value)
        total += count
        return safe[:maximum]

    return (
        GeneratedPatchContent(
            summary=clean(generated.summary, 500),
            warnings=[clean(item, 500) for item in generated.warnings],
            files=[
                patch_file.model_copy(
                    update={
                        "edits": [
                            edit.model_copy(update={"reason": clean(edit.reason, 500)})
                            for edit in patch_file.edits
                        ]
                    }
                )
                for patch_file in generated.files
            ],
        ),
        total,
    )
