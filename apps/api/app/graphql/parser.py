"""Parse untrusted GraphQL SDL with graphql-core under explicit limits."""

from __future__ import annotations

from dataclasses import dataclass

from graphql import GraphQLSchema, build_ast_schema, parse, validate_schema
from graphql.error import GraphQLError
from graphql.language import DocumentNode, Node

from apps.api.app.core import config
from apps.api.app.core.exceptions import DriftGuardError

GRAPHQL_EXTENSIONS = (".graphql", ".gql")


@dataclass(frozen=True, slots=True)
class GraphQLContract:
    schema: GraphQLSchema
    document: DocumentNode
    title: str
    version: str

    @property
    def operation_count(self) -> int:
        roots = (self.schema.query_type, self.schema.mutation_type, self.schema.subscription_type)
        return sum(len(root.fields) for root in roots if root is not None)


def parse_graphql_schema(filename: str, content: bytes) -> GraphQLContract:
    if not filename.lower().endswith(GRAPHQL_EXTENSIONS):
        raise DriftGuardError(
            code="unsupported_contract_type",
            message="GraphQL SDL files must use a .graphql or .gql extension.",
        )
    if not content:
        raise DriftGuardError(code="invalid_graphql_contract", message="The GraphQL SDL is empty.")
    maximum = getattr(
        config.settings,
        "max_graphql_document_bytes",
        config.settings.max_spec_file_bytes,
    )
    if len(content) > maximum:
        raise DriftGuardError(
            code="specification_too_large",
            message="The GraphQL SDL exceeds the configured size limit.",
            status_code=413,
            details={"max_bytes": maximum},
        )
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DriftGuardError(
            code="invalid_graphql_contract", message="The GraphQL SDL must be valid UTF-8."
        ) from exc
    try:
        document = parse(source, no_location=False, max_tokens=None)
    except GraphQLError as exc:
        raise DriftGuardError(
            code="graphql_parse_error", message="The GraphQL SDL contains invalid syntax."
        ) from exc
    _validate_ast_limits(document)
    try:
        schema = build_ast_schema(document)
    except GraphQLError as exc:
        raise DriftGuardError(
            code="graphql_schema_invalid", message="The GraphQL SDL does not define a valid schema."
        ) from exc
    errors = [
        error
        for error in validate_schema(schema)
        if not (
            error.message == "Query root type must be provided."
            and (schema.mutation_type is not None or schema.subscription_type is not None)
        )
    ]
    if errors:
        raise DriftGuardError(
            code="graphql_schema_invalid",
            message="The GraphQL SDL does not define a valid schema.",
            details={"issues": min(len(errors), 20)},
        )
    user_types = [name for name in schema.type_map if not name.startswith("__")]
    if not user_types or not any(
        (schema.query_type, schema.mutation_type, schema.subscription_type)
    ):
        raise DriftGuardError(
            code="invalid_graphql_contract",
            message=(
                "The GraphQL SDL must define at least one query, mutation, or subscription root."
            ),
        )
    return GraphQLContract(schema=schema, document=document, title="GraphQL schema", version="SDL")


def _validate_ast_limits(document: DocumentNode) -> None:
    maximum_nodes = getattr(config.settings, "max_graphql_ast_nodes", 100_000)
    maximum_depth = 100
    count = 0
    stack: list[tuple[Node, int]] = [(document, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > maximum_nodes or depth > maximum_depth:
            raise DriftGuardError(
                code="graphql_contract_too_complex",
                message="The GraphQL SDL exceeds supported complexity limits.",
                status_code=413,
                details={
                    "configured_max_ast_nodes": maximum_nodes,
                    "configured_max_depth": maximum_depth,
                    "observed_ast_nodes": count,
                    "observed_depth": depth,
                },
            )
        for key in node.keys:
            value = getattr(node, key, None)
            if isinstance(value, Node):
                stack.append((value, depth + 1))
            elif isinstance(value, tuple):
                stack.extend((item, depth + 1) for item in value if isinstance(item, Node))
