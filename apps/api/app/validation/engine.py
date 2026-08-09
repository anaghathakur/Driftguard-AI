"""Deterministic contract, dependency, scope, and related-test validation."""

from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.repository.code_analyzer import CodeSymbol, RepositoryCodeGraph
from apps.api.app.schemas.analysis import PersistedMatchResponse
from apps.api.app.schemas.comparison import ApiChange, ChangeType
from apps.api.app.schemas.patch import PatchProposal
from apps.api.app.schemas.validation import (
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    RelatedTest,
    TestGap,
    TestRelevance,
    ValidationFinding,
)

_TEST_PATTERNS = (
    re.compile(r"(?:^|/)tests?/", re.IGNORECASE),
    re.compile(r"(?:^|/)__tests__/", re.IGNORECASE),
    re.compile(r"(?:^|/)test_[^/]+\.py$", re.IGNORECASE),
    re.compile(r"(?:^|/)[^/]+_test\.py$", re.IGNORECASE),
    re.compile(r"\.(?:test|spec)\.(?:js|jsx|ts|tsx)$", re.IGNORECASE),
)


def patched_repository(scan: RepositoryScan, modified: dict[str, str]) -> RepositoryScan:
    """Return a source-only in-memory view; never write repository files."""

    files = tuple(
        ScannedSourceFile(
            path=item.path,
            content=modified.get(item.path, item.content),
            size_bytes=len(modified.get(item.path, item.content).encode("utf-8")),
        )
        for item in scan.files
    )
    return RepositoryScan(
        archive_sha256=scan.archive_sha256,
        archive_entries=scan.archive_entries,
        files=files,
        skipped_files=scan.skipped_files,
        skipped_reasons=scan.skipped_reasons,
    )


