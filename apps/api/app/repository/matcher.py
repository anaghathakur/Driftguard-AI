"""Deterministically associate contract changes with repository API usage."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from apps.api.app.core.config import settings
from apps.api.app.domain.openapi import NormalizedContract
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.repository.code_analyzer import (
    ApiUsageAnchor,
    CodeCallEdge,
    RepositoryCodeAnalyzer,
    RepositoryCodeGraph,
    propagation_paths,
)
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.impact import (
    ChangeImpact,
    CodeAnalysisSummary,
    ImpactAnalysisKind,
    ImpactMatch,
    ImpactTraceRelation,
    ImpactTraceStep,
    MatchConfidence,
    MatchKind,
)

MAX_MATCHES_PER_CHANGE = 100
METHOD_CONTEXT_LINES = 2


@dataclass(frozen=True, slots=True)
class ImpactMatchResult:
    impacts: list[ChangeImpact]
    code_analysis: CodeAnalysisSummary


class ApiImpactMatcher:
    def __init__(
        self,
        *,
        max_symbols: int = settings.max_code_symbols,
        max_edges: int = settings.max_code_graph_edges,
        max_impact_depth: int = settings.max_impact_depth,
    ) -> None:
        self.max_impact_depth = max_impact_depth
        self.code_analyzer = RepositoryCodeAnalyzer(
            max_symbols=max_symbols,
            max_edges=max_edges,
            max_impact_depth=max_impact_depth,
        )

    def match(
        self,
        changes: Iterable[ApiChange],
        repository: RepositoryScan,
        old_contract: NormalizedContract,
        new_contract: NormalizedContract,
    ) -> list[ChangeImpact]:
        return self.analyze(
            changes,
            repository,
            old_contract,
            new_contract,
        ).impacts

    def analyze(
        self,
        changes: Iterable[ApiChange],
        repository: RepositoryScan,
        old_contract: NormalizedContract,
        new_contract: NormalizedContract,
    ) -> ImpactMatchResult:
        change_list = list(changes)
        graph = self.code_analyzer.analyze(repository)
        impacts: list[ChangeImpact] = []
        transitive_matches = 0
        for change in change_list:
            operation_ids = _operation_ids(change, old_contract, new_contract)
            lexical_matches: list[ImpactMatch] = []
            for source_file in repository.files:
                lexical_matches.extend(self._match_file(change, operation_ids, source_file))
                if len(lexical_matches) >= MAX_MATCHES_PER_CHANGE:
                    break
            semantic_matches = self._semantic_matches(change, graph)
            matches = _merge_matches(lexical_matches, semantic_matches)
            transitive_matches += sum(match.impact_depth > 0 for match in matches)
            impacts.append(
                ChangeImpact(
                    change_id=change.change_id,
                    path=change.path,
                    method=change.method,
                    matches=matches[:MAX_MATCHES_PER_CHANGE],
                )
            )
        return ImpactMatchResult(
            impacts=impacts,
            code_analysis=graph.summary.model_copy(
                update={"transitive_matches": transitive_matches}
            ),
        )

    def _semantic_matches(
        self,
        change: ApiChange,
        graph: RepositoryCodeGraph,
    ) -> list[ImpactMatch]:
        symbols = graph.symbol_map()
        matches: list[ImpactMatch] = []
        path_pattern = _path_pattern(change.path)
        for anchor in graph.anchors:
            if anchor.method.casefold() != change.method.casefold():
                continue
            if path_pattern.search(anchor.path) is None:
                continue
            symbol = symbols.get(anchor.symbol_id) if anchor.symbol_id else None
            direct_trace = [_direct_trace(anchor, symbol.qualified_name if symbol else None)]
            matches.append(
                ImpactMatch(
                    file_path=anchor.file_path,
                    line=anchor.line,
                    column=anchor.column,
                    match_kind=MatchKind.DIRECT_SEMANTIC,
                    confidence=MatchConfidence.HIGH,
                    evidence=anchor.evidence,
                    symbol=symbol.qualified_name if symbol else None,
                    language=anchor.language,
                    impact_depth=0,
                    analysis_kind=ImpactAnalysisKind.DIRECT,
                    trace=direct_trace,
                )
            )
            for depth, caller, edge, chain in propagation_paths(
                graph,
                anchor,
                max_depth=self.max_impact_depth,
            ):
                matches.append(
                    ImpactMatch(
                        file_path=caller.file_path,
                        line=edge.line,
                        column=edge.column,
                        match_kind=(MatchKind.WRAPPER if depth == 1 else MatchKind.TRANSITIVE_CALL),
                        confidence=MatchConfidence.MEDIUM,
                        evidence=edge.evidence,
                        symbol=caller.qualified_name,
                        language=caller.language,
                        impact_depth=depth,
                        analysis_kind=(
                            ImpactAnalysisKind.WRAPPER
                            if depth == 1
                            else ImpactAnalysisKind.TRANSITIVE
                        ),
                        trace=_trace_chain(anchor, symbol, chain, symbols),
                    )
                )
        return matches

    def _match_file(
        self,
        change: ApiChange,
        operation_ids: tuple[str, ...],
        source_file: ScannedSourceFile,
    ) -> list[ImpactMatch]:
        lines = source_file.content.splitlines()
        path_pattern = _path_pattern(change.path)
        operation_patterns = [
            re.compile(rf"(?<![\w$]){re.escape(operation_id)}(?![\w$])")
            for operation_id in operation_ids
        ]
        matches: list[ImpactMatch] = []
        occupied_lines: set[int] = set()

        for line_index, line in enumerate(lines):
            operation_match = _first_match(operation_patterns, line)
            if operation_match:
                matches.append(
                    _impact_match(
                        source_file.path,
                        line_index,
                        operation_match.start(),
                        MatchKind.OPERATION_ID,
                        MatchConfidence.HIGH,
                        line,
                    )
                )
                occupied_lines.add(line_index)
                continue

            path_match = path_pattern.search(line)
            if not path_match or line_index in occupied_lines:
                continue
            method_found = _method_in_context(lines, line_index, change.method)
            matches.append(
                _impact_match(
                    source_file.path,
                    line_index,
                    path_match.start(),
                    MatchKind.PATH_AND_METHOD if method_found else MatchKind.PATH,
                    MatchConfidence.HIGH if method_found else MatchConfidence.MEDIUM,
                    line,
                )
            )
        return matches


def _operation_ids(
    change: ApiChange,
    old_contract: NormalizedContract,
    new_contract: NormalizedContract,
) -> tuple[str, ...]:
    key = f"{change.method.upper()} {change.path}"
    values = {
        operation.operation_id
        for contract in (old_contract, new_contract)
        if (operation := contract.operations.get(key)) is not None and operation.operation_id
    }
    return tuple(sorted(values))


def _path_pattern(path: str) -> re.Pattern[str]:
    parts: list[str] = []
    cursor = 0
    for parameter in re.finditer(r"\{[^{}]+\}", path):
        parts.append(re.escape(path[cursor : parameter.start()]))
        parts.append(r"[^/\s\"'`?#]+")
        cursor = parameter.end()
    parts.append(re.escape(path[cursor:]))
    parts.append(r"(?![A-Za-z0-9._~!$&()*+,;=:@%/-])")
    return re.compile("".join(parts))


def _method_in_context(lines: list[str], line_index: int, method: str) -> bool:
    start = max(0, line_index - METHOD_CONTEXT_LINES)
    end = min(len(lines), line_index + METHOD_CONTEXT_LINES + 1)
    context = "\n".join(lines[start:end])
    escaped_method = re.escape(method)
    patterns = (
        rf"\.\s*{escaped_method}\s*\(",
        rf"\bmethod\s*[:=]\s*[\"']{escaped_method}[\"']",
        rf"[\"']method[\"']\s*:\s*[\"']{escaped_method}[\"']",
        rf"\brequest\s*\(\s*[\"']{escaped_method}[\"']",
    )
    return any(re.search(pattern, context, re.IGNORECASE) for pattern in patterns)


def _first_match(patterns: list[re.Pattern[str]], line: str) -> re.Match[str] | None:
    for pattern in patterns:
        if match := pattern.search(line):
            return match
    return None


def _impact_match(
    file_path: str,
    line_index: int,
    column_index: int,
    match_kind: MatchKind,
    confidence: MatchConfidence,
    line: str,
) -> ImpactMatch:
    evidence = " ".join(line.strip().split())[:240]
    return ImpactMatch(
        file_path=file_path,
        line=line_index + 1,
        column=column_index + 1,
        match_kind=match_kind,
        confidence=confidence,
        evidence=evidence,
    )


def _direct_trace(anchor: ApiUsageAnchor, symbol: str | None) -> ImpactTraceStep:
    return ImpactTraceStep(
        file_path=anchor.file_path,
        symbol=symbol,
        relation=ImpactTraceRelation.DIRECT_API_USAGE,
        line=anchor.line,
        column=anchor.column,
        evidence=anchor.evidence,
    )


def _trace_chain(
    anchor: ApiUsageAnchor,
    anchor_symbol: object | None,
    chain: tuple[CodeCallEdge, ...],
    symbols: dict[str, object],
) -> list[ImpactTraceStep]:
    qualified_name = getattr(anchor_symbol, "qualified_name", None)
    trace = [_direct_trace(anchor, qualified_name)]
    for edge in chain:
        caller = symbols.get(edge.caller_symbol_id)
        trace.append(
            ImpactTraceStep(
                file_path=edge.file_path,
                symbol=getattr(caller, "qualified_name", None),
                relation=ImpactTraceRelation.CALLS,
                line=edge.line,
                column=edge.column,
                evidence=edge.evidence,
            )
        )
    return trace


def _merge_matches(
    lexical: list[ImpactMatch],
    semantic: list[ImpactMatch],
) -> list[ImpactMatch]:
    precedence = {
        MatchKind.DIRECT_SEMANTIC: 5,
        MatchKind.WRAPPER: 4,
        MatchKind.TRANSITIVE_CALL: 3,
        MatchKind.PATH_AND_METHOD: 2,
        MatchKind.OPERATION_ID: 2,
        MatchKind.PATH: 1,
    }
    direct_by_line = {
        (match.file_path, match.line): match
        for match in semantic
        if match.analysis_kind == ImpactAnalysisKind.DIRECT
    }
    semantic_by_line: dict[tuple[str, int], ImpactMatch] = {}
    for match in semantic:
        key = (match.file_path, match.line)
        existing = semantic_by_line.get(key)
        if existing is None or match.impact_depth < existing.impact_depth:
            semantic_by_line[key] = match
    direct_by_file: dict[str, list[ImpactMatch]] = {}
    for match in direct_by_line.values():
        direct_by_file.setdefault(match.file_path, []).append(match)
    used_direct: set[tuple[str, int]] = set()
    candidates: list[ImpactMatch] = []
    for match in lexical:
        if _looks_like_import_evidence(match.evidence):
            continue
        direct_key = (match.file_path, match.line)
        semantic_same_line = semantic_by_line.get(direct_key)
        if (
            semantic_same_line is not None
            and semantic_same_line.analysis_kind != ImpactAnalysisKind.DIRECT
        ):
            continue
        direct = direct_by_line.get(direct_key)
        if direct is None:
            if any(
                abs(candidate.line - match.line) <= METHOD_CONTEXT_LINES + 1
                for candidate in direct_by_file.get(match.file_path, [])
            ):
                continue
            candidates.append(match)
            continue
        used_direct.add(direct_key)
        candidates.append(
            direct.model_copy(
                update={
                    "line": match.line,
                    "column": match.column,
                    "match_kind": match.match_kind,
                    "evidence": match.evidence,
                }
            )
        )
    candidates.extend(
        match
        for match in semantic
        if match.analysis_kind != ImpactAnalysisKind.DIRECT
        or (match.file_path, match.line) not in used_direct
    )

    strongest: dict[tuple[str, int, int, str | None], ImpactMatch] = {}
    for match in candidates:
        key = (match.file_path, match.line, match.column)
        full_key = (*key, match.symbol if match.impact_depth > 0 else None)
        existing = strongest.get(full_key)
        if existing is None or precedence[match.match_kind] > precedence[existing.match_kind]:
            strongest[full_key] = match
    return sorted(
        strongest.values(),
        key=lambda match: (
            match.impact_depth,
            match.file_path,
            match.line,
            match.column,
            -precedence[match.match_kind],
            match.symbol or "",
        ),
    )


def _looks_like_import_evidence(evidence: str) -> bool:
    normalized = evidence.strip().casefold()
    return normalized.startswith(("import ", "export ")) and " from " in normalized
