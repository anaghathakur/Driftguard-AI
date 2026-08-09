"""Structured, durable execution pipeline for comparison and impact analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import PurePosixPath
from time import perf_counter
from typing import TypeVar

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.analysis import (
    AnalysisKind,
    AnalysisRecord,
    AnalysisStatus,
    AnalysisSubmission,
)
from apps.api.app.migration.provider import (
    MockMigrationRecommendationProvider,
)
from apps.api.app.migration.service import (
    MigrationRecommendationService,
)
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.openapi.parser import parse_openapi_document
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.repository.matcher import ApiImpactMatcher
from apps.api.app.repository.scanner import RepositoryArchiveScanner
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.schemas.analysis import (
    AnalysisDetail,
    AnalysisFailureResponse,
    AnalysisListItem,
    FileHashes,
    PersistedMatchResponse,
    PipelineStageResponse,
)
from apps.api.app.schemas.comparison import (
    ApiChange,
    ComparisonResponse,
    ComparisonSummary,
    ContractMetadata,
)
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactAnalysisResponse,
    ImpactMatch,
    ImpactSummary,
    RepositoryScanSummary,
)
from apps.api.app.schemas.migration import MigrationRecommendation
from apps.api.app.schemas.risk import RiskPrediction
from apps.api.app.services.comparison import SpecificationComparisonService

T = TypeVar("T")
ANALYSIS_PIPELINE_VERSION = "5.0.0"


class AnalysisPipelineService:
    def __init__(
    self,
    repository: AnalysisRepository,
    risk_classifier: RiskClassifier,
    migration_service: MigrationRecommendationService | None = None,
    ) -> None:
        self.repository = repository
        self.risk_classifier = risk_classifier

        self.migration_service = (
            migration_service
            or MigrationRecommendationService(
                MockMigrationRecommendationProvider()
            )
        )   

    def compare(
        self,
        *,
        old_filename: str,
        old_content: bytes,
        new_filename: str,
        new_content: bytes,
    ) -> ComparisonResponse:
        creation = self.repository.create_or_get(
            _submission(
                kind=AnalysisKind.COMPARISON,
                old_filename=old_filename,
                old_content=old_content,
                new_filename=new_filename,
                new_content=new_content,
            )
        )
        if creation.duplicate:
            return self._duplicate_comparison(creation.analysis)

        pipeline = _PipelineExecution(self.repository, creation.analysis.analysis_id)
        old_contract, new_contract = pipeline.run(
            "validate_and_normalize_specifications",
            lambda: (
                normalize_openapi(parse_openapi_document(old_filename, old_content)),
                normalize_openapi(parse_openapi_document(new_filename, new_content)),
            ),
        )
        comparison = pipeline.run(
            "compare_contracts",
            lambda: SpecificationComparisonService().compare_contracts(
                old_contract=old_contract,
                old_content=old_content,
                new_contract=new_contract,
                new_content=new_content,
            ),
        ).model_copy(
            update={"analysis_id": creation.analysis.analysis_id, "duplicate": False}
        )
        risk_predictions = pipeline.run(
            "classify_risk",
            lambda: self.risk_classifier.predict_all(
                comparison.changes,
                [],
            ),
        )

        migration_recommendations = pipeline.run(
            "generate_migration_recommendations",
            lambda: self.migration_service.generate_all(
                analysis_id=creation.analysis.analysis_id,
                changes=comparison.changes,
                impacts=[],
                risks=risk_predictions,
            ),
        )

        pipeline.persist(
            comparison=comparison,
            risk_predictions=risk_predictions,
            migration_recommendations=migration_recommendations,
        )

        return comparison.model_copy(
            update={
                "analysis_id": creation.analysis.analysis_id,
                "duplicate": creation.duplicate,
            }
        )

    def analyze_impact(
        self,
        *,
        old_filename: str,
        old_content: bytes,
        new_filename: str,
        new_content: bytes,
        repository_filename: str,
        repository_content: bytes,
    ) -> ImpactAnalysisResponse:
        creation = self.repository.create_or_get(
            _submission(
                kind=AnalysisKind.IMPACT,
                old_filename=old_filename,
                old_content=old_content,
                new_filename=new_filename,
                new_content=new_content,
                repository_filename=repository_filename,
                repository_content=repository_content,
            )
        )
        if creation.duplicate:
            return self._duplicate_impact(creation.analysis)

        pipeline = _PipelineExecution(self.repository, creation.analysis.analysis_id)
        old_contract, new_contract = pipeline.run(
            "validate_and_normalize_specifications",
            lambda: (
                normalize_openapi(parse_openapi_document(old_filename, old_content)),
                normalize_openapi(parse_openapi_document(new_filename, new_content)),
            ),
        )
        comparison = pipeline.run(
            "compare_contracts",
            lambda: SpecificationComparisonService().compare_contracts(
                old_contract=old_contract,
                old_content=old_content,
                new_contract=new_contract,
                new_content=new_content,
            ),
        ).model_copy(
            update={"analysis_id": creation.analysis.analysis_id, "duplicate": False}
        )
        scan = pipeline.run(
            "scan_repository",
            lambda: RepositoryArchiveScanner().scan(
                repository_filename, repository_content
            ),
        )
        impact_result = pipeline.run(
            "match_api_usage",
            lambda: ApiImpactMatcher().analyze(
                comparison.changes, scan, old_contract, new_contract
            ),
        )
        impacts = impact_result.impacts
        repository_summary = RepositoryScanSummary(
            archive_sha256=scan.archive_sha256,
            archive_entries=scan.archive_entries,
            scanned_files=len(scan.files),
            scanned_bytes=scan.scanned_bytes,
            skipped_files=scan.skipped_files,
            skipped_reasons=scan.skipped_reasons,
            code_analysis=impact_result.code_analysis,
        )
        impacted_paths = {
            match.file_path for impact in impacts for match in impact.matches
        }
        impact_summary = ImpactSummary(
            total_changes=len(comparison.changes),
            impacted_changes=sum(bool(impact.matches) for impact in impacts),
            impacted_files=len(impacted_paths),
            total_matches=sum(len(impact.matches) for impact in impacts),
        )
        risk_predictions = pipeline.run(
            "classify_risk",
            lambda: self.risk_classifier.predict_all(comparison.changes, impacts),
        )

        migration_recommendations = pipeline.run(
            "generate_migration_recommendations",
            lambda: self.migration_service.generate_all(
                analysis_id=creation.analysis.analysis_id,
                changes=comparison.changes,
                impacts=impacts,
                risks=risk_predictions,
            ),
        )

        pipeline.persist(
            comparison=comparison,
            repository_summary=repository_summary,
            impact_summary=impact_summary,
            impacts=impacts,
            risk_predictions=risk_predictions,
            migration_recommendations=migration_recommendations,
        )
        return ImpactAnalysisResponse(
        analysis_id=creation.analysis.analysis_id,
        duplicate=creation.duplicate,
        comparison=comparison,
        repository=repository_summary,
        impact_summary=impact_summary,
        impacts=impacts,
    )

    def list_analyses(self, *, limit: int, offset: int) -> list[AnalysisListItem]:
        return [
            self._list_item(record)
            for record in self.repository.list_analyses(limit=limit, offset=offset)
        ]

    def get_analysis(self, analysis_id: str) -> AnalysisDetail:
        return self._detail(self._require_analysis(analysis_id))

    def get_changes(self, analysis_id: str) -> list[ApiChange]:
        self._require_analysis(analysis_id)
        return self.repository.get_changes(analysis_id)

    def get_matches(self, analysis_id: str) -> list[PersistedMatchResponse]:
        self._require_analysis(analysis_id)
        return [
            PersistedMatchResponse.model_validate(asdict(match))
            for match in self.repository.get_matches(analysis_id)
        ]

    def get_pipeline(self, analysis_id: str) -> list[PipelineStageResponse]:
        self._require_analysis(analysis_id)
        return [
            PipelineStageResponse(
                stage_name=stage.stage_name,
                ordinal=stage.ordinal,
                status=stage.status,
                started_at=stage.started_at,
                completed_at=stage.completed_at,
                duration_ms=stage.duration_ms,
                error_code=stage.error_code,
                error_message=stage.error_message,
            )
            for stage in self.repository.get_pipeline(analysis_id)
        ]

    def get_risk_predictions(self, analysis_id: str) -> list[RiskPrediction]:
        self._require_analysis(analysis_id)
        return self.repository.get_risk_predictions(analysis_id)

    def get_risk_prediction(self, analysis_id: str, change_id: str) -> RiskPrediction:
        predictions = self.get_risk_predictions(analysis_id)
        for prediction in predictions:
            if prediction.change_id == change_id:
                return prediction
        raise DriftGuardError(
            code="risk_prediction_not_found",
            message="The requested risk prediction does not exist.",
            status_code=404,
        )

    def get_migration_recommendations(
        self,
        analysis_id: str,
    ) -> list[MigrationRecommendation]:
        self._require_analysis(analysis_id)

        return self.repository.get_migration_recommendations(
            analysis_id
        )


    def get_migration_recommendation(
        self,
        analysis_id: str,
        change_id: str,
    ) -> MigrationRecommendation:
        recommendations = self.get_migration_recommendations(
            analysis_id
        )

        for recommendation in recommendations:
            if recommendation.change_id == change_id:
                return recommendation

        raise DriftGuardError(
            code="migration_recommendation_not_found",
            message=(
                "The requested migration recommendation "
                "does not exist."
            ),
            status_code=404,
        )

    def delete(self, analysis_id: str) -> None:
        if not self.repository.delete(analysis_id):
            _not_found()

    def _duplicate_comparison(self, record: AnalysisRecord) -> ComparisonResponse:
        self._raise_unless_succeeded(record)
        return self._stored_comparison(record, duplicate=True)

    def _duplicate_impact(self, record: AnalysisRecord) -> ImpactAnalysisResponse:
        self._raise_unless_succeeded(record)
        comparison = self._stored_comparison(record, duplicate=True)
        repository_summary = RepositoryScanSummary.model_validate(record.repository_summary)
        impact_summary = ImpactSummary.model_validate(record.impact_summary)
        matches_by_change: dict[str, list[ImpactMatch]] = {}
        for match in self.get_matches(record.analysis_id):
            matches_by_change.setdefault(match.change_id, []).append(
                ImpactMatch.model_validate(match.model_dump(exclude={"change_id"}))
            )
        impacts = [
            ChangeImpact(
                change_id=change.change_id,
                path=change.path,
                method=change.method,
                matches=matches_by_change.get(change.change_id, []),
            )
            for change in comparison.changes
        ]
        return ImpactAnalysisResponse(
            comparison=comparison,
            repository=repository_summary,
            impact_summary=impact_summary,
            impacts=impacts,
            analysis_id=record.analysis_id,
            duplicate=True,
        )

    def _stored_comparison(
        self, record: AnalysisRecord, *, duplicate: bool
    ) -> ComparisonResponse:
        return ComparisonResponse(
            old_contract=ContractMetadata.model_validate(record.old_contract),
            new_contract=ContractMetadata.model_validate(record.new_contract),
            summary=ComparisonSummary.model_validate(record.comparison_summary),
            changes=self.repository.get_changes(record.analysis_id),
            analysis_id=record.analysis_id,
            duplicate=duplicate,
        )

    def _raise_unless_succeeded(self, record: AnalysisRecord) -> None:
        if record.status == AnalysisStatus.SUCCEEDED:
            return
        if record.status == AnalysisStatus.FAILED:
            failure = self.repository.get_failure(record.analysis_id)
            if failure is not None:
                raise DriftGuardError(
                    code=failure.error_code,
                    message=failure.safe_message,
                    status_code=failure.status_code,
                )
        raise DriftGuardError(
            code="analysis_in_progress",
            message="An identical analysis is already in progress.",
            status_code=409,
        )

    def _require_analysis(self, analysis_id: str) -> AnalysisRecord:
        record = self.repository.get_analysis(analysis_id)
        if record is None:
            _not_found()
        return record

    def _list_item(self, record: AnalysisRecord) -> AnalysisListItem:
        failure = self._failure_response(record.analysis_id)
        return AnalysisListItem(
            analysis_id=record.analysis_id,
            kind=record.kind,
            status=record.status,
            created_at=record.created_at,
            completed_at=record.completed_at,
            total_changes=int((record.comparison_summary or {}).get("total_changes", 0)),
            total_matches=int((record.impact_summary or {}).get("total_matches", 0)),
            failure=failure,
        )

    def _detail(self, record: AnalysisRecord) -> AnalysisDetail:
        return AnalysisDetail(
            analysis_id=record.analysis_id,
            kind=record.kind,
            status=record.status,
            request_fingerprint=record.request_fingerprint,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
            old_filename=record.old_filename,
            new_filename=record.new_filename,
            repository_filename=record.repository_filename,
            file_hashes=FileHashes(
                old_spec=record.old_file_sha256,
                new_spec=record.new_file_sha256,
                repository=record.repository_file_sha256,
            ),
            old_contract=record.old_contract,
            new_contract=record.new_contract,
            comparison_summary=record.comparison_summary,
            repository_summary=record.repository_summary,
            impact_summary=record.impact_summary,
            failure=self._failure_response(record.analysis_id),
        )

    def _failure_response(self, analysis_id: str) -> AnalysisFailureResponse | None:
        failure = self.repository.get_failure(analysis_id)
        if failure is None:
            return None
        return AnalysisFailureResponse(
            stage_name=failure.stage_name,
            error_code=failure.error_code,
            message=failure.safe_message,
            status_code=failure.status_code,
            created_at=failure.created_at,
        )


class _PipelineExecution:
    def __init__(self, repository: AnalysisRepository, analysis_id: str) -> None:
        self.repository = repository
        self.analysis_id = analysis_id
        self.ordinal = 0

    def run(self, stage_name: str, action: Callable[[], T]) -> T:
        stage_id, started_at, started_clock = self._start(stage_name)
        try:
            result = action()
        except Exception as exc:
            self._fail(stage_id, stage_name, started_at, started_clock, exc)
        completed_at = _utc_now()
        self.repository.complete_stage(
            stage_id, completed_at, _duration_ms(started_clock)
        )
        return result

    def persist(
        self,
        *,
        comparison: ComparisonResponse,
        repository_summary: RepositoryScanSummary | None = None,
        impact_summary: ImpactSummary | None = None,
        impacts: list[ChangeImpact] | None = None,
        risk_predictions: list[RiskPrediction] | None = None,
        migration_recommendations: (
            list[MigrationRecommendation] | None
        ) = None,
    ) -> None:
        stage_name = "persist_results"
        stage_id, started_at, started_clock = self._start(stage_name)
        try:
            self.repository.save_success(
                analysis_id=self.analysis_id,
                comparison=comparison,
                repository_summary=repository_summary,
                impact_summary=impact_summary,
                impacts=impacts or [],
                risk_predictions=risk_predictions or [],
                migration_recommendations=(
                    migration_recommendations or []
                ),
                stage_id=stage_id,
                completed_at=_utc_now(),
                duration_ms=_duration_ms(started_clock),
            )
        except Exception as exc:
            self._fail(stage_id, stage_name, started_at, started_clock, exc)

    def _start(self, stage_name: str) -> tuple[int, datetime, float]:
        self.ordinal += 1
        started_at = _utc_now()
        started_clock = perf_counter()
        stage_id = self.repository.start_stage(
            self.analysis_id, stage_name, self.ordinal, started_at
        )
        return stage_id, started_at, started_clock

    def _fail(
        self,
        stage_id: int,
        stage_name: str,
        _started_at: datetime,
        started_clock: float,
        exc: Exception,
    ) -> None:
        error = _safe_error(exc)
        self.repository.fail_analysis(
            analysis_id=self.analysis_id,
            stage_id=stage_id,
            stage_name=stage_name,
            error_code=error.code,
            safe_message=error.message,
            status_code=error.status_code,
            failed_at=_utc_now(),
            duration_ms=_duration_ms(started_clock),
        )
        raise error from exc


def _submission(
    *,
    kind: AnalysisKind,
    old_filename: str,
    old_content: bytes,
    new_filename: str,
    new_content: bytes,
    repository_filename: str | None = None,
    repository_content: bytes | None = None,
) -> AnalysisSubmission:
    old_hash = hashlib.sha256(old_content).hexdigest()
    new_hash = hashlib.sha256(new_content).hexdigest()
    repository_hash = (
        hashlib.sha256(repository_content).hexdigest()
        if repository_content is not None
        else None
    )
    fingerprint_source = json.dumps(
        {
            "pipeline_version": ANALYSIS_PIPELINE_VERSION,
            "kind": kind.value,
            "old": old_hash,
            "new": new_hash,
            "repository": repository_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return AnalysisSubmission(
        kind=kind,
        request_fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
        old_filename=_safe_filename(old_filename),
        new_filename=_safe_filename(new_filename),
        repository_filename=(
            _safe_filename(repository_filename) if repository_filename is not None else None
        ),
        old_file_sha256=old_hash,
        new_file_sha256=new_hash,
        repository_file_sha256=repository_hash,
        created_at=_utc_now(),
    )


def _safe_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return (PurePosixPath(normalized).name or "unnamed")[:255]


def _safe_error(exc: Exception) -> DriftGuardError:
    if isinstance(exc, DriftGuardError):
        return exc
    return DriftGuardError(
        code="analysis_execution_failed",
        message="The analysis could not be completed safely.",
        status_code=500,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _duration_ms(started_clock: float) -> int:
    return max(0, int((perf_counter() - started_clock) * 1000))


def _not_found() -> None:
    raise DriftGuardError(
        code="analysis_not_found",
        message="The requested analysis does not exist.",
        status_code=404,
    )
