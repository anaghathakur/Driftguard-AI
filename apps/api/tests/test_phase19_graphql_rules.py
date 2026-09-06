from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from apps.api.app.contracts.registry import default_contract_registry
from apps.api.tests.test_phase19_graphql import NEW_SCHEMA, OLD_SCHEMA, _graphql_upload


def _changes(old: bytes, new: bytes):
    return default_contract_registry.prepare_comparison(
        old_filename="old.graphql",
        old_content=old,
        new_filename="new.graphql",
        new_content=new,
    ).response.changes


def _repository_upload(path: str, content: str):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(path, content)
    return "repository.zip", output.getvalue(), "application/zip"


def test_graphql_type_field_and_input_field_rules():
    old = b"""
type Query { user(filter: UserFilter): User }
type User { id: ID!, name: String }
input UserFilter { legacy: String, term: String! }
type Legacy { id: ID! }
"""
    new = b"""
type Query { user(filter: UserFilter): User }
type User { id: ID!, email: String }
input UserFilter { term: String, locale: String, page: Int! }
type Added { id: ID! }
"""
    by_key = {
        (item.change_type.value, item.operation_identifier): item for item in _changes(old, new)
    }

    assert by_key[("type_removed", "Legacy")].category.value == "breaking"
    assert by_key[("type_added", "Added")].category.value == "non_breaking"
    assert by_key[("field_removed", "User.name")].category.value == "breaking"
    assert by_key[("field_added", "User.email")].category.value == "non_breaking"
    assert by_key[("input_field_removed", "UserFilter.legacy")].category.value == "breaking"
    assert by_key[("input_field_added", "UserFilter.locale")].category.value == "non_breaking"
    assert by_key[("required_input_field_added", "UserFilter.page")].category.value == "breaking"
    assert by_key[("nullability_relaxed", "UserFilter.term")].category.value == "non_breaking"


def test_graphql_list_input_and_return_type_changes_are_conservative():
    old = b"type Query { search(ids: [ID!]!): [String!]! }"
    new = b"type Query { search(ids: [String]!): [String] }"
    changes = _changes(old, new)
    input_change = next(item for item in changes if item.subject == "ids")
    output_change = next(
        item for item in changes if item.change_type.value == "graphql_return_type_changed"
    )
    assert input_change.change_type.value == "graphql_input_type_changed"
    assert input_change.category.value == "breaking"
    assert output_change.category.value == "breaking"


def test_plain_graphql_fragment_document_is_high_confidence(client):
    query = """
mutation CreatePayment($email: String!) {
  ...CreatePaymentMutation
}
fragment CreatePaymentMutation on Mutation {
  createPayment(amount: 100, email: $email) { id }
}
"""
    response = client.post(
        "/api/v1/impact/analyze",
        files={
            "old_spec": _graphql_upload("old.graphql", OLD_SCHEMA),
            "new_spec": _graphql_upload("new.graphql", NEW_SCHEMA),
            "repository": _repository_upload("queries/createPayment.graphql", query),
        },
    )
    assert response.status_code == 200, response.text
    removed = next(
        impact
        for impact in response.json()["impacts"]
        if impact["operation_identifier"] == "Mutation.createPayment"
        and any(match["confidence"] == "high" for match in impact["matches"])
    )
    assert any(
        match["confidence"] == "high" and match["analysis_kind"] == "direct"
        for match in removed["matches"]
    )


def test_python_graphql_string_and_dynamic_lexical_fallback_are_not_executed(client):
    source = '''
PAYMENT_MUTATION = """
mutation CreatePayment($email: String!) {
  createPayment(amount: 100, email: $email) { id }
}
"""

def build_dynamic_query():
    field = "createPayment"
    return field + "email"
'''
    response = client.post(
        "/api/v1/impact/analyze",
        files={
            "old_spec": _graphql_upload("old.graphql", OLD_SCHEMA),
            "new_spec": _graphql_upload("new.graphql", NEW_SCHEMA),
            "repository": _repository_upload("client.py", source),
        },
    )
    assert response.status_code == 200, response.text
    matches = [
        match
        for impact in response.json()["impacts"]
        if impact["operation_identifier"] == "Mutation.createPayment"
        for match in impact["matches"]
    ]
    assert any(
        item["confidence"] == "high" and item["analysis_kind"] == "direct" for item in matches
    )
    assert any(
        item["confidence"] == "low" and item["match_kind"] == "graphql_lexical" for item in matches
    )
