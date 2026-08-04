from __future__ import annotations

from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.openapi.differ import ContractDiffer
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.repository.matcher import ApiImpactMatcher


def impacts_for(old, new, content):
    old_contract = normalize_openapi(old)
    new_contract = normalize_openapi(new)
    changes = ContractDiffer().compare(old_contract, new_contract)
    repository = RepositoryScan(
        archive_sha256="0" * 64,
        archive_entries=1,
        files=(ScannedSourceFile(path="src/client.py", content=content, size_bytes=len(content)),),
        skipped_files=0,
        skipped_reasons={},
    )
    return ApiImpactMatcher().match(changes, repository, old_contract, new_contract)


def test_matches_path_and_http_method_with_high_confidence(base_spec, clone):
    new = clone(base_spec)
    del new["paths"]["/payments"]["post"]["responses"]["201"]

    impacts = impacts_for(
        base_spec, new, 'response = requests.post(f"{base_url}/payments", json=payload)'
    )

    assert impacts[0].matches[0].match_kind.value == "path_and_method"
    assert impacts[0].matches[0].confidence.value == "high"
    assert impacts[0].matches[0].file_path == "src/client.py"


def test_matches_operation_id_even_without_literal_path(base_spec, clone):
    base_spec["paths"]["/payments"]["post"]["operationId"] = "createPayment"
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["parameters"][0]["schema"]["type"] = "integer"

    impacts = impacts_for(base_spec, new, "sdk.createPayment(payload)")

    assert impacts[0].matches[0].match_kind.value == "operation_id"
    assert impacts[0].matches[0].evidence == "sdk.createPayment(payload)"


def test_matches_templated_path_and_returns_empty_result_for_unrelated_file(
    base_spec, clone
):
    operation = base_spec["paths"].pop("/payments")
    base_spec["paths"]["/payments/{payment_id}"] = operation
    new = clone(base_spec)
    del new["paths"]["/payments/{payment_id}"]["post"]["responses"]["201"]

    matched = impacts_for(
        base_spec,
        new,
        'client.post(f"/payments/{payment_id}")',
    )
    unrelated = impacts_for(base_spec, new, 'print("no API call")')

    assert matched[0].matches[0].match_kind.value == "path_and_method"
    assert unrelated[0].matches == []


def test_does_not_match_a_longer_unrelated_path(base_spec, clone):
    new = clone(base_spec)
    del new["paths"]["/payments"]["post"]["responses"]["201"]

    impacts = impacts_for(base_spec, new, 'client.post("/payments-archive")')

    assert impacts[0].matches == []
