from __future__ import annotations

from pathlib import Path

import yaml

from apps.api.app.openapi.differ import ContractDiffer
from apps.api.app.openapi.normalizer import normalize_openapi


def change_types(old, new):
    changes = ContractDiffer().compare(normalize_openapi(old), normalize_openapi(new))
    return [change.change_type.value for change in changes]


def test_endpoint_removed(base_spec, clone):
    new = clone(base_spec)
    new["paths"] = {}
    assert change_types(base_spec, new) == ["endpoint_removed"]


def test_required_request_field_added(base_spec, clone):
    new = clone(base_spec)
    schema = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    schema = schema["application/json"]["schema"]
    schema["properties"]["customer_id"] = {"type": "string"}
    schema["required"].append("customer_id")
    changes = ContractDiffer().compare(normalize_openapi(base_spec), normalize_openapi(new))
    assert changes[0].change_type.value == "required_request_body_field_added"
    assert changes[0].breaking is True


def test_optional_request_field_added_is_non_breaking(base_spec, clone):
    new = clone(base_spec)
    schema = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    schema["application/json"]["schema"]["properties"]["note"] = {"type": "string"}
    changes = ContractDiffer().compare(normalize_openapi(base_spec), normalize_openapi(new))
    assert changes[0].change_type.value == "request_body_field_added"
    assert changes[0].category.value == "non_breaking"


def test_parameter_type_changed(base_spec, clone):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["parameters"][0]["schema"]["type"] = "integer"
    assert change_types(base_spec, new) == ["parameter_data_type_changed"]


def test_parameter_rename_is_inferred_only_for_equivalent_parameters(base_spec, clone):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["parameters"][0]["name"] = "request_id"
    assert change_types(base_spec, new) == ["parameter_renamed"]


def test_authentication_added(base_spec, clone):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["security"] = [{"bearerAuth": []}]
    assert change_types(base_spec, new) == ["authentication_requirement_added"]


def test_response_field_removed(base_spec, clone):
    new = clone(base_spec)
    content = new["paths"]["/payments"]["post"]["responses"]["201"]["content"]
    del content["application/json"]["schema"]["properties"]["status"]
    assert change_types(base_spec, new) == ["response_field_removed"]


def test_description_only_change(base_spec, clone):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["summary"] = "Creates a payment"
    assert change_types(base_spec, new) == ["description_only"]


def test_description_is_not_called_description_only_with_semantic_change(base_spec, clone):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["summary"] = "Creates a payment"
    new["paths"]["/payments"]["post"]["parameters"][0]["schema"]["type"] = "integer"
    assert change_types(base_spec, new) == ["parameter_data_type_changed"]


def test_enum_value_removed(base_spec, clone):
    new = clone(base_spec)
    content = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    content["application/json"]["schema"]["properties"]["currency"]["enum"] = ["INR"]
    assert change_types(base_spec, new) == ["enum_value_removed"]


def test_payment_demo_detects_exactly_two_contract_changes():
    root = Path(__file__).parents[3]
    old_path = root / "sample-data/specifications/payments-old.yaml"
    new_path = root / "sample-data/specifications/payments-new.yaml"
    old = yaml.safe_load(old_path.read_text())
    new = yaml.safe_load(new_path.read_text())
    assert change_types(old, new) == [
        "request_body_field_removed",
        "required_request_body_field_added",
    ]
