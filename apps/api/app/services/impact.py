"""Orchestrate contract comparison, repository scanning, and impact matching."""

from __future__ import annotations

from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.openapi.parser import parse_openapi_document
from apps.api.app.repository.matcher import ApiImpactMatcher
from apps.api.app.repository.scanner import RepositoryArchiveScanner
from apps.api.app.schemas.impact import (
    ImpactAnalysisResponse,
    ImpactSummary,
    RepositoryScanSummary,
)
from apps.api.app.services.comparison import SpecificationComparisonService


class ImpactAnalysisService:
    def analyze(
        self,
        *,
        old_filename: str,
        old_content: bytes,
        new_filename: str,
        new_content: bytes,
        repository_filename: str,
        repository_content: bytes,
    ) -> ImpactAnalysisResponse:
        old_contract = normalize_openapi(parse_openapi_document(old_filename, old_content))
        new_contract = normalize_openapi(parse_openapi_document(new_filename, new_content))
        comparison = SpecificationComparisonService().compare_contracts(
            old_contract=old_contract,
            old_content=old_content,
            new_contract=new_contract,
            new_content=new_content,
        )
        repository = RepositoryArchiveScanner().scan(
            repository_filename, repository_content
        )
        impacts = ApiImpactMatcher().match(
            comparison.changes, repository, old_contract, new_contract
        )
        impacted_paths = {
            match.file_path for impact in impacts for match in impact.matches
        }
        total_matches = sum(len(impact.matches) for impact in impacts)
        return ImpactAnalysisResponse(
            comparison=comparison,
            repository=RepositoryScanSummary(
                archive_sha256=repository.archive_sha256,
                archive_entries=repository.archive_entries,
                scanned_files=len(repository.files),
                scanned_bytes=repository.scanned_bytes,
                skipped_files=repository.skipped_files,
                skipped_reasons=repository.skipped_reasons,
            ),
            impact_summary=ImpactSummary(
                total_changes=len(comparison.changes),
                impacted_changes=sum(bool(impact.matches) for impact in impacts),
                impacted_files=len(impacted_paths),
                total_matches=total_matches,
            ),
            impacts=impacts,
        )
