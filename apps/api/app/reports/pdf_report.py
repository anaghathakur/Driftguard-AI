"""Generate polished DriftGuard analysis reports as PDF bytes."""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
)

from apps.api.app.schemas.report import AnalysisReport

PAGE_WIDTH, PAGE_HEIGHT = A4

INK = HexColor("#111827")
MUTED = HexColor("#64748B")
ACCENT = HexColor("#0891B2")
ACCENT_LIGHT = HexColor("#ECFEFF")
BORDER = HexColor("#CBD5E1")
SURFACE = HexColor("#F8FAFC")


def build_analysis_pdf(report: AnalysisReport) -> bytes:
    """Render one complete DriftGuard analysis report to PDF bytes."""

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"DriftGuard Analysis {report.analysis.analysis_id}",
        author="DriftGuard AI",
        subject="API contract change and repository impact analysis",
    )

    styles = _styles()
    story: list[Any] = []
    story.extend(_title_block(report, styles))
    story.extend(_summary_block(report, styles))
    story.extend(_contract_block(report, styles))
    story.append(PageBreak())
    story.extend(_changes_block(report, styles))
    story.extend(_patches_block(report, styles))
    story.extend(_pipeline_block(report, styles))
    story.extend(_disclaimer_block(styles))

    analysis_id = report.analysis.analysis_id

    def draw_page(canvas: Any, doc: Any) -> None:
        _draw_page_chrome(
            canvas,
            doc,
            analysis_id=analysis_id,
        )

    document.build(
        story,
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )
    return buffer.getvalue()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DGTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=INK,
            spaceAfter=4,
        ),
        "eyebrow": ParagraphStyle(
            "DGEyebrow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=ACCENT,
            spaceAfter=5,
        ),
        "subtitle": ParagraphStyle(
            "DGSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            textColor=MUTED,
        ),
        "section": ParagraphStyle(
            "DGSection",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=INK,
            spaceBefore=15,
            spaceAfter=8,
        ),
        "change_title": ParagraphStyle(
            "DGChangeTitle",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=INK,
            spaceBefore=10,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "DGBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=INK,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "DGSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10.5,
            textColor=MUTED,
        ),
        "metric_value": ParagraphStyle(
            "DGMetricValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=INK,
            alignment=1,
        ),
        "metric_label": ParagraphStyle(
            "DGMetricLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=6.8,
            leading=8,
            textColor=MUTED,
            alignment=1,
        ),
        "bullet": ParagraphStyle(
            "DGBullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            leftIndent=9,
            firstLineIndent=-6,
            textColor=INK,
            spaceAfter=2,
        ),
        "code": ParagraphStyle(
            "DGCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.2,
            leading=10,
            textColor=INK,
            backColor=SURFACE,
            borderColor=BORDER,
            borderWidth=0.5,
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "disclaimer": ParagraphStyle(
            "DGDisclaimer",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.3,
            leading=10,
            textColor=MUTED,
        ),
    }


def _title_block(
    report: AnalysisReport,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    analysis = report.analysis
    generated_at = _display_datetime(report.generated_at)
    kind = _display(getattr(analysis, "kind", "analysis")).upper()
    status = _display(getattr(analysis, "status", "")).upper()
    subtitle = (
        f"{escape(kind)} analysis | Status: {escape(status)} | "
        f"Report generated: {escape(generated_at)}"
    )
    id_row = [
        Paragraph("<b>Analysis ID</b>", styles["small"]),
        Paragraph(escape(analysis.analysis_id), styles["small"]),
    ]

    return [
        Paragraph("DRIFTGUARD AI", styles["eyebrow"]),
        Paragraph("API Change Impact Analysis Report", styles["title"]),
        Paragraph(subtitle, styles["subtitle"]),
        Spacer(1, 6),
        Table(
            [id_row],
            colWidths=[27 * mm, 142 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ],
        ),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=1, color=ACCENT),
    ]


