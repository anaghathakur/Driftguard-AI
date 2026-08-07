"""Build complete exportable reports from persisted analysis data."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.api.app.schemas.report import (
    AnalysisReport,
    AnalysisReportSummary,
)
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService


def build_analysis_report(
    service: AnalysisPipelineService,
    analysis_id: str,
) -> AnalysisReport:
    """Collect one persisted analysis into a single report response."""

    analysis = service.get_analysis(analysis_id)
    changes = service.get_changes(analysis_id)
    matches = service.get_matches(analysis_id)
    risks = service.get_risk_predictions(analysis_id)
    migrations = service.get_migration_recommendations(analysis_id)
    pipeline = service.get_pipeline(analysis_id)

    comparison_summary = analysis.comparison_summary
    impacted_files = len(
        {match.file_path for match in matches}
    )

    return AnalysisReport(
        report_version="1.0",
        generated_at=datetime.now(UTC),
        analysis=analysis,
        summary=AnalysisReportSummary(
            total_changes=comparison_summary.total_changes,
            breaking_changes=(
                comparison_summary.breaking_changes
            ),
            potentially_breaking_changes=(
                comparison_summary.potentially_breaking_changes
            ),
            non_breaking_changes=(
                comparison_summary.non_breaking_changes
            ),
            repository_matches=len(matches),
            impacted_files=impacted_files,
            risk_predictions=len(risks),
            migration_recommendations=len(migrations),
        ),
        changes=changes,
        matches=matches,
        risks=risks,
        migrations=migrations,
        pipeline=pipeline,
    )