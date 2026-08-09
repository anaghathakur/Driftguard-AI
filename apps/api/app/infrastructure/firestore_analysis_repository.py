"""Google Cloud Firestore implementation of the analysis repository port."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from apps.api.app.core.redaction import redact_secrets
from apps.api.app.domain.analysis import (
    AnalysisCreation,
    AnalysisKind,
    AnalysisRecord,
    AnalysisStatus,
    AnalysisSubmission,
    FailureRecord,
    PipelineStageRecord,
    PipelineStageStatus,
    RepositorySourceType,
    StoredMatch,
)
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.schemas.comparison import ApiChange, ComparisonResponse
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactSummary,
    RepositoryScanSummary,
)
from apps.api.app.schemas.migration import MigrationRecommendation
from apps.api.app.schemas.patch import PatchProposal
from apps.api.app.schemas.pull_request import GitHubPullRequestRecord
from apps.api.app.schemas.risk import RiskPrediction
from apps.api.app.schemas.validation import PatchValidationRun

_ANALYSES = "analyses"
_FINGERPRINTS = "analysis_fingerprints"
_STAGE_INDEX = "pipeline_stage_index"

_CHANGES = "changes"
_MATCHES = "matches"
_RISKS = "risks"
_MIGRATIONS = "migrations"
_PIPELINE = "pipeline"
_FAILURES = "failures"
_PATCHES = "patches"
_VALIDATIONS = "validations"
_PULL_REQUESTS = "pull_requests"

_MAX_BATCH_WRITES = 400
_STAGE_ID_ATTEMPTS = 5


class FirestoreAnalysisRepository(AnalysisRepository):
    """Persist DriftGuard analyses in Google Cloud Firestore."""

    def __init__(
        self,
        *,
        project_id: str | None = None,
        database_id: str = "(default)",
        client: Any | None = None,
    ) -> None:
        self.client = client or firestore.Client(
            project=project_id or None,
            database=database_id,
        )
        self._analyses = self.client.collection(_ANALYSES)
        self._fingerprints = self.client.collection(_FINGERPRINTS)
        self._stage_index = self.client.collection(_STAGE_INDEX)

    def initialize(self) -> None:
        """Firestore is schemaless, so no database bootstrap is required."""

    def create_or_get(self, submission: AnalysisSubmission) -> AnalysisCreation:
        transaction = self.client.transaction()

        @firestore.transactional
        def create_in_transaction(transaction: Any) -> AnalysisCreation:
            fingerprint_ref = self._fingerprints.document(submission.request_fingerprint)
            fingerprint_snapshot = fingerprint_ref.get(transaction=transaction)

            if fingerprint_snapshot.exists:
                fingerprint_data = fingerprint_snapshot.to_dict() or {}
                existing_id = str(fingerprint_data.get("analysis_id", ""))
                if existing_id:
                    existing_ref = self._analyses.document(existing_id)
                    existing_snapshot = existing_ref.get(transaction=transaction)
                    if existing_snapshot.exists:
                        return AnalysisCreation(
                            analysis=_analysis_record(existing_snapshot),
                            duplicate=True,
                        )

            analysis_id = str(uuid4())
            analysis_ref = self._analyses.document(analysis_id)
            analysis_data = {
                "analysis_id": analysis_id,
                "kind": submission.kind.value,
                "status": AnalysisStatus.RUNNING.value,
                "request_fingerprint": submission.request_fingerprint,
                "old_filename": submission.old_filename,
                "new_filename": submission.new_filename,
                "repository_filename": submission.repository_filename,
                "old_file_sha256": submission.old_file_sha256,
                "new_file_sha256": submission.new_file_sha256,
                "repository_file_sha256": submission.repository_file_sha256,
                "repository_source_type": (
                    submission.repository_source_type.value
                    if submission.repository_source_type
                    else None
                ),
                "repository_url": submission.repository_url,
                "repository_ref": submission.repository_ref,
                "repository_commit_sha": submission.repository_commit_sha,
                "created_at": submission.created_at,
                "updated_at": submission.created_at,
                "completed_at": None,
                "old_contract": None,
                "new_contract": None,
                "comparison_summary": None,
                "repository_summary": None,
                "impact_summary": None,
            }
            transaction.set(analysis_ref, analysis_data)
            transaction.set(
                fingerprint_ref,
                {
                    "analysis_id": analysis_id,
                    "created_at": submission.created_at,
                },
            )
            return AnalysisCreation(
                analysis=_analysis_record_from_data(analysis_data),
                duplicate=False,
            )

        return create_in_transaction(transaction)

    def start_stage(
        self,
        analysis_id: str,
        stage_name: str,
        ordinal: int,
        started_at: datetime,
    ) -> int:
        analysis_ref = self._analyses.document(analysis_id)

        for _ in range(_STAGE_ID_ATTEMPTS):
            stage_id = _new_int_id()
            stage_doc_id = str(stage_id)
            stage_ref = analysis_ref.collection(_PIPELINE).document(stage_doc_id)
            stage_index_ref = self._stage_index.document(stage_doc_id)

            batch = self.client.batch()
            batch.create(
                stage_ref,
                {
                    "stage_id": stage_id,
                    "analysis_id": analysis_id,
                    "stage_name": stage_name,
                    "ordinal": ordinal,
                    "status": PipelineStageStatus.RUNNING.value,
                    "started_at": started_at,
                    "completed_at": None,
                    "duration_ms": None,
                    "error_code": None,
                    "error_message": None,
                },
            )
            batch.create(
                stage_index_ref,
                {
                    "analysis_id": analysis_id,
                    "stage_doc_id": stage_doc_id,
                },
            )
            batch.update(analysis_ref, {"updated_at": started_at})

            try:
                batch.commit()
            except AlreadyExists:
                continue
            return stage_id

        raise RuntimeError("Could not allocate a unique Firestore pipeline stage ID.")

    def complete_stage(
        self,
        stage_id: int,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        stage_ref = self._resolve_stage_ref(stage_id)
        stage_ref.update(
            {
                "status": PipelineStageStatus.SUCCEEDED.value,
                "completed_at": completed_at,
                "duration_ms": duration_ms,
            }
        )

    def fail_analysis(
        self,
        *,
        analysis_id: str,
        stage_id: int,
        stage_name: str,
        error_code: str,
        safe_message: str,
        status_code: int,
        failed_at: datetime,
        duration_ms: int,
    ) -> None:
        safe_code = error_code[:100]
        safe_text = safe_message[:500]

        analysis_ref = self._analyses.document(analysis_id)
        stage_ref = self._resolve_stage_ref(stage_id)
        failure_id = _new_int_id()
        failure_ref = analysis_ref.collection(_FAILURES).document(str(failure_id))

        batch = self.client.batch()
        batch.update(
            stage_ref,
            {
                "status": PipelineStageStatus.FAILED.value,
                "completed_at": failed_at,
                "duration_ms": duration_ms,
                "error_code": safe_code,
                "error_message": safe_text,
            },
        )
        batch.update(
            analysis_ref,
            {
                "status": AnalysisStatus.FAILED.value,
                "updated_at": failed_at,
                "completed_at": failed_at,
            },
        )
        batch.set(
            failure_ref,
            {
                "failure_id": failure_id,
                "analysis_id": analysis_id,
                "stage_name": stage_name,
                "error_code": safe_code,
                "safe_message": safe_text,
                "status_code": status_code,
                "created_at": failed_at,
            },
        )
        batch.commit()

    def save_success(
        self,
        *,
        analysis_id: str,
        comparison: ComparisonResponse,
        repository_summary: RepositoryScanSummary | None,
        impact_summary: ImpactSummary | None,
        impacts: list[ChangeImpact],
        risk_predictions: list[RiskPrediction],
        migration_recommendations: list[MigrationRecommendation],
        stage_id: int,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        analysis_ref = self._analyses.document(analysis_id)
        writes: list[tuple[Any, dict[str, Any]]] = []

        for ordinal, change in enumerate(comparison.changes, start=1):
            change_ref = analysis_ref.collection(_CHANGES).document(change.change_id)
            change_data = change.model_dump(mode="json")
            change_data["ordinal"] = ordinal
            writes.append((change_ref, change_data))

        match_ordinal = 0
        for impact in impacts:
            for ordinal, match in enumerate(impact.matches, start=1):
                match_ordinal += 1
                match_id = f"{impact.change_id}-{ordinal:04d}"
                match_ref = analysis_ref.collection(_MATCHES).document(match_id)
                safe_evidence = redact_secrets(match.evidence[:240])[0][:240]
                writes.append(
                    (
                        match_ref,
                        {
                            "change_id": impact.change_id,
                            "ordinal": ordinal,
                            "match_ordinal": match_ordinal,
                            "file_path": match.file_path,
                            "line": match.line,
                            "column": match.column,
                            "match_kind": match.match_kind.value,
                            "confidence": match.confidence.value,
                            "evidence": safe_evidence,
                            "symbol": match.symbol,
                            "language": match.language,
                            "impact_depth": match.impact_depth,
                            "analysis_kind": match.analysis_kind.value,
                            "trace": _safe_match_trace(match.trace),
                        },
                    )
                )

        for prediction in risk_predictions:
            prediction_ref = analysis_ref.collection(_RISKS).document(prediction.change_id)
            writes.append((prediction_ref, prediction.model_dump(mode="json")))

        for recommendation in migration_recommendations:
            recommendation_ref = analysis_ref.collection(_MIGRATIONS).document(
                recommendation.recommendation_id
            )
            data = recommendation.model_dump(mode="json")
            data["analysis_id"] = analysis_id
            writes.append((recommendation_ref, data))

        self._commit_sets(writes)
        self._finalize_success(
            analysis_ref=analysis_ref,
            stage_id=stage_id,
            comparison=comparison,
            repository_summary=repository_summary,
            impact_summary=impact_summary,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )

    def list_analyses(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[AnalysisRecord]:
        query = (
            self._analyses.order_by(
                "created_at",
                direction=firestore.Query.DESCENDING,
            )
            .offset(offset)
            .limit(limit)
        )
        return [_analysis_record(snapshot) for snapshot in query.stream()]

    def get_analysis(
        self,
        analysis_id: str,
    ) -> AnalysisRecord | None:
        snapshot = self._analyses.document(analysis_id).get()
        if not snapshot.exists:
            return None
        return _analysis_record(snapshot)

    def get_changes(
        self,
        analysis_id: str,
    ) -> list[ApiChange]:
        query = self._analyses.document(analysis_id).collection(_CHANGES).order_by("ordinal")
        return [
            ApiChange.model_validate(_without(snapshot.to_dict() or {}, "ordinal"))
            for snapshot in query.stream()
        ]

    def get_matches(
        self,
        analysis_id: str,
    ) -> list[StoredMatch]:
        query = self._analyses.document(analysis_id).collection(_MATCHES).order_by("match_ordinal")

        matches: list[StoredMatch] = []
        for snapshot in query.stream():
            data = snapshot.to_dict() or {}
            matches.append(
                StoredMatch(
                    change_id=data["change_id"],
                    file_path=data["file_path"],
                    line=data["line"],
                    column=data["column"],
                    match_kind=data["match_kind"],
                    confidence=data["confidence"],
                    evidence=data["evidence"],
                    symbol=data.get("symbol"),
                    language=data.get("language"),
                    impact_depth=int(data.get("impact_depth", 0)),
                    analysis_kind=data.get("analysis_kind", "lexical"),
                    trace=tuple(data.get("trace") or []),
                )
            )
        return matches

    def get_pipeline(
        self,
        analysis_id: str,
    ) -> list[PipelineStageRecord]:
        query = self._analyses.document(analysis_id).collection(_PIPELINE).order_by("ordinal")
        return [_stage_record(snapshot) for snapshot in query.stream()]

    def get_risk_predictions(
        self,
        analysis_id: str,
    ) -> list[RiskPrediction]:
        query = self._analyses.document(analysis_id).collection(_RISKS).order_by("predicted_at")
        return [
            RiskPrediction.model_validate(snapshot.to_dict() or {}) for snapshot in query.stream()
        ]

    def get_migration_recommendations(
        self,
        analysis_id: str,
    ) -> list[MigrationRecommendation]:
        query = (
            self._analyses.document(analysis_id).collection(_MIGRATIONS).order_by("generated_at")
        )
        return [
            MigrationRecommendation.model_validate(snapshot.to_dict() or {})
            for snapshot in query.stream()
        ]

    def get_failure(
        self,
        analysis_id: str,
    ) -> FailureRecord | None:
        query = (
            self._analyses.document(analysis_id)
            .collection(_FAILURES)
            .order_by(
                "created_at",
                direction=firestore.Query.DESCENDING,
            )
            .limit(1)
        )
        snapshots = list(query.stream())
        if not snapshots:
            return None

        data = snapshots[0].to_dict() or {}
        return FailureRecord(
            failure_id=data["failure_id"],
            analysis_id=data["analysis_id"],
            stage_name=data["stage_name"],
            error_code=data["error_code"],
            safe_message=data["safe_message"],
            status_code=data["status_code"],
            created_at=_datetime(data["created_at"]),
        )

    def save_patch_proposal(self, proposal: PatchProposal) -> PatchProposal:
        collection = self._analyses.document(proposal.analysis_id).collection(_PATCHES)
        existing = self.get_patch_by_fingerprint(
            proposal.analysis_id,
            proposal.request_fingerprint,
        )
        if existing is not None:
            return existing
        collection.document(proposal.patch_id).set(proposal.model_dump(mode="python"))
        return proposal

    def get_patch_proposal(
        self,
        analysis_id: str,
        patch_id: str,
    ) -> PatchProposal | None:
        snapshot = (
            self._analyses.document(analysis_id).collection(_PATCHES).document(patch_id).get()
        )
        if not snapshot.exists:
            return None
        return PatchProposal.model_validate(snapshot.to_dict() or {})

    def get_patch_by_fingerprint(
        self,
        analysis_id: str,
        fingerprint: str,
    ) -> PatchProposal | None:
        collection = self._analyses.document(analysis_id).collection(_PATCHES)
        for snapshot in collection.stream():
            data = snapshot.to_dict() or {}
            if data.get("request_fingerprint") == fingerprint:
                return PatchProposal.model_validate(data)
        return None

    def list_patch_proposals(self, analysis_id: str) -> list[PatchProposal]:
        query = (
            self._analyses.document(analysis_id)
            .collection(_PATCHES)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
        )
        return [
            PatchProposal.model_validate(snapshot.to_dict() or {}) for snapshot in query.stream()
        ]

    def _validation_collection(self, analysis_id: str, patch_id: str):
        return (
            self._analyses.document(analysis_id)
            .collection(_PATCHES)
            .document(patch_id)
            .collection(_VALIDATIONS)
        )

    def save_patch_validation(self, validation: PatchValidationRun) -> PatchValidationRun:
        existing = self.get_patch_validation_by_fingerprint(
            validation.analysis_id,
            validation.patch_id,
            validation.request_fingerprint,
        )
        if existing is not None:
            return existing
        self._validation_collection(validation.analysis_id, validation.patch_id).document(
            validation.validation_id
        ).set(validation.model_dump(mode="python"))
        return validation

    def get_patch_validation(
        self, analysis_id: str, patch_id: str, validation_id: str
    ) -> PatchValidationRun | None:
        snapshot = self._validation_collection(analysis_id, patch_id).document(validation_id).get()
        if not snapshot.exists:
            return None
        return PatchValidationRun.model_validate(snapshot.to_dict() or {})

    def get_patch_validation_by_fingerprint(
        self, analysis_id: str, patch_id: str, fingerprint: str
    ) -> PatchValidationRun | None:
        for snapshot in self._validation_collection(analysis_id, patch_id).stream():
            data = snapshot.to_dict() or {}
            if data.get("request_fingerprint") == fingerprint:
                return PatchValidationRun.model_validate(data)
        return None

    def list_patch_validations(self, analysis_id: str, patch_id: str) -> list[PatchValidationRun]:
        query = self._validation_collection(analysis_id, patch_id).order_by(
            "created_at", direction=firestore.Query.DESCENDING
        )
        return [
            PatchValidationRun.model_validate(snapshot.to_dict() or {})
            for snapshot in query.stream()
        ]

    def save_pull_request_record(self, record: GitHubPullRequestRecord) -> GitHubPullRequestRecord:
        self._analyses.document(record.analysis_id).collection(_PULL_REQUESTS).document(
            record.pr_record_id
        ).set(record.model_dump(mode="python"))
        return record

    def get_pull_request_record(
        self, analysis_id: str, pr_record_id: str
    ) -> GitHubPullRequestRecord | None:
        snapshot = (
            self._analyses.document(analysis_id)
            .collection(_PULL_REQUESTS)
            .document(pr_record_id)
            .get()
        )
        if not snapshot.exists:
            return None
        return GitHubPullRequestRecord.model_validate(snapshot.to_dict() or {})

    def get_pull_request_by_fingerprint(
        self, analysis_id: str, fingerprint: str
    ) -> GitHubPullRequestRecord | None:
        collection = self._analyses.document(analysis_id).collection(_PULL_REQUESTS)
        for snapshot in collection.stream():
            data = snapshot.to_dict() or {}
            if data.get("request_fingerprint") == fingerprint:
                return GitHubPullRequestRecord.model_validate(data)
        return None

    def list_pull_request_records(self, analysis_id: str) -> list[GitHubPullRequestRecord]:
        query = (
            self._analyses.document(analysis_id)
            .collection(_PULL_REQUESTS)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
        )
        return [
            GitHubPullRequestRecord.model_validate(snapshot.to_dict() or {})
            for snapshot in query.stream()
        ]

    def delete(
        self,
        analysis_id: str,
    ) -> bool:
        analysis_ref = self._analyses.document(analysis_id)
        snapshot = analysis_ref.get()
        if not snapshot.exists:
            return False

        data = snapshot.to_dict() or {}
        fingerprint = str(data.get("request_fingerprint", ""))

        pipeline_snapshots = list(analysis_ref.collection(_PIPELINE).stream())
        stage_ids = [
            str((stage.to_dict() or {}).get("stage_id", "")) for stage in pipeline_snapshots
        ]

        self.client.recursive_delete(analysis_ref)

        cleanup = self.client.batch()
        operations = 0

        if fingerprint:
            cleanup.delete(self._fingerprints.document(fingerprint))
            operations += 1

        for stage_id in stage_ids:
            if not stage_id:
                continue
            cleanup.delete(self._stage_index.document(stage_id))
            operations += 1

        if operations:
            cleanup.commit()

        return True

    def _resolve_stage_ref(self, stage_id: int) -> Any:
        index_snapshot = self._stage_index.document(str(stage_id)).get()
        if not index_snapshot.exists:
            raise RuntimeError("The Firestore pipeline stage does not exist.")

        data = index_snapshot.to_dict() or {}
        analysis_id = str(data.get("analysis_id", ""))
        stage_doc_id = str(data.get("stage_doc_id", ""))

        if not analysis_id or not stage_doc_id:
            raise RuntimeError("The Firestore pipeline stage index is invalid.")

        return self._analyses.document(analysis_id).collection(_PIPELINE).document(stage_doc_id)

    def _commit_sets(
        self,
        writes: list[tuple[Any, dict[str, Any]]],
    ) -> None:
        for start in range(0, len(writes), _MAX_BATCH_WRITES):
            batch = self.client.batch()
            for reference, data in writes[start : start + _MAX_BATCH_WRITES]:
                batch.set(reference, data)
            batch.commit()

    def _finalize_success(
        self,
        *,
        analysis_ref: Any,
        stage_id: int,
        comparison: ComparisonResponse,
        repository_summary: RepositoryScanSummary | None,
        impact_summary: ImpactSummary | None,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        transaction = self.client.transaction()

        @firestore.transactional
        def finalize(transaction: Any) -> None:
            analysis_snapshot = analysis_ref.get(transaction=transaction)
            if not analysis_snapshot.exists:
                raise RuntimeError("The Firestore analysis does not exist.")

            analysis_data = analysis_snapshot.to_dict() or {}
            if analysis_data.get("status") != AnalysisStatus.RUNNING.value:
                raise RuntimeError("The Firestore analysis is not running.")

            index_ref = self._stage_index.document(str(stage_id))
            index_snapshot = index_ref.get(transaction=transaction)
            if not index_snapshot.exists:
                raise RuntimeError("The Firestore pipeline stage does not exist.")

            index_data = index_snapshot.to_dict() or {}
            stage_doc_id = str(index_data.get("stage_doc_id", ""))
            if not stage_doc_id:
                raise RuntimeError("The Firestore pipeline stage index is invalid.")

            stage_ref = analysis_ref.collection(_PIPELINE).document(stage_doc_id)
            stage_snapshot = stage_ref.get(transaction=transaction)
            if not stage_snapshot.exists:
                raise RuntimeError("The Firestore pipeline stage does not exist.")

            transaction.update(
                stage_ref,
                {
                    "status": PipelineStageStatus.SUCCEEDED.value,
                    "completed_at": completed_at,
                    "duration_ms": duration_ms,
                },
            )
            transaction.update(
                analysis_ref,
                {
                    "status": AnalysisStatus.SUCCEEDED.value,
                    "updated_at": completed_at,
                    "completed_at": completed_at,
                    "old_contract": comparison.old_contract.model_dump(mode="json"),
                    "new_contract": comparison.new_contract.model_dump(mode="json"),
                    "comparison_summary": comparison.summary.model_dump(mode="json"),
                    "repository_summary": _model_data(repository_summary),
                    "impact_summary": _model_data(impact_summary),
                },
            )

        finalize(transaction)


def _analysis_record(snapshot: Any) -> AnalysisRecord:
    data = snapshot.to_dict() or {}
    return _analysis_record_from_data(data)


def _analysis_record_from_data(data: dict[str, Any]) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=str(data["analysis_id"]),
        kind=AnalysisKind(data["kind"]),
        status=AnalysisStatus(data["status"]),
        request_fingerprint=str(data["request_fingerprint"]),
        old_filename=str(data["old_filename"]),
        new_filename=str(data["new_filename"]),
        repository_filename=data.get("repository_filename"),
        old_file_sha256=str(data["old_file_sha256"]),
        new_file_sha256=str(data["new_file_sha256"]),
        repository_file_sha256=data.get("repository_file_sha256"),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        completed_at=_optional_datetime(data.get("completed_at")),
        old_contract=data.get("old_contract"),
        new_contract=data.get("new_contract"),
        comparison_summary=data.get("comparison_summary"),
        repository_summary=data.get("repository_summary"),
        impact_summary=data.get("impact_summary"),
        repository_source_type=(
            RepositorySourceType(data["repository_source_type"])
            if data.get("repository_source_type")
            else None
        ),
        repository_url=data.get("repository_url"),
        repository_ref=data.get("repository_ref"),
        repository_commit_sha=data.get("repository_commit_sha"),
    )


def _stage_record(snapshot: Any) -> PipelineStageRecord:
    data = snapshot.to_dict() or {}
    return PipelineStageRecord(
        stage_id=int(data["stage_id"]),
        analysis_id=str(data["analysis_id"]),
        stage_name=str(data["stage_name"]),
        ordinal=int(data["ordinal"]),
        status=PipelineStageStatus(data["status"]),
        started_at=_datetime(data["started_at"]),
        completed_at=_optional_datetime(data.get("completed_at")),
        duration_ms=data.get("duration_ms"),
        error_code=data.get("error_code"),
        error_message=data.get("error_message"),
    )


def _new_int_id() -> int:
    return uuid4().int & ((1 << 63) - 1)


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("Expected a datetime-compatible Firestore value.")


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)


def _model_data(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump(mode="json")


def _without(
    data: dict[str, Any],
    *keys: str,
) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in keys}


def _safe_match_trace(trace: list[Any]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for step in trace[:10]:
        data = step.model_dump(mode="json")
        data["evidence"] = redact_secrets(str(data.get("evidence", ""))[:240])[0][:240]
        safe.append(data)
    return safe