def _summary_block(
    report: AnalysisReport,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    summary = report.summary
    metrics = [
        ("TOTAL CHANGES", summary.total_changes),
        ("BREAKING", summary.breaking_changes),
        (
            "POTENTIALLY BREAKING",
            summary.potentially_breaking_changes,
        ),
        ("IMPACTED FILES", summary.impacted_files),
    ]

    metric_tables = []
    for label, value in metrics:
        value_cell = [
            Paragraph(str(value), styles["metric_value"]),
        ]
        label_cell = [
            Paragraph(label, styles["metric_label"]),
        ]
        metric_tables.append(
            Table(
                [value_cell, label_cell],
                colWidths=[38 * mm],
                style=[
                    ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                    ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ],
            )
        )

    metric_table = Table(
        [metric_tables],
        colWidths=[42 * mm] * 4,
    )
    details = Table(
        [
            [
                Paragraph("<b>Repository matches</b>", styles["body"]),
                Paragraph(str(summary.repository_matches), styles["body"]),
                Paragraph("<b>Risk predictions</b>", styles["body"]),
                Paragraph(str(summary.risk_predictions), styles["body"]),
            ],
            [
                Paragraph(
                    "<b>Migration recommendations</b>",
                    styles["body"],
                ),
                Paragraph(
                    str(summary.migration_recommendations),
                    styles["body"],
                ),
                Paragraph("<b>Overall risk</b>", styles["body"]),
                Paragraph(
                    escape(_overall_risk(report)),
                    styles["body"],
                ),
            ],
            [
                Paragraph("<b>Patch proposals</b>", styles["body"]),
                Paragraph(str(summary.patch_proposals), styles["body"]),
                Paragraph("<b>Patch application</b>", styles["body"]),
                Paragraph("Review only; not applied", styles["body"]),
            ],
        ],
        colWidths=[42 * mm, 20 * mm, 48 * mm, 58 * mm],
        style=[
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ],
    )

    return [
        Paragraph("Executive summary", styles["section"]),
        metric_table,
        Spacer(1, 8),
        details,
    ]


def _contract_block(
    report: AnalysisReport,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    old_contract = report.analysis.old_contract
    new_contract = report.analysis.new_contract
    rows = [
        [
            "",
            Paragraph("<b>Previous contract</b>", styles["body"]),
            Paragraph("<b>Proposed contract</b>", styles["body"]),
        ],
        _contract_row(
            "Title",
            old_contract.title,
            new_contract.title,
            styles,
        ),
        _contract_row(
            "Version",
            old_contract.version,
            new_contract.version,
            styles,
        ),
        _contract_row(
            "OpenAPI",
            old_contract.openapi_version,
            new_contract.openapi_version,
            styles,
        ),
        _contract_row(
            "Operations",
            old_contract.operation_count,
            new_contract.operation_count,
            styles,
        ),
    ]
    table = Table(
        rows,
        colWidths=[31 * mm, 69 * mm, 69 * mm],
        repeatRows=1,
        style=[
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ],
    )
    return [
        Paragraph("Contract overview", styles["section"]),
        table,
    ]


def _contract_row(
    label: str,
    old_value: Any,
    new_value: Any,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    return [
        Paragraph(f"<b>{escape(label)}</b>", styles["small"]),
        Paragraph(escape(_display(old_value)), styles["body"]),
        Paragraph(escape(_display(new_value)), styles["body"]),
    ]


def _changes_block(
    report: AnalysisReport,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    story: list[Any] = [
        Paragraph("Detected changes", styles["section"]),
        Paragraph(
            "Each change below combines the contract diff, repository "
            "impact, ML risk assessment, and migration guidance.",
            styles["body"],
        ),
    ]

    matches_by_change: dict[str, list[Any]] = defaultdict(list)
    for match in report.matches:
        matches_by_change[match.change_id].append(match)

    risks_by_change = {
        risk.change_id: risk for risk in report.risks
    }
    migrations_by_change = {
        migration.change_id: migration
        for migration in report.migrations
    }

    for index, change in enumerate(report.changes, start=1):
        story.append(Spacer(1, 5))
        story.append(
            HRFlowable(
                width="100%",
                thickness=0.6,
                color=BORDER,
            )
        )
        title = (
            f"{index}. {escape(_display(change.method))} "
            f"{escape(_display(change.path))}"
        )
        story.append(Paragraph(title, styles["change_title"]))

        classification = (
            f"<b>Classification:</b> "
            f"{escape(_display(change.category))} &nbsp;&nbsp; "
            f"<b>Severity:</b> {escape(_display(change.severity))}"
        )
        story.append(Paragraph(classification, styles["body"]))
        story.append(
            Paragraph(
                escape(_display(change.explanation)),
                styles["body"],
            )
        )

        subject = _display(getattr(change, "subject", ""))
        if subject:
            story.append(
                Paragraph(
                    f"<b>Subject:</b> {escape(subject)}",
                    styles["body"],
                )
            )

        story.extend(
            _source_impact(
                matches_by_change.get(change.change_id, []),
                styles,
            )
        )

        risk = risks_by_change.get(change.change_id)
        if risk is not None:
            story.extend(_risk_block(risk, styles))
        else:
            story.extend(
                _missing_insight(
                    "ML risk assessment",
                    "No persisted risk prediction exists for this "
                    "historical analysis.",
                    styles,
                )
            )

        migration = migrations_by_change.get(change.change_id)
        if migration is not None:
            story.extend(_migration_block(migration, styles))
        else:
            story.extend(
                _missing_insight(
                    "Migration plan",
                    "No persisted migration recommendation exists for "
                    "this historical analysis.",
                    styles,
                )
            )

    return story


def _source_impact(
    matches: list[Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    story: list[Any] = [
        Paragraph("Source impact", styles["section"]),
    ]

    if not matches:
        story.append(
            Paragraph(
                "No repository usage was matched. Dynamic URL "
                "construction or indirect client wrappers may still "
                "require manual review.",
                styles["body"],
            )
        )
        return story

    direct_count = sum(getattr(match, "impact_depth", 0) == 0 for match in matches)
    transitive_count = len(matches) - direct_count
    maximum_depth = max(
        (getattr(match, "impact_depth", 0) for match in matches),
        default=0,
    )
    story.append(
        Paragraph(
            f"Direct usages: {direct_count} | Transitive callers: "
            f"{transitive_count} | Maximum depth: {maximum_depth}",
            styles["body"],
        )
    )

    for match in matches:
        location = (
            f"{_display(match.file_path)} - line {match.line}, "
            f"column {match.column}"
        )
        details = (
            f"<b>{escape(location)}</b><br/>"
            f"Match: {escape(_display(match.match_kind))} | "
            f"Confidence: {escape(_display(match.confidence))} | "
            f"Depth: {getattr(match, 'impact_depth', 0)}"
        )
        symbol = _display(getattr(match, "symbol", ""))
        if symbol:
            details += f"<br/>Symbol: {escape(symbol)}"
        story.append(Paragraph(details, styles["body"]))

        evidence = _display(match.evidence)
        if evidence:
            story.append(
                Preformatted(
                    evidence,
                    styles["code"],
                    maxLineLength=95,
                )
            )

        trace = list(getattr(match, "trace", []) or [])[:6]
        if trace:
            story.append(Paragraph("Dependency chain", styles["small"]))
            for step in trace:
                step_symbol = _display(getattr(step, "symbol", "")) or "module scope"
                step_text = (
                    f"&#8594; {escape(step_symbol)} "
                    f"({escape(_display(step.relation))}) - "
                    f"{escape(_display(step.file_path))}:{step.line}"
                )
                story.append(Paragraph(step_text, styles["small"]))

    return story


def _risk_block(
    risk: Any,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    story: list[Any] = [
        Paragraph("ML risk assessment", styles["section"]),
    ]
    model = (
        f"{_display(risk.model_name)} "
        f"{_display(risk.model_version)}"
    ).strip()
    rows = [
        [
            Paragraph("<b>Risk level</b>", styles["small"]),
            Paragraph(
                escape(_display(risk.risk_level).upper()),
                styles["body"],
            ),
            Paragraph("<b>Score</b>", styles["small"]),
            Paragraph(
                escape(_display(risk.risk_score)),
                styles["body"],
            ),
        ],
        [
            Paragraph("<b>Prediction source</b>", styles["small"]),
            Paragraph(
                escape(_display(risk.prediction_source)),
                styles["body"],
            ),
            Paragraph("<b>Model</b>", styles["small"]),
            Paragraph(escape(model), styles["body"]),
        ],
    ]
    story.append(
        Table(
            rows,
            colWidths=[31 * mm, 50 * mm, 31 * mm, 57 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ],
        )
    )

    reasons = list(getattr(risk, "reasons", []) or [])
    if reasons:
        story.append(Paragraph("Why this is risky", styles["body"]))
        story.extend(_bullet_items(reasons, styles))

    fallback_reason = _display(
        getattr(risk, "fallback_reason", "")
    )
    if fallback_reason:
        note = f"<b>Fallback note:</b> {escape(fallback_reason)}"
        story.append(Paragraph(note, styles["small"]))

    return story


def _migration_block(
    migration: Any,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    story: list[Any] = [
        Paragraph("Migration plan", styles["section"]),
        Paragraph(
            f"<b>{escape(_display(migration.summary))}</b>",
            styles["body"],
        ),
        Paragraph(
            escape(_display(migration.why_it_matters)),
            styles["body"],
        ),
        Paragraph(
            escape(_display(migration.affected_code_explanation)),
            styles["body"],
        ),
    ]

    confidence = round(float(migration.confidence) * 100)
    provider_text = (
        f"{_display(migration.provider)} / "
        f"{_display(migration.provider_model)}"
    )
    provider_line = (
        f"<b>Confidence:</b> {confidence}% &nbsp;&nbsp; "
        f"<b>Provider:</b> {escape(provider_text)}"
    )
    story.append(Paragraph(provider_line, styles["small"]))

    story.append(Paragraph("Migration steps", styles["body"]))
    story.extend(
        _numbered_items(
            list(migration.migration_steps),
            styles,
        )
    )

    story.append(Paragraph("Suggested tests", styles["body"]))
    story.extend(
        _bullet_items(
            list(migration.suggested_tests),
            styles,
        )
    )

    code_example = _display(
        getattr(migration, "code_example", "")
    )
    if code_example:
        story.append(Paragraph("Example", styles["body"]))
        story.append(
            Preformatted(
                code_example,
                styles["code"],
                maxLineLength=95,
            )
        )

    warnings = list(getattr(migration, "warnings", []) or [])
    if warnings:
        story.append(Paragraph("Warnings", styles["body"]))
        story.extend(_bullet_items(warnings, styles))

    return story


def _pipeline_block(
    report: AnalysisReport,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    story: list[Any] = [
        PageBreak(),
        Paragraph("Pipeline information", styles["section"]),
        Paragraph(
            "Recorded processing stages for this analysis. Durations "
            "are persisted by the backend pipeline.",
            styles["body"],
        ),
    ]

    rows = [
        [
            Paragraph("<b>Stage</b>", styles["small"]),
            Paragraph("<b>Status</b>", styles["small"]),
            Paragraph("<b>Duration</b>", styles["small"]),
        ]
    ]
    for stage in report.pipeline:
        rows.append(
            [
                Paragraph(
                    escape(_display(stage.stage_name)),
                    styles["small"],
                ),
                Paragraph(
                    escape(_display(stage.status)),
                    styles["small"],
                ),
                Paragraph(
                    f"{_display(stage.duration_ms)} ms",
                    styles["small"],
                ),
            ]
        )

    story.append(
        Table(
            rows,
            colWidths=[105 * mm, 34 * mm, 30 * mm],
            repeatRows=1,
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT_LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ],
        )
    )
    return story


def _disclaimer_block(
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    message = (
        "<b>Important:</b> DriftGuard risk scores rank engineering "
        "review priority. AI-generated migration guidance may be "
        "incomplete or wrong and must be reviewed by a developer. "
        "This report does not represent autonomous approval, testing, "
        "deployment, or code modification."
    )
    return [
        Spacer(1, 15),
        HRFlowable(width="100%", thickness=0.6, color=BORDER),
        Spacer(1, 5),
        Paragraph(message, styles["disclaimer"]),
    ]


def _patches_block(
    report: AnalysisReport,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    if not report.patches:
        return []
    story: list[Any] = [Paragraph("Proposed patches", styles["section"])]
    for proposal in report.patches[:3]:
        story.append(
            Paragraph(
                f"<b>{escape(_display(proposal.summary))}</b><br/>"
                f"Status: {escape(_display(proposal.status))} | "
                f"Provider: {escape(_display(proposal.provider))} / "
                f"{escape(_display(proposal.provider_model))}<br/>"
                f"Files: {proposal.files_changed} | Edits: {proposal.edit_count}",
                styles["body"],
            )
        )
        checks = proposal.validation
        story.append(
            Paragraph(
                "Validation: snapshot verified, paths safe, allowed scope verified, "
                "anchors verified, syntax valid, limits valid.",
                styles["small"],
            )
        )
        diff_lines = proposal.unified_diff.splitlines()[:40]
        excerpt = "<br/>".join(escape(line or " ") for line in diff_lines)
        story.append(
            Paragraph(
                f'<font name="Courier" size="7">{excerpt}</font>',
                styles["small"],
            )
        )
        if checks.warnings or proposal.warnings:
            warning_text = " ".join([*checks.warnings, *proposal.warnings])[:1_000]
            story.append(
                Paragraph(f"Warnings: {escape(warning_text)}", styles["small"])
            )
    story.append(
        Paragraph(
            "No repository files were modified. Every patch is a review-only proposal.",
            styles["body"],
        )
    )
    return story


def _missing_insight(
    title: str,
    message: str,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    return [
        Paragraph(title, styles["section"]),
        Paragraph(escape(message), styles["body"]),
    ]


def _bullet_items(
    items: list[Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    return [
        Paragraph(
            f"- {escape(_display(item))}",
            styles["bullet"],
        )
        for item in items
    ]


def _numbered_items(
    items: list[Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    return [
        Paragraph(
            f"{index}. {escape(_display(item))}",
            styles["bullet"],
        )
        for index, item in enumerate(items, start=1)
    ]


def _overall_risk(report: AnalysisReport) -> str:
    if not report.risks:
        return "Not available"

    ranking = {
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }
    highest = max(
        report.risks,
        key=lambda item: ranking.get(
            _display(item.risk_level).lower(),
            0,
        ),
    )
    level = _display(highest.risk_level).upper()
    score = _display(highest.risk_score)
    return f"{level} ({score}/100)"


def _display(value: Any) -> str:
    if value is None:
        return ""

    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        value = enum_value

    return str(value).replace("_", " ").strip()


def _display_datetime(value: Any) -> str:
    if value is None:
        return ""

    try:
        return value.strftime("%Y-%m-%d %H:%M UTC")
    except (AttributeError, ValueError):
        return _display(value)


def _draw_page_chrome(
    canvas: Any,
    doc: Any,
    *,
    analysis_id: str,
) -> None:
    canvas.saveState()
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1)
    canvas.line(
        16 * mm,
        PAGE_HEIGHT - 10 * mm,
        PAGE_WIDTH - 16 * mm,
        PAGE_HEIGHT - 10 * mm,
    )
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(
        16 * mm,
        9 * mm,
        f"DriftGuard AI | {analysis_id}",
    )
    canvas.drawRightString(
        PAGE_WIDTH - 16 * mm,
        9 * mm,
        f"Page {doc.page}",
    )
    canvas.restoreState()
