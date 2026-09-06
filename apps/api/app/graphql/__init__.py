"""Bounded GraphQL SDL and consumer-document static analysis."""

from apps.api.app.graphql.parser import GraphQLContract, parse_graphql_schema

__all__ = ["GraphQLContract", "parse_graphql_schema"]
