"""Orchestrate migration recommendations with a deterministic fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.migration.context import (
    MigrationContext,
    build_prompt,
    impact_for_change,
    redact_generated_text,
    risk_for_change,
)
from apps.api.app.migration.fallback import (
    deterministic_recommendation,
)
from apps.api.app.migration.provider import (
    MigrationRecommendationProvider,
)
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.impact import ChangeImpact
from apps.api.app.schemas.migration import (
    GeneratedMigrationContent,
    MigrationProvider,
    MigrationProviderStatus,
    MigrationRecommendation,
    RecommendationSource,
)
from apps.api.app.schemas.risk import RiskPrediction


class MigrationRecommendationService:
    """Generate recommendations and fall back safely on provider failure."""

    def __init__(
        self,
        provider: MigrationRecommendationProvider,
        *,
        prompt_version: str = "migration-prompt-v1",
        schema_version: str = "migration-schema-v1",
    ) -> None:
        self.provider = provider
        self.prompt_version = prompt_version
        self.schema_version = schema_version

    def fingerprint_profile(self) -> str:
        """Return configuration that changes recommendation output."""

        return "|".join(
            [
                self.provider.name.value,
                self.provider.model_name,
                self.prompt_version,
                self.schema_version,
            ]
        )

    def status(self) -> MigrationProviderStatus:
        """Return safe public provider status."""

        active_provider = (
            self.provider.name if self.provider.available else MigrationProvider.DETERMINISTIC
        )

        return MigrationProviderStatus(
            configured_provider=self.provider.name,
            active_provider=active_provider,
            provider_model=self.provider.model_name,
            available=self.provider.available,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            fallback_enabled=True,
            warning=self.provider.warning,
        )

    def generate_all(
        self,
        *,
        analysis_id: str,
        changes: list[ApiChange],
        impacts: list[ChangeImpact],
        risks: list[RiskPrediction],
    ) -> list[MigrationRecommendation]:
        """Generate one recommendation for every detected API change."""

        recommendations: list[MigrationRecommendation] = []

        for change in changes:
            context = MigrationContext(
                analysis_id=analysis_id,
                change=change,
                impact=impact_for_change(
                    change,
                    impacts,
                ),
                risk=risk_for_change(
                    change,
                    risks,
                ),
            )

            recommendations.append(self.generate(context))

        return recommendations

    def generate(
        self,
        context: MigrationContext,
    ) -> MigrationRecommendation:
        """Generate one safe and validated recommendation."""

        prompt = build_prompt(context)

        provider_warning_parts = list(prompt.warnings)

        provider = self.provider.name

        try:
            content = self.provider.generate(
                context,
                prompt,
            )

            recommendation_source = (
                RecommendationSource.MOCK
                if provider == MigrationProvider.MOCK
                else RecommendationSource.GEMINI
            )

        except Exception as exc:
            content = deterministic_recommendation(context)

            recommendation_source = RecommendationSource.DETERMINISTIC_FALLBACK

            provider_warning_parts.append(_safe_provider_warning(exc))

        safe_content, output_redactions = _sanitize_content(content)

        total_redactions = prompt.redactions_applied + output_redactions

        if output_redactions:
            provider_warning_parts.append(
                f"Redacted {output_redactions} potential secret value(s) from provider output."
            )

        provider_warning = _bounded_warning(provider_warning_parts)

        generated_at = datetime.now(UTC)

        recommendation_id = str(
            uuid5(
                NAMESPACE_URL,
                ":".join(
                    [
                        context.analysis_id,
                        context.change.change_id,
                        self.prompt_version,
                        self.schema_version,
                        self.provider.model_name,
                    ]
                ),
            )
        )

        return MigrationRecommendation(
            **safe_content.model_dump(),
            recommendation_id=recommendation_id,
            analysis_id=context.analysis_id,
            change_id=context.change.change_id,
            provider=provider,
            provider_model=self.provider.model_name,
            recommendation_source=recommendation_source,
            provider_warning=provider_warning,
            redactions_applied=total_redactions,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            generated_at=generated_at,
        )


def _sanitize_content(
    content: GeneratedMigrationContent,
) -> tuple[GeneratedMigrationContent, int]:
    """Redact provider output before persistence."""

    total = 0

    def clean(
        value: str,
        max_chars: int,
    ) -> str:
        nonlocal total

        safe_value, count = redact_generated_text(value)
        total += count

        return safe_value[:max_chars]

    safe_content = GeneratedMigrationContent(
        summary=clean(
            content.summary,
            500,
        ),
        why_it_matters=clean(
            content.why_it_matters,
            1_000,
        ),
        affected_code_explanation=clean(
            content.affected_code_explanation,
            1_000,
        ),
        migration_steps=[clean(item, 500) for item in content.migration_steps],
        suggested_tests=[clean(item, 500) for item in content.suggested_tests],
        code_example=clean(
            content.code_example,
            2_000,
        ),
        assumptions=[clean(item, 500) for item in content.assumptions],
        warnings=[clean(item, 500) for item in content.warnings],
        confidence=content.confidence,
    )

    return safe_content, total


def _safe_provider_warning(
    exc: Exception,
) -> str:
    """Return a warning without exposing provider secrets or raw errors."""

    exception_name = type(exc).__name__

    return f"AI provider failed safely ({exception_name}); deterministic guidance was used."


def _bounded_warning(
    parts: list[str],
) -> str | None:
    """Combine unique warnings within the persisted size limit."""

    unique_parts = [part.strip() for part in dict.fromkeys(parts) if part.strip()]

    if not unique_parts:
        return None

    return " ".join(unique_parts)[:500]
