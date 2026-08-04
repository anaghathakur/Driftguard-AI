"""Deterministically associate contract changes with repository API usage."""

from __future__ import annotations

import re
from collections.abc import Iterable

from apps.api.app.domain.openapi import NormalizedContract
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactMatch,
    MatchConfidence,
    MatchKind,
)

MAX_MATCHES_PER_CHANGE = 100
METHOD_CONTEXT_LINES = 2


class ApiImpactMatcher:
    def match(
        self,
        changes: Iterable[ApiChange],
        repository: RepositoryScan,
        old_contract: NormalizedContract,
        new_contract: NormalizedContract,
    ) -> list[ChangeImpact]:
        impacts: list[ChangeImpact] = []
        for change in changes:
            operation_ids = _operation_ids(change, old_contract, new_contract)
            matches: list[ImpactMatch] = []
            for source_file in repository.files:
                matches.extend(self._match_file(change, operation_ids, source_file))
                if len(matches) >= MAX_MATCHES_PER_CHANGE:
                    break
            impacts.append(
                ChangeImpact(
                    change_id=change.change_id,
                    path=change.path,
                    method=change.method,
                    matches=matches[:MAX_MATCHES_PER_CHANGE],
                )
            )
        return impacts

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
        if (operation := contract.operations.get(key)) is not None
        and operation.operation_id
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
