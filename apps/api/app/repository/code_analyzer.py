"""Bounded, deterministic static code analysis for repository impact graphs."""

from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.schemas.impact import CodeAnalysisSummary

_PYTHON_EXTENSIONS = frozenset({".py"})
_JAVASCRIPT_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_HTTP_RECEIVER_HINTS = (
    "api",
    "axios",
    "client",
    "http",
    "httpx",
    "request",
    "requests",
    "session",
)
_JS_CALL_PATTERN = re.compile(
    r"(?P<callee>[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s*\("
)
_JS_FUNCTION_PATTERN = re.compile(
    r"(?:\bexport\s+)?(?:\basync\s+)?\bfunction\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"
)
_JS_ARROW_PATTERN = re.compile(
    r"(?:\bexport\s+)?(?:\bconst|\blet|\bvar)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
    r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"
)
_JS_CONSTANT_PATTERN = re.compile(
    r"(?:^|[;{}]\s*|\n\s*)(?:const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<value>[^;\n]+)",
    re.MULTILINE,
)
_JS_NAMED_IMPORT_PATTERN = re.compile(
    r"\bimport\s*\{(?P<names>[^}]+)\}\s*from\s*"
    r"[\"'](?P<module>[^\"']+)[\"']"
)
_JS_NAMESPACE_IMPORT_PATTERN = re.compile(
    r"\bimport\s*\*\s*as\s*(?P<alias>[A-Za-z_$][\w$]*)\s*"
    r"from\s*[\"'](?P<module>[^\"']+)[\"']"
)
_JS_DEFAULT_IMPORT_PATTERN = re.compile(
    r"\bimport\s+(?P<alias>[A-Za-z_$][\w$]*)\s+from\s*"
    r"[\"'](?P<module>[^\"']+)[\"']"
)
_JS_IGNORED_CALLS = frozenset(
    {
        "catch",
        "for",
        "function",
        "if",
        "new",
        "return",
        "switch",
        "typeof",
        "while",
    }
)


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    symbol_id: str
    language: str
    file_path: str
    module_name: str
    name: str
    qualified_name: str
    container: str | None
    line: int
    column: int
    start_offset: int = 0
    end_offset: int = 0


@dataclass(frozen=True, slots=True)
class ImportBinding:
    module_name: str
    imported_name: str | None
    namespace: bool


@dataclass(frozen=True, slots=True)
class UnresolvedCall:
    caller_symbol_id: str
    callee_parts: tuple[str, ...]
    file_path: str
    line: int
    column: int
    evidence: str


@dataclass(frozen=True, slots=True)
class CodeCallEdge:
    caller_symbol_id: str
    callee_symbol_id: str
    file_path: str
    line: int
    column: int
    evidence: str


@dataclass(frozen=True, slots=True)
class ApiUsageAnchor:
    symbol_id: str | None
    language: str
    file_path: str
    method: str
    path: str
    line: int
    column: int
    evidence: str


@dataclass(frozen=True, slots=True)
class SourceAnalysis:
    file_path: str
    language: str
    module_name: str
    symbols: tuple[CodeSymbol, ...]
    imports: dict[str, ImportBinding]
    calls: tuple[UnresolvedCall, ...]
    anchors: tuple[ApiUsageAnchor, ...]
    parser_failed: bool = False


@dataclass(frozen=True, slots=True)
class RepositoryCodeGraph:
    symbols: tuple[CodeSymbol, ...]
    edges: tuple[CodeCallEdge, ...]
    anchors: tuple[ApiUsageAnchor, ...]
    summary: CodeAnalysisSummary

    def symbol_map(self) -> dict[str, CodeSymbol]:
        return {symbol.symbol_id: symbol for symbol in self.symbols}

    def callers(self) -> dict[str, tuple[CodeCallEdge, ...]]:
        by_callee: dict[str, list[CodeCallEdge]] = defaultdict(list)
        for edge in self.edges:
            by_callee[edge.callee_symbol_id].append(edge)
        return {
            key: tuple(
                sorted(
                    values,
                    key=lambda edge: (
                        edge.file_path,
                        edge.line,
                        edge.column,
                        edge.caller_symbol_id,
                    ),
                )
            )
            for key, values in by_callee.items()
        }


