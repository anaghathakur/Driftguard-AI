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
    patches = service.get_patch_proposals(analysis_id)
    pipeline = service.get_pipeline(analysis_id)

    comparison_summary = analysis.comparison_summary
    impacted_files = len(
        {match.file_path for match in matches}
    )

    return AnalysisReport(
        report_version="1.2",
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
            direct_matches=sum(match.impact_depth == 0 for match in matches),
            transitive_matches=sum(match.impact_depth > 0 for match in matches),
            max_impact_depth=max(
                (match.impact_depth for match in matches),
                default=0,
            ),
            risk_predictions=len(risks),
            migration_recommendations=len(migrations),
            patch_proposals=len(patches),
        ),
        changes=changes,
        matches=matches,
        risks=risks,
        migrations=migrations,
        patches=patches,
        pipeline=pipeline,
    )
