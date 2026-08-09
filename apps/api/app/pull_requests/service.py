"""Safety-gated, idempotent GitHub pull-request orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.redaction import redact_secrets
from apps.api.app.domain.analysis import RepositorySourceType
from apps.api.app.patches.validator import validate_patch
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.pull_requests.provider import (
    GitHubRepositoryMetadata,
    GitHubWriteProvider,
)
from apps.api.app.repository.github_source import GitHubRepositorySource
from apps.api.app.repository.scanner import RepositoryArchiveScanner
from apps.api.app.schemas.analysis import PersistedMatchResponse
from apps.api.app.schemas.patch import GeneratedPatchContent, PatchStatus
from apps.api.app.schemas.pull_request import (
    GitHubPullRequestRecord,
    PullRequestListItem,
    PullRequestPreview,
    PullRequestStatus,
)
from apps.api.app.schemas.validation import ValidationReadiness

PULL_REQUEST_PROFILE_VERSION = "1.0.0"
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


class PullRequestWorkflowService:
    def __init__(
        self,
        repository: AnalysisRepository,
        provider: GitHubWriteProvider,
        github_source: GitHubRepositorySource,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.github_source = github_source

    async def preview(
        self, analysis_id: str, patch_id: str, validation_id: str
    ) -> PullRequestPreview:
        analysis, patch, validation = self._eligible(analysis_id, patch_id, validation_id)
        metadata = await self.provider.prepare_repository(
            analysis.repository_url or "",
            analysis.repository_ref,
            analysis.repository_commit_sha,
        )
        self._verify_base_commit(analysis.repository_commit_sha, metadata)
        return PullRequestPreview(
            repository_owner=metadata.owner,
            repository_name=metadata.repository,
            base_ref=metadata.base_ref,
            base_commit_sha=metadata.base_commit_sha,
            branch_name=_branch_name(analysis_id, patch_id),
            files_changed=patch.files_changed,
            edit_count=patch.edit_count,
            validation_readiness=validation.readiness,
            tests_executed=False,
        )

    async def create(
        self, analysis_id: str, patch_id: str, validation_id: str
    ) -> GitHubPullRequestRecord:
        analysis, patch, validation = self._eligible(analysis_id, patch_id, validation_id)
        metadata = await self.provider.prepare_repository(
            analysis.repository_url or "",
            analysis.repository_ref,
            analysis.repository_commit_sha,
        )
        self._verify_base_commit(analysis.repository_commit_sha, metadata)

        archive = await self.github_source.fetch(
            analysis.repository_url or "", ref=analysis.repository_ref
        )
        scan = RepositoryArchiveScanner().scan(archive.filename, archive.content)
        expected_hash = analysis.repository_file_sha256
        if (
            scan.archive_sha256 != expected_hash
            or scan.archive_sha256 != patch.source_repository_hash
            or scan.archive_sha256 != validation.source_repository_hash
        ):
            raise DriftGuardError(
                code="repository_snapshot_mismatch",
                message=(
                    "The GitHub repository changed after this patch was analyzed and "
                    "validated. Run a new DriftGuard analysis before creating a pull request."
                ),
                status_code=409,
            )
        if archive.commit_sha != metadata.base_commit_sha:
            raise DriftGuardError(
                code="github_base_commit_mismatch",
                message="The GitHub base commit changed after validation.",
                status_code=409,
            )

        matches = [
            PersistedMatchResponse.model_validate(asdict(item))
            for item in self.repository.get_matches(analysis_id)
        ]
        allowed = {item.file_path for item in matches if item.impact_depth == 0} or {
            item.file_path for item in matches
        }
        generated = GeneratedPatchContent(
            summary=patch.summary,
            files=patch.files,
            warnings=patch.warnings,
        )
        trusted = validate_patch(generated, scan, allowed)
        expected_paths = sorted(item.file_path for item in patch.files)
        actual_paths = sorted(trusted.modified_sources)
        if actual_paths != expected_paths:
            raise DriftGuardError(
                code="pull_request_scope_mismatch",
                message="The reproduced patch changed files outside its validated scope.",
                status_code=409,
            )
        if trusted.unified_diff != patch.unified_diff:
            raise DriftGuardError(
                code="validated_patch_mismatch",
                message="The exact validated patch could not be reproduced.",
                status_code=409,
            )
        total_bytes = sum(len(value.encode()) for value in trusted.modified_sources.values())
        if total_bytes > settings.max_pull_request_modified_bytes:
            raise DriftGuardError(
                code="pull_request_limit_exceeded",
                message="The validated patch exceeds the pull-request content limit.",
                status_code=413,
            )

        branch = _branch_name(analysis_id, patch_id)
        changes = self.repository.get_changes(analysis_id)
        title = _pull_request_title(changes)
        commit_message = _commit_message(changes)
        body = _pull_request_body(
            changes=changes,
            matches=matches,
            patch=patch,
            validation=validation,
            maximum=settings.max_pull_request_body_bytes,
        )
        fingerprint = _fingerprint(
            analysis_id=analysis_id,
            patch_id=patch_id,
            validation_id=validation_id,
            source_hash=scan.archive_sha256,
            base_commit_sha=metadata.base_commit_sha,
        )
        record = self.repository.get_pull_request_by_fingerprint(analysis_id, fingerprint)
        if record is not None and record.status == PullRequestStatus.CREATED:
            return record
        now = datetime.now(UTC)
        if record is None:
            record = GitHubPullRequestRecord(
                pr_record_id=str(uuid5(NAMESPACE_URL, f"driftguard-pull-request:{fingerprint}")),
                analysis_id=analysis_id,
                patch_id=patch_id,
                validation_id=validation_id,
                repository_owner=metadata.owner,
                repository_name=metadata.repository,
                base_ref=metadata.base_ref,
                base_commit_sha=metadata.base_commit_sha,
                branch_name=branch,
                status=PullRequestStatus.PREPARING,
                created_at=now,
                updated_at=now,
                provider=self.provider.name,
                request_fingerprint=fingerprint,
                pull_request_profile_version=PULL_REQUEST_PROFILE_VERSION,
                validation_readiness=validation.readiness,
                files_changed=patch.files_changed,
                edit_count=patch.edit_count,
                modified_file_sha256={
                    path: hashlib.sha256(content.encode()).hexdigest()
                    for path, content in sorted(trusted.modified_sources.items())
                },
            )
            record = self.repository.save_pull_request_record(record)
        else:
            record = record.model_copy(
                update={
                    "status": PullRequestStatus.PREPARING,
                    "failure_code": None,
                    "failure_message": None,
                    "updated_at": now,
                }
            )
            record = self.repository.save_pull_request_record(record)

        try:
            branch_state = await self.provider.get_branch(metadata, branch)
            allowed_states = {metadata.base_commit_sha}
            if record.commit_sha:
                allowed_states.add(record.commit_sha)
            if branch_state is None:
                branch_state = await self.provider.create_branch(
                    metadata, branch, metadata.base_commit_sha
                )
            elif branch_state.commit_sha not in allowed_states:
                raise DriftGuardError(
                    code="github_branch_conflict",
                    message=("The deterministic DriftGuard branch exists in an unexpected state."),
                    status_code=409,
                )

            commit_sha = record.commit_sha
            if commit_sha is None:
                commit_sha = await self.provider.create_commit(
                    metadata,
                    base_sha=metadata.base_commit_sha,
                    message=commit_message,
                    files=trusted.modified_sources,
                )
                record = self.repository.save_pull_request_record(
                    record.model_copy(
                        update={"commit_sha": commit_sha, "updated_at": datetime.now(UTC)}
                    )
                )
            if branch_state.commit_sha == metadata.base_commit_sha:
                branch_state = await self.provider.update_branch(metadata, branch, commit_sha)
            if branch_state.commit_sha != commit_sha:
                raise DriftGuardError(
                    code="github_branch_conflict",
                    message=("The deterministic DriftGuard branch exists in an unexpected state."),
                    status_code=409,
                )

            result = await self.provider.find_pull_request(metadata, branch)
            if result is None:
                result = await self.provider.create_pull_request(
                    metadata, branch=branch, title=title, body=body
                )
            _verify_pull_request_result(result, metadata, commit_sha)
            return self.repository.save_pull_request_record(
                record.model_copy(
                    update={
                        "status": PullRequestStatus.CREATED,
                        "pull_request_number": result.number,
                        "pull_request_url": result.url,
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
        except DriftGuardError as exc:
            self.repository.save_pull_request_record(
                record.model_copy(
                    update={
                        "status": PullRequestStatus.FAILED,
                        "failure_code": exc.code,
                        "failure_message": exc.message,
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
            raise
        except Exception as exc:
            error = DriftGuardError(
                code="github_write_failed",
                message="GitHub could not complete the pull-request workflow safely.",
                status_code=502,
            )
            self.repository.save_pull_request_record(
                record.model_copy(
                    update={
                        "status": PullRequestStatus.FAILED,
                        "failure_code": error.code,
                        "failure_message": error.message,
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
            raise error from exc

    def list(self, analysis_id: str) -> list[PullRequestListItem]:
        self._require_analysis(analysis_id)
        return [
            PullRequestListItem.model_validate(
                item.model_dump(
                    include={
                        "pr_record_id",
                        "analysis_id",
                        "patch_id",
                        "validation_id",
                        "repository_owner",
                        "repository_name",
                        "branch_name",
                        "pull_request_number",
                        "pull_request_url",
                        "status",
                        "created_at",
                        "validation_readiness",
                    }
                )
            )
            for item in self.repository.list_pull_request_records(analysis_id)
        ]

    def get(self, analysis_id: str, pr_record_id: str) -> GitHubPullRequestRecord:
        self._require_analysis(analysis_id)
        record = self.repository.get_pull_request_record(analysis_id, pr_record_id)
        if record is None:
            raise DriftGuardError(
                code="pull_request_record_not_found",
                message="The requested pull-request record does not exist.",
                status_code=404,
            )
        return record

    def _eligible(self, analysis_id: str, patch_id: str, validation_id: str):
        analysis = self._require_analysis(analysis_id)
        if analysis.repository_source_type != RepositorySourceType.GITHUB:
            raise DriftGuardError(
                code="github_source_required",
                message="Pull requests require a GitHub-backed analysis.",
                status_code=409,
            )
        if not analysis.repository_url or not analysis.repository_commit_sha:
            raise DriftGuardError(
                code="github_source_identity_required",
                message=(
                    "This historical analysis lacks immutable GitHub source identity. "
                    "Run a new GitHub analysis before creating a pull request."
                ),
                status_code=409,
            )
        patch = self.repository.get_patch_proposal(analysis_id, patch_id)
        if patch is None:
            raise DriftGuardError(
                code="patch_proposal_not_found",
                message="The requested patch proposal does not exist.",
                status_code=404,
            )
        if patch.status != PatchStatus.VALIDATED:
            raise DriftGuardError(
                code="patch_not_validated",
                message="Only a validated patch proposal can create a pull request.",
                status_code=409,
            )
        validation = self.repository.get_patch_validation(analysis_id, patch_id, validation_id)
        if validation is None:
            raise DriftGuardError(
                code="patch_validation_not_found",
                message="The requested patch validation does not exist for this patch.",
                status_code=404,
            )
        if validation.patch_id != patch.patch_id or validation.analysis_id != analysis_id:
            raise DriftGuardError(
                code="patch_validation_mismatch",
                message="The validation does not belong to the requested patch.",
                status_code=409,
            )
        if validation.readiness != ValidationReadiness.READY_FOR_REVIEW:
            raise DriftGuardError(
                code="patch_not_ready_for_pr",
                message=(
                    "Only a patch with READY_FOR_REVIEW validation can create a pull request."
                ),
                status_code=409,
            )
        if (
            patch.source_repository_hash != validation.source_repository_hash
            or patch.source_repository_hash != analysis.repository_file_sha256
        ):
            raise DriftGuardError(
                code="patch_validation_mismatch",
                message="Patch and validation source fingerprints do not match.",
                status_code=409,
            )
        return analysis, patch, validation

    def _require_analysis(self, analysis_id: str):
        analysis = self.repository.get_analysis(analysis_id)
        if analysis is None:
            raise DriftGuardError(
                code="analysis_not_found",
                message="The requested analysis does not exist.",
                status_code=404,
            )
        return analysis

    @staticmethod
    def _verify_base_commit(
        expected_commit: str | None, metadata: GitHubRepositoryMetadata
    ) -> None:
        if expected_commit != metadata.base_commit_sha:
            raise DriftGuardError(
                code="github_base_commit_mismatch",
                message="The GitHub base commit changed after validation.",
                status_code=409,
            )
        if not metadata.base_ref:
            raise DriftGuardError(
                code="github_branch_required",
                message="A GitHub base branch could not be determined.",
                status_code=409,
            )


def _branch_name(analysis_id: str, patch_id: str) -> str:
    analysis = re.sub(r"[^a-f0-9]", "", analysis_id.lower())[:8]
    patch = re.sub(r"[^a-f0-9]", "", patch_id.lower())[:8]
    branch = f"driftguard/{analysis or 'analysis'}-{patch or 'patch'}"
    if not _SAFE_BRANCH.fullmatch(branch) or branch in {"main", "master"}:
        raise DriftGuardError(
            code="unsafe_github_branch",
            message="A safe deterministic DriftGuard branch could not be generated.",
            status_code=409,
        )
    return branch


def _operation_label(changes) -> str:
    operations = sorted({(item.method.upper(), item.path) for item in changes})
    if len(operations) == 1:
        method, path = operations[0]
        return _metadata_text(f"{method} {path}", maximum=120)
    return "breaking API changes"


def _commit_message(changes) -> str:
    return f"fix: migrate {_operation_label(changes)} API usage"[:200]


def _pull_request_title(changes) -> str:
    return f"DriftGuard: migrate {_operation_label(changes)} API usage"[:200]


def _pull_request_body(*, changes, matches, patch, validation, maximum: int) -> str:
    direct = [item for item in matches if item.impact_depth == 0]
    transitive = [item for item in matches if item.impact_depth > 0]
    change_lines = [
        f"- {_markdown_text(item.method.upper())} {_markdown_text(item.path)}: "
        f"{_markdown_text(item.change_type.value.replace('_', ' '))}"
        for item in changes[:20]
    ]
    test_lines = [
        f"- {_markdown_text(item.file_path)}" for item in validation.related_tests[:20]
    ] or ["- No related test was statically discovered."]
    body = "\n".join(
        [
            "## DriftGuard API Migration",
            "",
            "### API changes",
            *change_lines,
            "",
            "### Impact",
            f"- Direct usages: {len(direct)}",
            f"- Transitive callers: {len(transitive)}",
            "",
            "### Proposed patch",
            f"- Files changed: {patch.files_changed}",
            f"- Structured edits: {patch.edit_count}",
            "",
            "### Validation",
            f"- Readiness: {validation.readiness.value.upper()}",
            f"- Passed: {validation.passed_count}",
            f"- Warnings: {validation.warning_count}",
            f"- Failed: {validation.failed_count}",
            f"- Unknown: {validation.unknown_count}",
            "",
            "### Related tests discovered",
            *test_lines,
            "",
            "### Important",
            "DriftGuard performed static validation only.",
            "Repository tests were not executed.",
            "This pull request requires human review before merge.",
            "DriftGuard did not merge or deploy this change.",
        ]
    )
    safe = redact_secrets(body)[0]
    return safe.encode("utf-8")[:maximum].decode("utf-8", errors="ignore")


def _verify_pull_request_result(result, metadata, commit_sha: str) -> None:
    parsed = urlparse(result.url)
    path = [part for part in parsed.path.split("/") if part]
    valid_path = (
        len(path) == 4
        and path[0].casefold() == metadata.owner.casefold()
        and path[1].casefold() == metadata.repository.casefold()
        and path[2] == "pull"
        and path[3] == str(result.number)
    )
    if (
        result.number < 1
        or parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or not valid_path
        or result.commit_sha != commit_sha
    ):
        raise DriftGuardError(
            code="github_pull_request_conflict",
            message="An existing pull request has unexpected repository or commit metadata.",
            status_code=409,
        )


def _metadata_text(value: str, *, maximum: int) -> str:
    normalized = re.sub(r"[^A-Za-z0-9 /._{}:-]+", " ", value)
    return " ".join(normalized.split())[:maximum] or "breaking API changes"


def _markdown_text(value: str) -> str:
    normalized = " ".join(value.replace("\x00", "").split())[:500]
    return re.sub(r"([\\`*_{}\[\]<>()#+.!|])", r"\\\1", normalized)


def _fingerprint(
    *,
    analysis_id: str,
    patch_id: str,
    validation_id: str,
    source_hash: str,
    base_commit_sha: str,
) -> str:
    value = json.dumps(
        {
            "analysis_id": analysis_id,
            "patch_id": patch_id,
            "validation_id": validation_id,
            "source_hash": source_hash,
            "base_commit_sha": base_commit_sha,
            "profile": PULL_REQUEST_PROFILE_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode()).hexdigest()
