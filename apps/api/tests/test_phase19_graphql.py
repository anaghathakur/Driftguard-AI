from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from apps.api.app.contracts.registry import default_contract_registry
from apps.api.app.core.exceptions import DriftGuardError

OLD_SCHEMA = b"""
type Query { payment(id: ID!): Payment }
type Mutation { createPayment(amount: Int!, email: String!): Payment! }
type Payment { id: ID!, status: Status! }
enum Status { PENDING COMPLETE FAILED }
input PaymentFilter { email: String }
"""

NEW_SCHEMA = b"""
type Query { payment(id: ID!): Payment }
type Mutation { createPayment(amount: Int!, customerId: ID!): Payment! }
type Payment { id: ID!, status: Status! }
enum Status { PENDING COMPLETE REFUNDED }
input PaymentFilter { email: String, customerId: ID! }
"""


def _graphql_upload(name: str, content: bytes):
    return (name, content, "application/graphql")


def _repository_upload() -> tuple[str, bytes, str]:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "src/paymentClient.ts",
            """import { gql } from 'graphql-tag';
export function createPayment(email: string) {
  const mutation = gql`
    mutation CreatePayment($email: String!) {
      createPayment(amount: 100, email: $email) { id }
    }
  `;
  return mutation;
}
""",
        )
        archive.writestr(
            "src/checkout.ts",
            """import { createPayment } from './paymentClient';
export function checkout(email: string) {
  return createPayment(email);
}
""",
        )
        archive.writestr(
            "src/orderService.ts",
            """import { checkout } from './checkout';
export function submitOrder(email: string) {
  return checkout(email);
}
""",
        )
    return ("graphql-client.zip", output.getvalue(), "application/zip")


def test_graphql_adapter_detects_and_classifies_core_changes():
    result = default_contract_registry.prepare_comparison(
        old_filename="old.graphql",
        old_content=OLD_SCHEMA,
        new_filename="new.graphql",
        new_content=NEW_SCHEMA,
    ).response

    assert result.old_contract.contract_type.value == "graphql"
    changes = {
        (item.change_type.value, item.operation_identifier, item.subject): item
        for item in result.changes
    }
    assert changes[("argument_removed", "Mutation.createPayment", "email")].breaking
    assert changes[("required_argument_added", "Mutation.createPayment", "customerId")].breaking
    assert changes[("enum_value_removed", "Status", "FAILED")].breaking
    assert (
        changes[("enum_value_added", "Status", "REFUNDED")].category.value == "potentially_breaking"
    )
    assert changes[
        ("required_input_field_added", "PaymentFilter.customerId", "customerId")
    ].breaking


def test_graphql_nullability_and_optional_addition_rules():
    old = b"type Query { search(term: String!): String }"
    new = b"type Query { search(term: String, locale: String): String! }"
    changes = default_contract_registry.prepare_comparison(
        old_filename="old.gql", old_content=old, new_filename="new.gql", new_content=new
    ).response.changes
    by_type = {item.change_type.value: item for item in changes}
    assert by_type["nullability_relaxed"].category.value == "non_breaking"
    assert by_type["argument_added"].category.value == "non_breaking"
    assert by_type["graphql_return_type_changed"].category.value == "potentially_breaking"


def test_graphql_invalid_and_cross_protocol_inputs_are_controlled(base_spec):
    with pytest.raises(DriftGuardError) as invalid:
        default_contract_registry.prepare_comparison(
            old_filename="old.graphql",
            old_content=b"type Query {",
            new_filename="new.graphql",
            new_content=b"type Query { ok: Boolean }",
        )
    assert invalid.value.code == "graphql_parse_error"

    with pytest.raises(DriftGuardError) as mismatch:
        default_contract_registry.prepare_comparison(
            old_filename="old.graphql",
            old_content=b"type Query { ok: Boolean }",
            new_filename="new.json",
            new_content=str(base_spec).encode(),
        )
    assert mismatch.value.code == "contract_type_mismatch"


def test_graphql_contract_api_and_repository_lifecycle(client):
    comparison = client.post(
        "/api/v1/contracts/compare",
        files={
            "old_contract": _graphql_upload("old.graphql", OLD_SCHEMA),
            "new_contract": _graphql_upload("new.graphql", NEW_SCHEMA),
        },
        data={"contract_type": "auto"},
    )
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["old_contract"]["contract_type"] == "graphql"

    impact = client.post(
        "/api/v1/impact/analyze",
        files={
            "old_spec": _graphql_upload("old.graphql", OLD_SCHEMA),
            "new_spec": _graphql_upload("new.graphql", NEW_SCHEMA),
            "repository": _repository_upload(),
        },
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    target = next(
        item
        for item in body["impacts"]
        if item["operation_identifier"] == "Mutation.createPayment"
        and next(
            change
            for change in body["comparison"]["changes"]
            if change["change_id"] == item["change_id"]
        )["subject"]
        == "email"
    )
    assert any(item["analysis_kind"] == "direct" for item in target["matches"])
    assert any(item["analysis_kind"] == "wrapper" for item in target["matches"])
    assert any(item["analysis_kind"] == "transitive" for item in target["matches"])
    assert body["impact_summary"]["impacted_files"] >= 3
    assert client.get(f"/api/v1/analyses/{body['analysis_id']}").status_code == 200
