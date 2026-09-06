"""Static GraphQL consumer-document matching that reuses the existing call graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from graphql import GraphQLError, parse
from graphql.language import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    OperationDefinitionNode,
    SelectionSetNode,
)

from apps.api.app.core.config import settings
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.repository.code_analyzer import (
    ApiUsageAnchor,
    CodeSymbol,
    RepositoryCodeAnalyzer,
    RepositoryCodeGraph,
    propagation_paths,
)
from apps.api.app.repository.matcher import ImpactMatchResult
from apps.api.app.schemas.comparison import ApiChange, ChangeType, OperationKind
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactAnalysisKind,
    ImpactMatch,
    ImpactTraceRelation,
    ImpactTraceStep,
    MatchConfidence,
    MatchKind,
)

_TAGGED_DOCUMENT = re.compile(r"(?:\b(?:gql|graphql)\s*)`(?P<body>[\s\S]*?)`", re.MULTILINE)
_PYTHON_DOCUMENT = re.compile(r"(?P<quote>'''|\"\"\")(?P<body>[\s\S]*?)(?P=quote)", re.MULTILINE)
_GRAPHQL_START = re.compile(r"\b(query|mutation|subscription|fragment)\b|\{\s*[_A-Za-z]")


@dataclass(frozen=True, slots=True)
class ParsedConsumerDocument:
    file: ScannedSourceFile
    document: DocumentNode
    body: str
    start_offset: int


class GraphQLImpactMatcher:
    def __init__(self, *, max_impact_depth: int = settings.max_impact_depth) -> None:
        self.max_impact_depth = max_impact_depth
        self.code_analyzer = RepositoryCodeAnalyzer(max_impact_depth=max_impact_depth)

    def analyze(self, changes: list[ApiChange], repository: RepositoryScan) -> ImpactMatchResult:
        graph = self.code_analyzer.analyze(repository)
        documents = _parse_documents(repository)
        impacts: list[ChangeImpact] = []
        transitive = 0
        for change in changes:
            direct = self._direct_matches(change, documents, graph)
            matches = list(direct)
            for match, anchor in direct:
                matches.extend(self._propagate(match, anchor, graph))
            flattened = [item[0] if isinstance(item, tuple) else item for item in matches]
            flattened.extend(_lexical_fallback(change, repository, flattened))
            flattened = _deduplicate(flattened)[:100]
            transitive += sum(item.impact_depth > 0 for item in flattened)
            impacts.append(
                ChangeImpact(
                    change_id=change.change_id,
                    operation_identifier=change.operation_identifier,
                    operation_kind=change.operation_kind,
                    matches=flattened,
                )
            )
        return ImpactMatchResult(
            impacts=impacts,
            code_analysis=graph.summary.model_copy(
                update={
                    "direct_api_anchors": graph.summary.direct_api_anchors
                    + sum(
                        len(self._direct_matches(change, documents, graph)) for change in changes
                    ),
                    "transitive_matches": transitive,
                }
            ),
        )

    def _direct_matches(
        self,
        change: ApiChange,
        documents: list[ParsedConsumerDocument],
        graph: RepositoryCodeGraph,
    ) -> list[tuple[ImpactMatch, ApiUsageAnchor]]:
        results: list[tuple[ImpactMatch, ApiUsageAnchor]] = []
        for parsed in documents:
            for field in _relevant_fields(change, parsed.document):
                relative = field.loc.start if field.loc else 0
                absolute = parsed.start_offset + relative
                line, column = _line_column(parsed.file.content, absolute)
                symbol = _containing_symbol(graph, parsed.file.path, absolute)
                evidence = _evidence(parsed.file.content, line)
                anchor = ApiUsageAnchor(
                    symbol_id=symbol.symbol_id if symbol else None,
                    language=_language(parsed.file.path),
                    file_path=parsed.file.path,
                    method="graphql",
                    path=change.operation_identifier or change.subject or "graphql",
                    line=line,
                    column=column,
                    evidence=evidence,
                )
                results.append(
                    (
                        ImpactMatch(
                            file_path=parsed.file.path,
                            line=line,
                            column=column,
                            match_kind=MatchKind.DIRECT_SEMANTIC,
                            confidence=MatchConfidence.HIGH,
                            evidence=evidence,
                            symbol=symbol.qualified_name if symbol else None,
                            language=anchor.language,
                            impact_depth=0,
                            analysis_kind=ImpactAnalysisKind.DIRECT,
                            trace=[
                                ImpactTraceStep(
                                    file_path=parsed.file.path,
                                    symbol=symbol.qualified_name if symbol else None,
                                    relation=ImpactTraceRelation.DIRECT_GRAPHQL_USAGE,
                                    line=line,
                                    column=column,
                                    evidence=evidence,
                                )
                            ],
                        ),
                        anchor,
                    )
                )
        return results

    def _propagate(
        self, direct: ImpactMatch, anchor: ApiUsageAnchor, graph: RepositoryCodeGraph
    ) -> list[ImpactMatch]:
        symbols = graph.symbol_map()
        propagated: list[ImpactMatch] = []
        for depth, caller, edge, chain in propagation_paths(
            graph, anchor, max_depth=self.max_impact_depth
        ):
            trace = list(direct.trace)
            for item in chain:
                trace_symbol = symbols.get(item.caller_symbol_id)
                trace.append(
                    ImpactTraceStep(
                        file_path=item.file_path,
                        symbol=trace_symbol.qualified_name if trace_symbol else None,
                        relation=ImpactTraceRelation.CALLS,
                        line=item.line,
                        column=item.column,
                        evidence=item.evidence,
                    )
                )
            propagated.append(
                ImpactMatch(
                    file_path=caller.file_path,
                    line=edge.line,
                    column=edge.column,
                    match_kind=MatchKind.WRAPPER if depth == 1 else MatchKind.TRANSITIVE_CALL,
                    confidence=MatchConfidence.MEDIUM,
                    evidence=edge.evidence,
                    symbol=caller.qualified_name,
                    language=caller.language,
                    impact_depth=depth,
                    analysis_kind=(
                        ImpactAnalysisKind.WRAPPER if depth == 1 else ImpactAnalysisKind.TRANSITIVE
                    ),
                    trace=trace,
                )
            )
        return propagated


def _parse_documents(repository: RepositoryScan) -> list[ParsedConsumerDocument]:
    maximum = getattr(settings, "max_graphql_query_documents", 500)
    results: list[ParsedConsumerDocument] = []
    for source in repository.files:
        suffix = PurePosixPath(source.path).suffix.lower()
        candidates: list[tuple[str, int]] = []
        if suffix in {".graphql", ".gql"}:
            candidates.append((source.content, 0))
        elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
            candidates.extend(
                (match.group("body"), match.start("body"))
                for match in _TAGGED_DOCUMENT.finditer(source.content)
            )
        elif suffix == ".py":
            candidates.extend(
                (match.group("body"), match.start("body"))
                for match in _PYTHON_DOCUMENT.finditer(source.content)
                if _GRAPHQL_START.search(match.group("body"))
            )
        for body, start in candidates:
            try:
                document = parse(body, no_location=False)
            except GraphQLError:
                continue
            results.append(ParsedConsumerDocument(source, document, body, start))
            if len(results) >= maximum:
                return results
    return results


def _relevant_fields(change: ApiChange, document: DocumentNode) -> list[FieldNode]:
    identifier = change.operation_identifier or ""
    parent, _, target = identifier.partition(".")
    fragments = {
        definition.name.value: definition
        for definition in document.definitions
        if isinstance(definition, FragmentDefinitionNode)
    }
    results: list[FieldNode] = []
    for definition in document.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        root = definition.operation.value.title()
        for field, depth in _fields(definition.selection_set, fragments):
            if depth == 0 and root == parent and field.name.value == target:
                if _field_matches_change(change, field):
                    results.append(field)
            elif (
                change.operation_kind
                in {
                    OperationKind.OBJECT_FIELD,
                    OperationKind.INTERFACE_FIELD,
                }
                and field.name.value == target
            ):
                results.append(field)
    return results


def _fields(
    selection_set: SelectionSetNode,
    fragments: dict[str, FragmentDefinitionNode],
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
):
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            yield selection, depth
            if selection.selection_set:
                yield from _fields(selection.selection_set, fragments, depth + 1, seen)
        elif isinstance(selection, InlineFragmentNode):
            yield from _fields(selection.selection_set, fragments, depth, seen)
        elif isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            if name not in seen and name in fragments:
                yield from _fields(fragments[name].selection_set, fragments, depth, seen | {name})


def _field_matches_change(change: ApiChange, field: FieldNode) -> bool:
    arguments = {argument.name.value for argument in field.arguments}
    if change.change_type in {ChangeType.ARGUMENT_REMOVED, ChangeType.ENUM_VALUE_REMOVED}:
        return bool(change.subject and change.subject in arguments)
    if change.change_type in {
        ChangeType.REQUIRED_ARGUMENT_ADDED,
        ChangeType.ARGUMENT_ADDED,
        ChangeType.GRAPHQL_INPUT_TYPE_CHANGED,
        ChangeType.NULLABILITY_TIGHTENED,
        ChangeType.NULLABILITY_RELAXED,
    }:
        return True
    return True


def _containing_symbol(graph: RepositoryCodeGraph, path: str, offset: int) -> CodeSymbol | None:
    candidates = [
        symbol
        for symbol in graph.symbols
        if symbol.file_path == path and symbol.start_offset <= offset <= symbol.end_offset
    ]
    return min(candidates, key=lambda item: item.end_offset - item.start_offset, default=None)


def _line_column(content: str, offset: int) -> tuple[int, int]:
    bounded = max(0, min(offset, len(content)))
    line = content.count("\n", 0, bounded) + 1
    last_newline = content.rfind("\n", 0, bounded)
    return line, bounded - last_newline


def _evidence(content: str, line: int) -> str:
    lines = content.splitlines()
    if not lines:
        return "GraphQL document"
    return " ".join(lines[min(line - 1, len(lines) - 1)].strip().split())[:240]


def _language(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".graphql": "graphql",
        ".gql": "graphql",
    }.get(suffix, "text")


def _lexical_fallback(
    change: ApiChange, repository: RepositoryScan, existing: list[ImpactMatch]
) -> list[ImpactMatch]:
    occupied = {(item.file_path, item.line) for item in existing}
    terms = [
        term
        for term in (change.subject, (change.operation_identifier or "").split(".")[-1])
        if term
    ]
    results: list[ImpactMatch] = []
    for source in repository.files:
        for line_index, line in enumerate(source.content.splitlines(), start=1):
            if (source.path, line_index) in occupied:
                continue
            term = next(
                (value for value in terms if re.search(rf"\b{re.escape(value)}\b", line)), None
            )
            if not term:
                continue
            results.append(
                ImpactMatch(
                    file_path=source.path,
                    line=line_index,
                    column=line.find(term) + 1,
                    match_kind=MatchKind.GRAPHQL_LEXICAL,
                    confidence=MatchConfidence.LOW,
                    evidence=" ".join(line.strip().split())[:240],
                    language=_language(source.path),
                )
            )
    return results[:100]


def _deduplicate(matches: list[ImpactMatch]) -> list[ImpactMatch]:
    result: dict[tuple[str, int, int, str | None], ImpactMatch] = {}
    confidence = {MatchConfidence.HIGH: 3, MatchConfidence.MEDIUM: 2, MatchConfidence.LOW: 1}
    for match in matches:
        key = (match.file_path, match.line, match.impact_depth, match.symbol)
        current = result.get(key)
        if current is None or confidence[match.confidence] > confidence[current.confidence]:
            result[key] = match
    return sorted(
        result.values(),
        key=lambda item: (item.impact_depth, item.file_path, item.line, item.column),
    )