def validate_contract(
    changes: list[ApiChange],
    graph: RepositoryCodeGraph,
    scan: RepositoryScan,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    files = {item.path: item.content for item in scan.files}
    operations = sorted({(change.path, change.method.upper()) for change in changes})
    for path, method in operations:
        anchors = [
            anchor for anchor in graph.anchors if anchor.path == path and anchor.method == method
        ]
        operation_changes = [
            change for change in changes if change.path == path and change.method.upper() == method
        ]
        should_exist = not all(
            change.change_type in {ChangeType.ENDPOINT_REMOVED, ChangeType.HTTP_METHOD_REMOVED}
            for change in operation_changes
        )
        if should_exist:
            findings.append(
                _finding(
                    f"endpoint:{method}:{path}",
                    FindingCategory.ENDPOINT_METHOD,
                    FindingStatus.PASS if anchors else FindingStatus.FAIL,
                    FindingSeverity.INFO if anchors else FindingSeverity.HIGH,
                    (
                        f"{method} {path} is preserved in the patched source."
                        if anchors
                        else (
                            f"No statically resolved {method} {path} usage remains "
                            "in the patched source."
                        )
                    ),
                    change_id=operation_changes[0].change_id if operation_changes else None,
                    file_path=anchors[0].file_path if anchors else None,
                    line=anchors[0].line if anchors else None,
                    column=anchors[0].column if anchors else None,
                    evidence=anchors[0].evidence if anchors else None,
                )
            )
        for change in operation_changes:
            if (
                change.change_type
                not in {
                    ChangeType.REQUIRED_REQUEST_FIELD_ADDED,
                    ChangeType.REQUEST_FIELD_REMOVED,
                }
                or not change.subject
            ):
                continue
            if not anchors:
                continue
            for index, anchor in enumerate(anchors):
                keys = _request_payload_keys(
                    files.get(anchor.file_path, ""), anchor.line, anchor.language
                )
                present = keys is not None and change.subject in keys
                required = change.change_type == ChangeType.REQUIRED_REQUEST_FIELD_ADDED
                if keys is None:
                    status = FindingStatus.UNKNOWN
                    severity = FindingSeverity.MEDIUM
                    message = (
                        f"The {method} {path} payload is dynamic; presence of required field "
                        f"'{change.subject}' could not be resolved statically."
                        if required
                        else f"The {method} {path} payload is dynamic; removal of field "
                        f"'{change.subject}' could not be resolved statically."
                    )
                elif required:
                    status = FindingStatus.PASS if present else FindingStatus.FAIL
                    severity = FindingSeverity.INFO if present else FindingSeverity.HIGH
                    message = (
                        f"{change.subject} is present in the {method} {path} request payload."
                        if present
                        else (
                            f"Required field '{change.subject}' is missing from the "
                            f"{method} {path} request payload."
                        )
                    )
                else:
                    status = FindingStatus.FAIL if present else FindingStatus.PASS
                    severity = FindingSeverity.HIGH if present else FindingSeverity.INFO
                    message = (
                        f"Removed field '{change.subject}' is still sent in the "
                        f"{method} {path} request payload."
                        if present
                        else f"{change.subject} is absent from the {method} {path} request payload."
                    )
                findings.append(
                    _finding(
                        f"field:{change.change_id}:{index}",
                        (
                            FindingCategory.REQUIRED_REQUEST_FIELD
                            if required
                            else FindingCategory.REMOVED_REQUEST_FIELD
                        ),
                        status,
                        severity,
                        message,
                        change_id=change.change_id,
                        file_path=anchor.file_path,
                        line=anchor.line,
                        column=anchor.column,
                        evidence=anchor.evidence,
                    )
                )
    return findings


def validate_dependencies(
    changes: list[ApiChange],
    original: RepositoryScan,
    patched: RepositoryScan,
    original_graph: RepositoryCodeGraph,
    patched_graph: RepositoryCodeGraph,
    proposal: PatchProposal,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    original_files = {item.path: item.content for item in original.files}
    patched_files = {item.path: item.content for item in patched.files}
    old_fields = {
        change.subject
        for change in changes
        if change.change_type == ChangeType.REQUEST_FIELD_REMOVED and change.subject
    }
    new_fields = {
        change.subject
        for change in changes
        if change.change_type == ChangeType.REQUIRED_REQUEST_FIELD_ADDED and change.subject
    }
    symbols = patched_graph.symbol_map()
    callers = patched_graph.callers()
    original_symbols = original_graph.symbol_map()
    for patch_file in proposal.files:
        candidates = [
            symbol
            for symbol in patched_graph.symbols
            if symbol.file_path == patch_file.file_path
            and (
                not patch_file.related_symbol
                or symbol.qualified_name == patch_file.related_symbol
                or symbol.qualified_name.endswith(f".{patch_file.related_symbol}")
                or patch_file.related_symbol.endswith(f".{symbol.name}")
            )
        ]
        for target in candidates[:5]:
            old_target = next(
                (
                    item
                    for item in original_symbols.values()
                    if item.file_path == target.file_path
                    and item.qualified_name == target.qualified_name
                ),
                None,
            )
            old_signature = _signature(original_files.get(target.file_path, ""), old_target)
            new_signature = _signature(patched_files.get(target.file_path, ""), target)
            if not new_signature or old_signature == new_signature:
                continue
            for edge in callers.get(target.symbol_id, ()):
                caller = symbols.get(edge.caller_symbol_id)
                if caller is None:
                    continue
                call = _call_details(
                    patched_files.get(edge.file_path, ""), edge.line, target.name, target.language
                )
                if call is None:
                    findings.append(
                        _finding(
                            f"caller:unknown:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.CALLER_SIGNATURE,
                            FindingStatus.UNKNOWN,
                            FindingSeverity.MEDIUM,
                            f"Caller {caller.qualified_name} resolves to the modified "
                            "symbol, but its arguments could not be inspected safely.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=edge.evidence,
                        )
                    )
                    continue
                parameters, required_parameters, variadic = _parameter_details(
                    new_signature, target.language
                )
                args, keywords = call
                old_keywords = sorted(old_fields.intersection(keywords))
                if old_keywords:
                    findings.append(
                        _finding(
                            f"caller:keyword:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.CALLER_SIGNATURE,
                            FindingStatus.FAIL,
                            FindingSeverity.HIGH,
                            f"{caller.qualified_name} still supplies removed keyword "
                            f"argument '{old_keywords[0]}'.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=edge.evidence,
                        )
                    )
                    continue
                unexpected_keywords = sorted(keywords - set(parameters))
                if unexpected_keywords:
                    findings.append(
                        _finding(
                            f"caller:keyword:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.CALLER_SIGNATURE,
                            FindingStatus.FAIL,
                            FindingSeverity.HIGH,
                            f"{caller.qualified_name} supplies unsupported keyword "
                            f"argument '{unexpected_keywords[0]}'.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=edge.evidence,
                        )
                    )
                    continue
                positionally_provided = set(parameters[: len(args)])
                missing_parameters = sorted(required_parameters - positionally_provided - keywords)
                if missing_parameters:
                    findings.append(
                        _finding(
                            f"caller:missing:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.CALLER_SIGNATURE,
                            FindingStatus.FAIL,
                            FindingSeverity.HIGH,
                            f"{caller.qualified_name} does not supply required parameter "
                            f"'{missing_parameters[0]}' for {target.qualified_name}.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=edge.evidence,
                        )
                    )
                    continue
                if not variadic and len(args) > len(parameters):
                    findings.append(
                        _finding(
                            f"caller:many:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.CALLER_SIGNATURE,
                            FindingStatus.FAIL,
                            FindingSeverity.HIGH,
                            f"{caller.qualified_name} supplies too many positional arguments "
                            f"for modified symbol {target.qualified_name}.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=edge.evidence,
                        )
                    )
                    continue
                stale = _stale_argument(parameters, args, old_fields, new_fields)
                if stale:
                    old_name, new_name, expression = stale
                    findings.append(
                        _finding(
                            f"caller:stale:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.STALE_VALUE,
                            FindingStatus.WARNING,
                            FindingSeverity.HIGH,
                            f"{caller.qualified_name} still passes a value derived from "
                            f"removed field '{old_name}' into parameter '{new_name}'.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=expression,
                        )
                    )
                else:
                    findings.append(
                        _finding(
                            f"caller:compatible:{edge.caller_symbol_id}:{edge.line}",
                            FindingCategory.CALLER_SIGNATURE,
                            FindingStatus.PASS,
                            FindingSeverity.INFO,
                            f"Resolved caller {caller.qualified_name} is positionally "
                            f"compatible with {target.qualified_name}.",
                            file_path=edge.file_path,
                            symbol=caller.qualified_name,
                            line=edge.line,
                            column=edge.column,
                            evidence=edge.evidence,
                        )
                    )
    return _unique_findings(findings)


def validate_blast_radius(
    proposal: PatchProposal,
    matches: list[PersistedMatchResponse],
) -> tuple[list[ValidationFinding], list[str], list[str], list[str]]:
    modified = sorted({item.file_path for item in proposal.files})
    direct = sorted({item.file_path for item in matches if item.impact_depth == 0})
    transitive = sorted({item.file_path for item in matches if item.impact_depth > 0})
    unrelated = sorted(set(modified) - set(direct) - set(transitive))
    finding = _finding(
        "patch:blast-radius",
        FindingCategory.PATCH_SCOPE,
        FindingStatus.FAIL if unrelated else FindingStatus.PASS,
        FindingSeverity.HIGH if unrelated else FindingSeverity.INFO,
        (
            f"Patch modifies unrelated file(s): {', '.join(unrelated)}."
            if unrelated
            else "Every modified file belongs to the statically identified impact radius."
        ),
    )
    return [finding], direct, transitive, unrelated


def discover_related_tests(
    scan: RepositoryScan,
    changes: list[ApiChange],
    matches: list[PersistedMatchResponse],
    *,
    maximum: int,
) -> list[RelatedTest]:
    direct_symbols = {item.symbol for item in matches if item.impact_depth == 0 and item.symbol}
    transitive_symbols = {item.symbol for item in matches if item.impact_depth > 0 and item.symbol}
    all_paths = {change.path for change in changes}
    fields = {change.subject for change in changes if change.subject}
    change_ids = [change.change_id for change in changes]
    candidates: list[RelatedTest] = []
    for source in scan.files:
        if not any(pattern.search(source.path) for pattern in _TEST_PATTERNS):
            continue
        reasons: list[str] = []
        related_symbols: set[str] = set()
        lines: set[int] = set()
        for symbol in sorted(direct_symbols):
            if _references_symbol(source.content, symbol):
                reasons.append(f"References direct impacted symbol {symbol}.")
                related_symbols.add(symbol)
                lines.update(_reference_lines(source.content, symbol.split(".")[-1]))
        endpoint_hits = sorted(path for path in all_paths if path in source.content)
        if endpoint_hits:
            reasons.append(f"References changed endpoint {endpoint_hits[0]}.")
            lines.update(_reference_lines(source.content, endpoint_hits[0]))
        field_hits = sorted(field for field in fields if _word_in(field, source.content))
        if field_hits:
            reasons.append(f"References changed request field {field_hits[0]}.")
            lines.update(_reference_lines(source.content, field_hits[0]))
        direct = bool(related_symbols or endpoint_hits or field_hits)
        for symbol in sorted(transitive_symbols):
            if _references_symbol(source.content, symbol):
                reasons.append(f"References impacted caller {symbol}.")
                related_symbols.add(symbol)
                lines.update(_reference_lines(source.content, symbol.split(".")[-1]))
        if direct:
            relevance = TestRelevance.HIGH
        elif related_symbols:
            relevance = TestRelevance.MEDIUM
        elif _nearby_test(source.path, matches):
            relevance = TestRelevance.LOW
            reasons.append("Test filename or feature directory resembles an impacted module.")
        else:
            continue
        candidates.append(
            RelatedTest(
                file_path=source.path,
                language=_language(source.path),
                relevance=relevance,
                reasons=list(dict.fromkeys(reasons))[:8],
                related_symbols=sorted(related_symbols)[:20],
                related_changes=change_ids[:20],
                lines=sorted(lines)[:20],
            )
        )
    order = {TestRelevance.HIGH: 0, TestRelevance.MEDIUM: 1, TestRelevance.LOW: 2}
    return sorted(candidates, key=lambda item: (order[item.relevance], item.file_path))[:maximum]


def find_test_gaps(
    matches: list[PersistedMatchResponse], related_tests: list[RelatedTest], *, maximum: int
) -> list[TestGap]:
    discovered = {symbol for test in related_tests for symbol in test.related_symbols}
    unique: dict[tuple[str, str, int], PersistedMatchResponse] = {}
    for match in matches:
        if not match.symbol:
            continue
        key = (match.symbol, match.file_path, match.impact_depth)
        unique.setdefault(key, match)
    gaps: list[TestGap] = []
    for (symbol, path, depth), _match in sorted(unique.items(), key=lambda item: item[0][2]):
        if symbol in discovered:
            continue
        label = "Direct API integration" if depth == 0 else "Impacted caller"
        gaps.append(
            TestGap(
                gap_id=f"test-gap:{len(gaps) + 1}",
                message=f"{label} {symbol} has no statically discovered related test.",
                symbol=symbol,
                file_path=path,
                impact_depth=depth,
            )
        )
        if len(gaps) >= maximum:
            break
    return gaps


def _request_payload_keys(content: str, line: int, language: str) -> set[str] | None:
    if language == "python":
        return _python_payload_keys(content, line)
    return _javascript_payload_keys(content, line)


def _python_payload_keys(content: str, line: int) -> set[str] | None:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return None
    assignments: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            value = node.value
            if isinstance(target, ast.Name) and value is not None:
                assignments[target.id] = value
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and node.lineno == line]
    for call in calls:
        values = [keyword.value for keyword in call.keywords if keyword.arg in {"json", "data"}]
        if not values and len(call.args) > 1:
            values.append(call.args[1])
        for value in values:
            if isinstance(value, ast.Name):
                value = assignments.get(value.id, value)
            if isinstance(value, ast.Dict):
                keys: set[str] = set()
                for key in value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
                    else:
                        return None
                return keys
            return None
    return None


def _javascript_payload_keys(content: str, line: int) -> set[str] | None:
    lines = content.splitlines()
    start = max(0, line - 30)
    end = min(len(lines), line + 20)
    window = "\n".join(lines[start:end])
    matches = list(re.finditer(r"(?:payload|body)\s*=\s*\{(?P<body>[^{}]{0,4000})\}", window, re.S))
    if not matches:
        matches = list(
            re.finditer(r"JSON\.stringify\s*\(\s*\{(?P<body>[^{}]{0,4000})\}", window, re.S)
        )
    if not matches:
        return None
    body = matches[-1].group("body")
    if "..." in body or "[" in body:
        return None
    return {
        match.group("key") or match.group("quoted")
        for match in re.finditer(
            r"(?:['\"](?P<quoted>[A-Za-z_$][\w$]*)['\"]|"
            r"(?P<key>[A-Za-z_$][\w$]*))\s*:",
            body,
        )
    }


def _signature(content: str, symbol: CodeSymbol | None) -> str | None:
    if symbol is None:
        return None
    lines = content.splitlines()
    if not (1 <= symbol.line <= len(lines)):
        return None
    return lines[symbol.line - 1].strip()


def _parameter_details(signature: str, language: str) -> tuple[list[str], set[str], bool]:
    match = re.search(r"\((?P<params>[^)]*)\)", signature)
    if not match:
        return [], set(), False
    result: list[str] = []
    required: set[str] = set()
    variadic = False
    for item in match.group("params").split(","):
        raw = item.strip()
        if not raw:
            continue
        if raw.startswith(("*", "...")):
            variadic = True
        name = raw.split(":", 1)[0].split("=", 1)[0].strip()
        name = name.removeprefix("...")
        name = name.lstrip("*")
        if name and not (language == "python" and name in {"self", "cls"}):
            result.append(name)
            if "=" not in raw and not raw.startswith(("*", "...")):
                required.add(name)
    return result, required, variadic


def _call_details(
    content: str, line: int, name: str, language: str
) -> tuple[list[str], set[str]] | None:
    if language == "python":
        try:
            tree = ast.parse(content)
        except (SyntaxError, ValueError):
            return None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.lineno != line:
                continue
            called = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            )
            if called != name:
                continue
            args = [ast.get_source_segment(content, arg) or "" for arg in node.args]
            return args, {item.arg for item in node.keywords if item.arg}
        return None
    lines = content.splitlines()
    if not 1 <= line <= len(lines):
        return None
    window = " ".join(lines[line - 1 : min(len(lines), line + 5)])
    match = re.search(rf"\b{re.escape(name)}\s*\((?P<args>[^)]*)\)", window)
    if not match:
        return None
    args = _split_arguments(match.group("args"))
    return args, set()


