"""Orchestrate snapshot-grounded static patch validation and test intelligence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.analysis import RepositorySourceType
from apps.api.app.patches.validator import validate_patch
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.repository.code_analyzer import RepositoryCodeAnalyzer
from apps.api.app.repository.github_source import GitHubRepositorySource
from apps.api.app.repository.scanner import RepositoryArchiveScanner
from apps.api.app.schemas.analysis import PersistedMatchResponse
from apps.api.app.schemas.patch import GeneratedPatchContent
from apps.api.app.schemas.validation import (
    FindingStatus,
    PatchValidationListItem,
    PatchValidationRun,
    ValidationReadiness,
)
from apps.api.app.validation.engine import (
    discover_related_tests,
    find_test_gaps,
    patched_repository,
    validate_blast_radius,
    validate_contract,
    validate_dependencies,
)
from apps.api.app.validation.provider import (
    MockTestPlanProvider,
    TestPlanContext,
    TestPlanProvider,
    TestPlanProviderError,
)

VALIDATION_PROFILE_VERSION = "1.0.0"


class PatchValidationService:
    def __init__(
        self,
        repository: AnalysisRepository,
        provider: TestPlanProvider,
        github_source: GitHubRepositorySource,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.github_source = github_source

    async def validate(
        self,
        analysis_id: str,
        patch_id: str,
        *,
        repository_content: bytes | None = None,
        repository_filename: str | None = None,
    ) -> PatchValidationRun:
        analysis = self.repository.get_analysis(analysis_id)
        if analysis is None:
            raise DriftGuardError(
                code="analysis_not_found",
                message="The requested analysis does not exist.",
                status_code=404,
            )
        proposal = self.repository.get_patch_proposal(analysis_id, patch_id)
        if proposal is None:
            raise DriftGuardError(
                code="patch_proposal_not_found",
                message="The requested patch proposal does not exist.",
                status_code=404,
            )
        scan = await self._verified_source(
            analysis,
            proposal.source_repository_hash,
            repository_content=repository_content,
            repository_filename=repository_filename,
        )
        fingerprint = _validation_fingerprint(
            analysis_id=analysis_id,
            patch_id=patch_id,
            source_hash=scan.archive_sha256,
            provider=self.provider.name.value,
            model=self.provider.model_name,
        )
        existing = self.repository.get_patch_validation_by_fingerprint(
            analysis_id, patch_id, fingerprint
        )
        if existing is not None:
            return existing

        matches = [
            PersistedMatchResponse.model_validate(asdict(item))
            for item in self.repository.get_matches(analysis_id)
        ]
        changes = self.repository.get_changes(analysis_id)
        allowed_files = {match.file_path for match in matches if match.impact_depth == 0} or {
            match.file_path for match in matches
        }
        generated = GeneratedPatchContent(
            summary=proposal.summary,
            files=proposal.files,
            warnings=proposal.warnings,
        )
        trusted = validate_patch(generated, scan, allowed_files)
        patched = patched_repository(scan, trusted.modified_sources)
        analyzer = RepositoryCodeAnalyzer()
        original_graph = analyzer.analyze(scan)
        patched_graph = analyzer.analyze(patched)

        contract_findings = validate_contract(changes, patched_graph, patched)
        dependency_findings = validate_dependencies(
            changes, scan, patched, original_graph, patched_graph, proposal
        )
        scope_findings, direct_files, transitive_files, unrelated = validate_blast_radius(
            proposal, matches
        )
        dependency_findings.extend(scope_findings)
        if patched_graph.summary.parser_failures:
            from apps.api.app.schemas.validation import (  # local import keeps the engine API small
                FindingCategory,
                FindingSeverity,
                ValidationFinding,
            )

            dependency_findings.append(
                ValidationFinding(
                    check_id="static-analysis:parser-failures",
                    category=FindingCategory.STATIC_ANALYSIS,
                    status=FindingStatus.UNKNOWN,
                    severity=FindingSeverity.MEDIUM,
                    message=(
                        "Some supported files could not be parsed during patched-snapshot "
                        "reanalysis."
                    ),
                    evidence=", ".join(patched_graph.summary.parser_failure_files)[:240],
                )
            )
        contract_findings = contract_findings[: settings.max_validation_findings]
        remaining = max(0, settings.max_validation_findings - len(contract_findings))
        dependency_findings = dependency_findings[:remaining]
        related_tests = discover_related_tests(
            patched, changes, matches, maximum=settings.max_related_tests
        )
        test_gaps = find_test_gaps(matches, related_tests, maximum=settings.max_validation_findings)
        context = TestPlanContext(
            changes=tuple(changes),
            matches=tuple(matches),
            findings=tuple([*contract_findings, *dependency_findings]),
            related_tests=tuple(related_tests),
            test_gaps=tuple(test_gaps),
            patch_summary=proposal.summary,
        )
        warnings: list[str] = []
        result_provider = self.provider
        try:
            test_plan = self.provider.generate(
                context,
                max_cases=settings.max_test_plan_cases,
                max_context_bytes=settings.max_test_context_bytes,
            )
        except TestPlanProviderError as exc:
            if self.provider.name.value != "mock":
                warnings.append(
                    "Configured test-plan provider failed; deterministic recommendations were used."
                )
                fallback = MockTestPlanProvider()
                result_provider = fallback
                test_plan = fallback.generate(
                    context,
                    max_cases=settings.max_test_plan_cases,
                    max_context_bytes=settings.max_test_context_bytes,
                )
            else:
                raise DriftGuardError(
                    code="test_plan_generation_failed",
                    message="A bounded test plan could not be generated.",
                    status_code=422,
                ) from exc
        if self.provider.warning:
            warnings.append(self.provider.warning)

        all_findings = [*contract_findings, *dependency_findings]
        counts = {
            status: sum(item.status == status for item in all_findings) for status in FindingStatus
        }
        readiness = _readiness(all_findings, test_gaps)
        run = PatchValidationRun(
            validation_id=str(uuid5(NAMESPACE_URL, f"driftguard-validation:{fingerprint}")),
            patch_id=patch_id,
            analysis_id=analysis_id,
            created_at=datetime.now(UTC),
            validation_profile_version=VALIDATION_PROFILE_VERSION,
            readiness=readiness,
            source_repository_hash=scan.archive_sha256,
            request_fingerprint=fingerprint,
            passed_count=counts[FindingStatus.PASS],
            warning_count=counts[FindingStatus.WARNING],
            failed_count=counts[FindingStatus.FAIL],
            unknown_count=counts[FindingStatus.UNKNOWN],
            contract_findings=contract_findings,
            dependency_findings=dependency_findings,
            related_tests=related_tests,
            test_gaps=test_gaps,
            test_plan=test_plan,
            provider=result_provider.name,
            provider_model=result_provider.model_name,
            provider_mode=result_provider.mode,
            warnings=list(dict.fromkeys(warnings))[:20],
            modified_files=sorted(trusted.modified_sources),
            direct_impacted_files=direct_files,
            transitive_impacted_files=transitive_files,
            unrelated_modified_files=unrelated,
            static_only=True,
        )
        return self.repository.save_patch_validation(run)

    def list(self, analysis_id: str, patch_id: str) -> list[PatchValidationListItem]:
        self._require_patch(analysis_id, patch_id)
        return [
            PatchValidationListItem.model_validate(
                item.model_dump(
                    include={
                        "validation_id",
                        "patch_id",
                        "analysis_id",
                        "created_at",
                        "readiness",
                        "passed_count",
                        "warning_count",
                        "failed_count",
                        "unknown_count",
                        "provider",
                        "provider_model",
                    }
                )
            )
            for item in self.repository.list_patch_validations(analysis_id, patch_id)
        ]

    def get(self, analysis_id: str, patch_id: str, validation_id: str) -> PatchValidationRun:
        self._require_patch(analysis_id, patch_id)
        run = self.repository.get_patch_validation(analysis_id, patch_id, validation_id)
        if run is None:
            raise DriftGuardError(
                code="patch_validation_not_found",
                message="The requested patch validation does not exist.",
                status_code=404,
            )
        return run

    def _require_patch(self, analysis_id: str, patch_id: str) -> None:
        if self.repository.get_analysis(analysis_id) is None:
            raise DriftGuardError(
                code="analysis_not_found",
                message="The requested analysis does not exist.",
                status_code=404,
            )
        if self.repository.get_patch_proposal(analysis_id, patch_id) is None:
            raise DriftGuardError(
                code="patch_proposal_not_found",
                message="The requested patch proposal does not exist.",
                status_code=404,
            )

    async def _verified_source(
        self,
        analysis,
        expected_hash: str,
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
                analysis.repository_url, ref=analysis.repository_ref
            )
            filename, content = archive.filename, archive.content
        else:
            if repository_content is None:
                raise DriftGuardError(
                    code="repository_source_required",
                    message="Upload the original repository ZIP to validate this patch.",
                    status_code=422,
                )
            filename = repository_filename or analysis.repository_filename or "repository.zip"
            content = repository_content
        scan = RepositoryArchiveScanner().scan(filename, content)
        if (
            scan.archive_sha256 != expected_hash
            or scan.archive_sha256 != analysis.repository_file_sha256
        ):
            raise DriftGuardError(
                code="repository_snapshot_mismatch",
                message=(
                    "The repository snapshot differs from the source used for this "
                    "analysis and patch."
                ),
                status_code=409,
            )
        return scan


def _readiness(findings, gaps) -> ValidationReadiness:
    if any(item.status == FindingStatus.FAIL for item in findings):
        return ValidationReadiness.BLOCKED
    if any(item.status in {FindingStatus.WARNING, FindingStatus.UNKNOWN} for item in findings):
        return ValidationReadiness.NEEDS_REVIEW
    if any(gap.impact_depth == 0 for gap in gaps):
        return ValidationReadiness.NEEDS_REVIEW
    return ValidationReadiness.READY_FOR_REVIEW


def _validation_fingerprint(
    *, analysis_id: str, patch_id: str, source_hash: str, provider: str, model: str
) -> str:
    value = json.dumps(
        {
            "analysis_id": analysis_id,
            "patch_id": patch_id,
            "source_hash": source_hash,
            "validation_profile_version": VALIDATION_PROFILE_VERSION,
            "provider": provider,
            "model": model,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode()).hexdigest()