class RepositoryCodeAnalyzer:
    """Parse supported files as data and build a bounded local call graph."""

    def __init__(
        self,
        *,
        max_symbols: int = settings.max_code_symbols,
        max_edges: int = settings.max_code_graph_edges,
        max_impact_depth: int = settings.max_impact_depth,
    ) -> None:
        self.max_symbols = max_symbols
        self.max_edges = max_edges
        self.max_impact_depth = max_impact_depth

    def analyze(self, repository: RepositoryScan) -> RepositoryCodeGraph:
        analyses: list[SourceAnalysis] = []
        parser_failure_files: list[str] = []
        for source_file in repository.files:
            suffix = PurePosixPath(source_file.path).suffix.lower()
            if suffix in _PYTHON_EXTENSIONS:
                analysis = _analyze_python(source_file)
            elif suffix in _JAVASCRIPT_EXTENSIONS:
                analysis = _analyze_javascript(source_file)
            else:
                continue
            analyses.append(analysis)
            if analysis.parser_failed:
                parser_failure_files.append(source_file.path)

        symbols = tuple(
            sorted(
                (symbol for analysis in analyses for symbol in analysis.symbols),
                key=_symbol_sort_key,
            )
        )
        if len(symbols) > self.max_symbols:
            _code_limit_error("symbols", self.max_symbols)

        edges = _resolve_calls(analyses, symbols)
        if len(edges) > self.max_edges:
            _code_limit_error("graph_edges", self.max_edges)

        anchors = tuple(
            sorted(
                (anchor for analysis in analyses for anchor in analysis.anchors),
                key=lambda item: (
                    item.file_path,
                    item.line,
                    item.column,
                    item.method,
                    item.path,
                ),
            )
        )
        if len(anchors) > self.max_edges:
            _code_limit_error("api_anchors", self.max_edges)

        return RepositoryCodeGraph(
            symbols=symbols,
            edges=edges,
            anchors=anchors,
            summary=CodeAnalysisSummary(
                supported_files=len(analyses),
                parser_failures=len(parser_failure_files),
                parser_failure_files=parser_failure_files[:20],
                symbols_discovered=len(symbols),
                call_edges_resolved=len(edges),
                direct_api_anchors=len(anchors),
                max_impact_depth=self.max_impact_depth,
            ),
        )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(
        self,
        source_file: ScannedSourceFile,
        module_name: str,
        module_constants: dict[str, str],
        imports: dict[str, ImportBinding],
    ) -> None:
        self.source_file = source_file
        self.module_name = module_name
        self.module_constants = module_constants
        self.imports = imports
        self.lines = source_file.content.splitlines()
        self.symbols: list[CodeSymbol] = []
        self.calls: list[UnresolvedCall] = []
        self.anchors: list[ApiUsageAnchor] = []
        self._scope: list[str] = []
        self._symbol_stack: list[CodeSymbol] = []
        self._environment_stack: list[dict[str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        names = [*self._scope, node.name]
        local_name = ".".join(names)
        symbol = CodeSymbol(
            symbol_id=_symbol_id("python", self.source_file.path, local_name, node.lineno),
            language="python",
            file_path=self.source_file.path,
            module_name=self.module_name,
            name=node.name,
            qualified_name=f"{self.module_name}.{local_name}",
            container=".".join(self._scope) or None,
            line=node.lineno,
            column=node.col_offset + 1,
        )
        self.symbols.append(symbol)
        environment = _python_constants(node.body, self.module_constants)
        self._scope.append(node.name)
        self._symbol_stack.append(symbol)
        self._environment_stack.append(environment)
        for statement in node.body:
            self.visit(statement)
        self._environment_stack.pop()
        self._symbol_stack.pop()
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        parts = _python_call_parts(node.func)
        current = self._symbol_stack[-1] if self._symbol_stack else None
        environment = (
            self._environment_stack[-1]
            if self._environment_stack
            else self.module_constants
        )
        anchor = _python_http_anchor(
            node,
            parts,
            environment,
            self.source_file.path,
            current,
            self.lines,
        )
        if anchor is not None:
            self.anchors.append(anchor)
        elif current is not None and parts:
            self.calls.append(
                UnresolvedCall(
                    caller_symbol_id=current.symbol_id,
                    callee_parts=parts,
                    file_path=self.source_file.path,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    evidence=_line_evidence(self.lines, node.lineno),
                )
            )
        self.generic_visit(node)


def _analyze_python(source_file: ScannedSourceFile) -> SourceAnalysis:
    module_name = _python_module_name(source_file.path)
    try:
        tree = ast.parse(source_file.content, filename=source_file.path)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return SourceAnalysis(
            file_path=source_file.path,
            language="python",
            module_name=module_name,
            symbols=(),
            imports={},
            calls=(),
            anchors=(),
            parser_failed=True,
        )

    imports = _python_imports(tree)
    constants = _python_constants(tree.body, {})
    visitor = _PythonVisitor(source_file, module_name, constants, imports)
    for statement in tree.body:
        visitor.visit(statement)
    return SourceAnalysis(
        file_path=source_file.path,
        language="python",
        module_name=module_name,
        symbols=tuple(sorted(visitor.symbols, key=_symbol_sort_key)),
        imports=imports,
        calls=tuple(
            sorted(visitor.calls, key=lambda item: (item.line, item.column, item.callee_parts))
        ),
        anchors=tuple(
            sorted(visitor.anchors, key=lambda item: (item.line, item.column, item.method))
        ),
    )


def _python_imports(tree: ast.Module) -> dict[str, ImportBinding]:
    imports: dict[str, ImportBinding] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports[alias.asname or alias.name] = ImportBinding(
                    module_name=node.module,
                    imported_name=alias.name,
                    namespace=False,
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                imports[local_name] = ImportBinding(
                    module_name=alias.name,
                    imported_name=None,
                    namespace=True,
                )
    return imports


def _python_constants(
    statements: list[ast.stmt],
    inherited: dict[str, str],
) -> dict[str, str]:
    values = dict(inherited)
    for statement in statements:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        if isinstance(target, ast.Name) and value is not None:
            resolved = _resolve_python_string(value, values)
            if resolved is not None:
                values[target.id] = resolved
    return values


def _resolve_python_string(node: ast.AST, values: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return values.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_python_string(node.left, values)
        right = _resolve_python_string(node.right, values)
        if left is not None and right is not None:
            return left + right
        if right is not None and right.startswith("/"):
            return right
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str | None] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append(_resolve_python_string(value.value, values))
            else:
                parts.append(None)
        if all(part is not None for part in parts):
            return "".join(part or "" for part in parts)
        return _safe_unknown_prefix_suffix(parts)
    return None


def _python_call_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _python_call_parts(node.value)
        return (*parent, node.attr) if parent else (node.attr,)
    return ()


def _python_http_anchor(
    node: ast.Call,
    parts: tuple[str, ...],
    values: dict[str, str],
    file_path: str,
    symbol: CodeSymbol | None,
    lines: list[str],
) -> ApiUsageAnchor | None:
    if len(parts) < 2:
        return None
    receiver = ".".join(parts[:-1])
    method = parts[-1].lower()
    path_node: ast.AST | None = None
    if method in _HTTP_METHODS and _looks_like_http_receiver(receiver):
        path_node = node.args[0] if node.args else None
    elif method == "request" and _looks_like_http_receiver(receiver):
        if len(node.args) >= 2:
            resolved_method = _resolve_python_string(node.args[0], values)
            if resolved_method and resolved_method.lower() in _HTTP_METHODS:
                method = resolved_method.lower()
                path_node = node.args[1]
        for keyword in node.keywords:
            if keyword.arg == "method":
                resolved_method = _resolve_python_string(keyword.value, values)
                if resolved_method and resolved_method.lower() in _HTTP_METHODS:
                    method = resolved_method.lower()
            if keyword.arg in {"url", "path"}:
                path_node = keyword.value
    if path_node is None:
        return None
    resolved_path = _resolved_endpoint(_resolve_python_string(path_node, values))
    if resolved_path is None:
        return None
    return ApiUsageAnchor(
        symbol_id=symbol.symbol_id if symbol else None,
        language="python",
        file_path=file_path,
        method=method.upper(),
        path=resolved_path,
        line=node.lineno,
        column=node.col_offset + 1,
        evidence=_line_evidence(lines, node.lineno),
    )


def _analyze_javascript(source_file: ScannedSourceFile) -> SourceAnalysis:
    language = (
        "typescript"
        if PurePosixPath(source_file.path).suffix.lower() in {".ts", ".tsx"}
        else "javascript"
    )
    module_name = _javascript_module_name(source_file.path)
    try:
        masked = _mask_javascript(source_file.content)
        symbols = _javascript_symbols(source_file, language, module_name, masked)
        imports = _javascript_imports(source_file.path, source_file.content)
        calls, anchors = _javascript_calls(
            source_file,
            language,
            symbols,
            masked,
        )
    except (ValueError, MemoryError, RecursionError):
        return SourceAnalysis(
            file_path=source_file.path,
            language=language,
            module_name=module_name,
            symbols=(),
            imports={},
            calls=(),
            anchors=(),
            parser_failed=True,
        )
    return SourceAnalysis(
        file_path=source_file.path,
        language=language,
        module_name=module_name,
        symbols=tuple(symbols),
        imports=imports,
        calls=tuple(calls),
        anchors=tuple(anchors),
    )


def _javascript_symbols(
    source_file: ScannedSourceFile,
    language: str,
    module_name: str,
    masked: str,
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    occupied: set[tuple[int, str]] = set()
    for pattern in (_JS_FUNCTION_PATTERN, _JS_ARROW_PATTERN):
        for match in pattern.finditer(masked):
            name = match.group("name")
            open_brace = masked.find("{", match.start(), match.end())
            close_brace = _matching_brace(masked, open_brace)
            line, column = _line_column(source_file.content, match.start("name"))
            key = (match.start(), name)
            if key in occupied:
                continue
            occupied.add(key)
            symbols.append(
                CodeSymbol(
                    symbol_id=_symbol_id(language, source_file.path, name, line),
                    language=language,
                    file_path=source_file.path,
                    module_name=module_name,
                    name=name,
                    qualified_name=f"{module_name}.{name}",
                    container=None,
                    line=line,
                    column=column,
                    start_offset=match.start(),
                    end_offset=close_brace + 1,
                )
            )
    return sorted(symbols, key=_symbol_sort_key)


def _javascript_imports(file_path: str, content: str) -> dict[str, ImportBinding]:
    imports: dict[str, ImportBinding] = {}
    for match in _JS_NAMED_IMPORT_PATTERN.finditer(content):
        module_name = _javascript_import_module(file_path, match.group("module"))
        for item in match.group("names").split(","):
            parts = re.split(r"\s+as\s+", item.strip())
            if not parts or not re.fullmatch(r"[A-Za-z_$][\w$]*", parts[0]):
                continue
            imported_name = parts[0]
            local_name = parts[-1]
            imports[local_name] = ImportBinding(module_name, imported_name, False)
    for match in _JS_NAMESPACE_IMPORT_PATTERN.finditer(content):
        imports[match.group("alias")] = ImportBinding(
            _javascript_import_module(file_path, match.group("module")),
            None,
            True,
        )
    for match in _JS_DEFAULT_IMPORT_PATTERN.finditer(content):
        alias = match.group("alias")
        imports.setdefault(
            alias,
            ImportBinding(
                _javascript_import_module(file_path, match.group("module")),
                "default",
                False,
            ),
        )
    return imports


def _javascript_calls(
    source_file: ScannedSourceFile,
    language: str,
    symbols: list[CodeSymbol],
    masked: str,
) -> tuple[list[UnresolvedCall], list[ApiUsageAnchor]]:
    content = source_file.content
    lines = content.splitlines()
    module_constants = _javascript_constants(content, symbols, None)
    calls: list[UnresolvedCall] = []
    anchors: list[ApiUsageAnchor] = []
    for match in _JS_CALL_PATTERN.finditer(masked):
        callee = re.sub(r"\s+", "", match.group("callee"))
        parts = tuple(callee.split("."))
        if not parts or parts[0] in _JS_IGNORED_CALLS:
            continue
        if _is_javascript_declaration(masked, match.start()):
            continue
        symbol = _enclosing_javascript_symbol(symbols, match.start())
        environment = dict(module_constants)
        environment.update(_javascript_constants(content, symbols, symbol))
        arguments = _javascript_arguments(content, match.end() - 1)
        line, column = _line_column(content, match.start())
        evidence = _line_evidence(lines, line)
        method: str | None = None
        path_expression: str | None = None
        if callee == "fetch" and arguments:
            path_expression = arguments[0]
            options = arguments[1] if len(arguments) > 1 else ""
            method_match = re.search(
                r"(?:[\"']?method[\"']?)\s*:\s*[\"'](?P<method>[A-Za-z]+)[\"']",
                options,
                re.IGNORECASE,
            )
            method = method_match.group("method") if method_match else "GET"
        elif len(parts) >= 2 and parts[-1].lower() in _HTTP_METHODS:
            if _looks_like_http_receiver(".".join(parts[:-1])) and arguments:
                method = parts[-1]
                path_expression = arguments[0]
        elif len(parts) >= 2 and parts[-1].lower() == "request" and arguments:
            receiver = ".".join(parts[:-1])
            if _looks_like_http_receiver(receiver):
                request_object = arguments[0]
                method_match = re.search(
                    r"(?:[\"']?method[\"']?)\s*:\s*[\"'](?P<method>[A-Za-z]+)[\"']",
                    request_object,
                    re.IGNORECASE,
                )
                url_match = re.search(
                    r"(?:[\"']?(?:url|path)[\"']?)\s*:\s*(?P<url>[^,}]+)",
                    request_object,
                    re.IGNORECASE,
                )
                if method_match and url_match:
                    method = method_match.group("method")
                    path_expression = url_match.group("url")
        resolved_path = (
            _resolved_endpoint(_resolve_javascript_string(path_expression, environment))
            if path_expression is not None
            else None
        )
        if method and method.lower() in _HTTP_METHODS and resolved_path is not None:
            anchors.append(
                ApiUsageAnchor(
                    symbol_id=symbol.symbol_id if symbol else None,
                    language=language,
                    file_path=source_file.path,
                    method=method.upper(),
                    path=resolved_path,
                    line=line,
                    column=column,
                    evidence=evidence,
                )
            )
        elif symbol is not None:
            calls.append(
                UnresolvedCall(
                    caller_symbol_id=symbol.symbol_id,
                    callee_parts=parts,
                    file_path=source_file.path,
                    line=line,
                    column=column,
                    evidence=evidence,
                )
            )
    return (
        sorted(calls, key=lambda item: (item.line, item.column, item.callee_parts)),
        sorted(anchors, key=lambda item: (item.line, item.column, item.method)),
    )


def _javascript_constants(
    content: str,
    symbols: list[CodeSymbol],
    scope: CodeSymbol | None,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in _JS_CONSTANT_PATTERN.finditer(content):
        offset = match.start("name")
        enclosing = _enclosing_javascript_symbol(symbols, offset)
        if enclosing != scope:
            continue
        resolved = _resolve_javascript_string(match.group("value").strip(), values)
        if resolved is not None:
            values[match.group("name")] = resolved
    return values


def _resolve_javascript_string(
    expression: str | None,
    values: dict[str, str],
) -> str | None:
    if expression is None:
        return None
    value = expression.strip()
    if not value:
        return None
    if re.fullmatch(r"[A-Za-z_$][\w$]*", value):
        return values.get(value)
    if value[0:1] in {"\"", "'"} and value[-1:] == value[0]:
        return _decode_simple_string(value[1:-1])
    if value.startswith("`") and value.endswith("`"):
        body = value[1:-1]
        parts: list[str | None] = []
        cursor = 0
        for match in re.finditer(r"\$\{([^{}]+)\}", body):
            parts.append(body[cursor : match.start()])
            parts.append(_resolve_javascript_string(match.group(1), values))
            cursor = match.end()
        parts.append(body[cursor:])
        if all(part is not None for part in parts):
            return "".join(part or "" for part in parts)
        return _safe_unknown_prefix_suffix(parts)
    concatenated = _split_javascript_concatenation(value)
    if len(concatenated) > 1:
        parts = [_resolve_javascript_string(part, values) for part in concatenated]
        if all(part is not None for part in parts):
            return "".join(part or "" for part in parts)
        return _safe_unknown_prefix_suffix(parts)
    return None


def _resolve_calls(
    analyses: list[SourceAnalysis],
    symbols: tuple[CodeSymbol, ...],
) -> tuple[CodeCallEdge, ...]:
    symbol_by_id = {symbol.symbol_id: symbol for symbol in symbols}
    analyses_by_file = {analysis.file_path: analysis for analysis in analyses}
    modules = {analysis.module_name for analysis in analyses}
    symbols_by_module_name: dict[tuple[str, str], list[CodeSymbol]] = defaultdict(list)
    for symbol in symbols:
        symbols_by_module_name[(symbol.module_name, symbol.name)].append(symbol)

    edges: list[CodeCallEdge] = []
    seen: set[tuple[str, str, int, int]] = set()
    for analysis in analyses:
        for call in analysis.calls:
            caller = symbol_by_id.get(call.caller_symbol_id)
            if caller is None:
                continue
            target = _resolve_call_target(
                call,
                caller,
                analysis.imports,
                modules,
                symbols_by_module_name,
            )
            if target is None or target.symbol_id == caller.symbol_id:
                continue
            key = (caller.symbol_id, target.symbol_id, call.line, call.column)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                CodeCallEdge(
                    caller_symbol_id=caller.symbol_id,
                    callee_symbol_id=target.symbol_id,
                    file_path=call.file_path,
                    line=call.line,
                    column=call.column,
                    evidence=call.evidence,
                )
            )
    del analyses_by_file
    return tuple(
        sorted(
            edges,
            key=lambda edge: (
                edge.file_path,
                edge.line,
                edge.column,
                edge.caller_symbol_id,
                edge.callee_symbol_id,
            ),
        )
    )


def _resolve_call_target(
    call: UnresolvedCall,
    caller: CodeSymbol,
    imports: dict[str, ImportBinding],
    modules: set[str],
    symbols_by_module_name: dict[tuple[str, str], list[CodeSymbol]],
) -> CodeSymbol | None:
    parts = call.callee_parts
    if not parts:
        return None
    requested_module = caller.module_name
    requested_name = parts[-1]
    candidates: list[CodeSymbol]

    binding = imports.get(parts[0])
    if binding is not None:
        requested_module = binding.module_name
        if not binding.namespace:
            requested_name = binding.imported_name or requested_name
        elif len(parts) > 2:
            suffix = ".".join(parts[1:-1])
            if suffix and not requested_module.endswith((f".{suffix}", f"/{suffix}")):
                separator = "/" if "/" in requested_module else "."
                requested_module = f"{requested_module}{separator}{suffix}"
    elif len(parts) == 1:
        candidates = symbols_by_module_name.get((caller.module_name, requested_name), [])
        candidates = [item for item in candidates if item.container is None]
        return candidates[0] if len(candidates) == 1 else None
    elif parts[0] in {"self", "cls", "this"} and caller.container:
        candidates = symbols_by_module_name.get((caller.module_name, requested_name), [])
        candidates = [item for item in candidates if item.container == caller.container]
        return candidates[0] if len(candidates) == 1 else None
    else:
        return None

    resolved_module = _resolve_module_name(requested_module, modules)
    if resolved_module is None:
        return None
    candidates = symbols_by_module_name.get((resolved_module, requested_name), [])
    candidates = [item for item in candidates if item.container is None]
    return candidates[0] if len(candidates) == 1 else None


def _resolve_module_name(requested: str, modules: set[str]) -> str | None:
    normalized = requested.strip("./").replace("\\", "/")
    variants = {requested, normalized, normalized.replace("/", ".")}
    exact = sorted(module for module in modules if module in variants)
    if len(exact) == 1:
        return exact[0]
    suffix_matches = sorted(
        module
        for module in modules
        if any(
            module.endswith(f".{variant}") or module.endswith(f"/{variant}")
            for variant in variants
            if variant
        )
    )
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def _mask_javascript(content: str) -> str:
    output = list(content)
    index = 0
    state = "normal"
    quote = ""
    while index < len(content):
        current = content[index]
        next_value = content[index + 1] if index + 1 < len(content) else ""
        if state == "normal":
            if current == "/" and next_value == "/":
                output[index] = output[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if current == "/" and next_value == "*":
                output[index] = output[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
            if current in {"'", '"', "`"}:
                quote = current
                output[index] = " "
                state = "string"
        elif state == "line_comment":
            if current == "\n":
                state = "normal"
            else:
                output[index] = " "
        elif state == "block_comment":
            if current == "*" and next_value == "/":
                output[index] = output[index + 1] = " "
                state = "normal"
                index += 2
                continue
            if current != "\n":
                output[index] = " "
        elif state == "string":
            if current == "\\":
                output[index] = " "
                if index + 1 < len(content):
                    if content[index + 1] != "\n":
                        output[index + 1] = " "
                    index += 2
                    continue
            if current == quote:
                output[index] = " "
                state = "normal"
            elif current != "\n":
                output[index] = " "
        index += 1
    if state in {"block_comment", "string"}:
        raise ValueError("unterminated JavaScript token")
    return "".join(output)


def _matching_brace(masked: str, opening: int) -> int:
    if opening < 0:
        raise ValueError("function body missing")
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced JavaScript function")


def _javascript_arguments(content: str, opening: int) -> list[str]:
    arguments: list[str] = []
    start = opening + 1
    index = start
    depth = 0
    state = "normal"
    quote = ""
    while index < len(content):
        current = content[index]
        if state == "normal":
            if current in {"'", '"', "`"}:
                state = "string"
                quote = current
            elif current in "[{(":
                depth += 1
            elif current in "]}":
                depth = max(0, depth - 1)
            elif current == ")":
                if depth == 0:
                    arguments.append(content[start:index].strip())
                    return [argument for argument in arguments if argument]
                depth -= 1
            elif current == "," and depth == 0:
                arguments.append(content[start:index].strip())
                start = index + 1
        elif state == "string":
            if current == "\\":
                index += 2
                continue
            if current == quote:
                state = "normal"
        index += 1
    raise ValueError("unterminated JavaScript call")


def _split_javascript_concatenation(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    state = "normal"
    quote = ""
    depth = 0
    index = 0
    while index < len(value):
        current = value[index]
        if state == "normal":
            if current in {"'", '"', "`"}:
                state = "string"
                quote = current
            elif current in "([{" :
                depth += 1
            elif current in ")]}" :
                depth = max(0, depth - 1)
            elif current == "+" and depth == 0:
                parts.append(value[start:index].strip())
                start = index + 1
        elif current == "\\":
            index += 2
            continue
        elif current == quote:
            state = "normal"
        index += 1
    parts.append(value[start:].strip())
    return parts


def _is_javascript_declaration(masked: str, offset: int) -> bool:
    prefix = masked[max(0, offset - 20) : offset]
    return bool(re.search(r"\bfunction\s*$", prefix))


def _enclosing_javascript_symbol(
    symbols: list[CodeSymbol],
    offset: int,
) -> CodeSymbol | None:
    candidates = [
        symbol
        for symbol in symbols
        if symbol.start_offset <= offset < symbol.end_offset
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda symbol: symbol.end_offset - symbol.start_offset)


def _javascript_import_module(file_path: str, requested: str) -> str:
    if not requested.startswith("."):
        return requested
    base_parts = list(PurePosixPath(file_path).parent.parts)
    for part in requested.replace("\\", "/").split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if base_parts:
                base_parts.pop()
            continue
        base_parts.append(part)
    path = PurePosixPath(*base_parts)
    if path.suffix.lower() in _JAVASCRIPT_EXTENSIONS:
        path = path.with_suffix("")
    return path.as_posix()


def _python_module_name(file_path: str) -> str:
    path = PurePosixPath(file_path)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "repository"


def _javascript_module_name(file_path: str) -> str:
    path = PurePosixPath(file_path).with_suffix("")
    if path.name == "index":
        path = path.parent
    return path.as_posix() or "repository"


def _looks_like_http_receiver(receiver: str) -> bool:
    normalized = receiver.casefold().replace("-", "_")
    return any(hint in normalized for hint in _HTTP_RECEIVER_HINTS)


def _resolved_endpoint(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    parsed = urlparse(stripped)
    if parsed.scheme in {"http", "https"} and parsed.path:
        stripped = parsed.path
    if not stripped.startswith("/"):
        return None
    return stripped.split("?", 1)[0].split("#", 1)[0]


def _safe_unknown_prefix_suffix(parts: list[str | None]) -> str | None:
    last_unknown = max((index for index, part in enumerate(parts) if part is None), default=-1)
    suffix = "".join(part or "" for part in parts[last_unknown + 1 :])
    return suffix if suffix.startswith("/") else None


def _decode_simple_string(value: str) -> str:
    return (
        value.replace(r"\n", "\n")
        .replace(r"\t", "\t")
        .replace(r"\'", "'")
        .replace(r'\"', '"')
        .replace(r"\\", "\\")
    )


def _line_column(content: str, offset: int) -> tuple[int, int]:
    line = content.count("\n", 0, offset) + 1
    previous_newline = content.rfind("\n", 0, offset)
    return line, offset - previous_newline


def _line_evidence(lines: list[str], line: int) -> str:
    if line < 1 or line > len(lines):
        return ""
    return " ".join(lines[line - 1].strip().split())[:240]


def _symbol_id(language: str, file_path: str, qualified_name: str, line: int) -> str:
    return f"{language}:{file_path}:{qualified_name}:{line}"


def _symbol_sort_key(symbol: CodeSymbol) -> tuple[str, int, int, str]:
    return symbol.file_path, symbol.line, symbol.column, symbol.qualified_name


def _code_limit_error(limit: str, maximum: int) -> None:
    raise DriftGuardError(
        code="repository_code_analysis_limit_exceeded",
        message="The repository exceeds a configured static-analysis limit.",
        status_code=413,
        details={"limit": limit, "maximum": maximum},
    )


def propagation_paths(
    graph: RepositoryCodeGraph,
    anchor: ApiUsageAnchor,
    *,
    max_depth: int,
) -> list[tuple[int, CodeSymbol, CodeCallEdge, tuple[CodeCallEdge, ...]]]:
    """Return deterministic callers and their anchor-to-caller edge chains."""

    if anchor.symbol_id is None:
        return []
    symbols = graph.symbol_map()
    callers = graph.callers()
    queue: deque[tuple[str, int, tuple[CodeCallEdge, ...]]] = deque(
        [(anchor.symbol_id, 0, ())]
    )
    best_depth: dict[str, int] = {anchor.symbol_id: 0}
    results: list[tuple[int, CodeSymbol, CodeCallEdge, tuple[CodeCallEdge, ...]]] = []
    while queue:
        callee_id, depth, chain = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in callers.get(callee_id, ()):
            next_depth = depth + 1
            previous = best_depth.get(edge.caller_symbol_id)
            if previous is not None and previous <= next_depth:
                continue
            caller = symbols.get(edge.caller_symbol_id)
            if caller is None:
                continue
            best_depth[edge.caller_symbol_id] = next_depth
            next_chain = (*chain, edge)
            results.append((next_depth, caller, edge, next_chain))
            queue.append((edge.caller_symbol_id, next_depth, next_chain))
    return sorted(
        results,
        key=lambda item: (
            item[0],
            item[1].file_path,
            item[2].line,
            item[2].column,
            item[1].qualified_name,
        ),
    )