def _split_arguments(value: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in value:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
        elif char in "([{":
            depth += 1
            current.append(char)
        elif char in ")]}":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            if "".join(current).strip():
                result.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if "".join(current).strip():
        result.append("".join(current).strip())
    return result


def _stale_argument(
    parameters: list[str], args: list[str], old_fields: set[str], new_fields: set[str]
) -> tuple[str, str, str] | None:
    normalized_new = {_normalize(name): name for name in new_fields}
    for index, parameter in enumerate(parameters):
        new_name = normalized_new.get(_normalize(parameter))
        if new_name is None or index >= len(args):
            continue
        expression = args[index]
        for old_name in sorted(old_fields):
            if _word_in(old_name, expression):
                return old_name, parameter, expression[:240]
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _word_in(value: str, content: str) -> bool:
    parts = value.split("_")
    alternatives = {value, parts[0] + "".join(part.title() for part in parts[1:])}
    return any(
        re.search(rf"(?<![A-Za-z0-9_$]){re.escape(item)}(?![A-Za-z0-9_$])", content)
        for item in alternatives
    )


def _references_symbol(content: str, symbol: str) -> bool:
    return _word_in(symbol.split(".")[-1], content) or symbol in content


def _reference_lines(content: str, value: str) -> set[int]:
    return {index for index, line in enumerate(content.splitlines(), 1) if value in line}


def _nearby_test(path: str, matches: list[PersistedMatchResponse]) -> bool:
    stem = PurePosixPath(path).stem.lower().replace("test_", "").replace("_test", "")
    return any(stem and stem in PurePosixPath(match.file_path).stem.lower() for match in matches)


def _language(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx"}:
        return "javascript"
    return suffix.lstrip(".") or "unknown"


def _finding(
    check_id: str,
    category: FindingCategory,
    status: FindingStatus,
    severity: FindingSeverity,
    message: str,
    **details: object,
) -> ValidationFinding:
    return ValidationFinding(
        check_id=check_id[:120],
        category=category,
        status=status,
        severity=severity,
        message=message[:500],
        **details,
    )


def _unique_findings(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    by_id: dict[str, ValidationFinding] = {}
    for finding in findings:
        by_id.setdefault(finding.check_id, finding)
    return [by_id[key] for key in sorted(by_id)]
