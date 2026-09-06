"""Auditable deterministic migration planning and safe external-provider fallback."""

from __future__ import annotations

from apps.api.app.migration.context import MigrationContext
from apps.api.app.schemas.comparison import ChangeType, ContractType
from apps.api.app.schemas.migration import GeneratedMigrationContent


def deterministic_recommendation(
    context: MigrationContext,
) -> GeneratedMigrationContent:
    change = context.change

    subject = _short(
        change.subject or "the changed contract element",
        160,
    )
    method = _short(change.method.upper(), 16)
    path = _short(change.path, 300)
    location = _short(change.operation_identifier or f"{method} {path}".strip(), 340)

    match_count = len(context.impact.matches)
    file_count = len({match.file_path for match in context.impact.matches})

    impact_text = _impact_text(match_count, file_count)

    summary = f"Update the integration for {location}: {change.change_type.value}."

    why = _short(
        f"{_short(change.explanation, 700)} {impact_text}",
        1_000,
    )

    affected = _affected_explanation(context)

    assumptions: list[str] = []
    warnings: list[str] = []

    confidence = 0.84 if match_count else 0.68
    code_example = ""

    match change.change_type:
        case ChangeType.ENDPOINT_REMOVED | ChangeType.HTTP_METHOD_REMOVED:
            summary = f"Calls to {location} must be replaced or removed."

            steps = [
                ("Confirm the provider's documented replacement endpoint or workflow."),
                ("Locate every matched call site and replace or remove the obsolete request."),
                (
                    "Update client abstractions, request types, and "
                    "error handling for the replacement."
                ),
                ("Run contract and integration tests for every affected call path."),
            ]

            tests = [
                "Verify no production code calls the removed operation.",
                ("Verify the replacement request uses the expected method, path, and payload."),
                ("Verify failures from the replacement API are handled safely."),
            ]

            warnings.append(
                "A replacement operation was not supplied; confirm it in provider documentation."
            )

            confidence = 0.9 if match_count else 0.75

        case ChangeType.REQUIRED_PARAMETER_ADDED:
            summary = f"Add the required parameter '{subject}' to {location} calls."

            steps = [
                (f"Identify how the application should obtain a valid value for '{subject}'."),
                (f"Add '{subject}' in the required parameter location for every matched request."),
                ("Update validation and client types so the value cannot be omitted."),
                ("Update tests and fixtures to include the new required parameter."),
            ]

            tests = [
                f"Verify every {location} request includes '{subject}'.",
                (f"Verify a missing or invalid '{subject}' is rejected before the API call."),
                ("Verify existing successful request behavior remains unchanged."),
            ]

            code_example = _parameter_example(
                change.method,
                change.path,
                subject,
            )

            confidence = 0.92 if match_count else 0.78

        case (
            ChangeType.REQUIRED_REQUEST_FIELD_ADDED
            | ChangeType.REQUIRED_ARGUMENT_ADDED
            | ChangeType.REQUIRED_INPUT_FIELD_ADDED
        ):
            summary = f"Add the required request field '{subject}' to {location} payloads."

            steps = [
                (f"Determine the authoritative source for the new '{subject}' value."),
                f"Add '{subject}' to every matched request payload.",
                ("Update request schemas, types, and validation so the field is mandatory."),
                ("Review whether any removed or superseded field should also be deleted."),
                ("Update unit and integration tests for the new payload contract."),
            ]

            tests = [
                f"Verify every {location} payload contains '{subject}'.",
                (f"Verify requests without '{subject}' fail validation before network I/O."),
                ("Verify the serialized payload contains only currently supported fields."),
            ]

            code_example = (
                ""
                if change.contract_type is ContractType.GRAPHQL
                else _body_field_example(
                    change.method,
                    change.path,
                    subject,
                )
            )

            confidence = 0.94 if match_count else 0.8

        case (
            ChangeType.PARAMETER_REMOVED
            | ChangeType.REQUEST_FIELD_REMOVED
            | ChangeType.ARGUMENT_REMOVED
            | ChangeType.INPUT_FIELD_REMOVED
        ):
            summary = f"Remove '{subject}' from {location} requests."

            steps = [
                (f"Remove '{subject}' from matched request construction code."),
                ("Remove or deprecate obsolete validation, types, and mapping logic."),
                ("Check whether the removed value has a documented replacement."),
                ("Update tests so they assert the current request shape."),
            ]

            tests = [
                (f"Verify serialized {location} requests no longer contain '{subject}'."),
                ("Verify the request still succeeds with the remaining supported fields."),
                ("Verify legacy callers receive a clear migration error when appropriate."),
            ]

            assumptions.append("The provider no longer accepts the removed field or parameter.")

        case (
            ChangeType.PARAMETER_TYPE_CHANGED
            | ChangeType.REQUEST_FIELD_TYPE_CHANGED
            | ChangeType.GRAPHQL_INPUT_TYPE_CHANGED
            | ChangeType.GRAPHQL_RETURN_TYPE_CHANGED
            | ChangeType.NULLABILITY_TIGHTENED
        ):
            summary = f"Convert '{subject}' to the new type required by {location}."

            steps = [
                (f"Update the application type and serializer for '{subject}'."),
                ("Add explicit conversion or validation at the integration boundary."),
                ("Review stored data and upstream callers for incompatible values."),
                ("Update tests with valid, invalid, and boundary values for the new type."),
            ]

            tests = [
                (f"Verify '{subject}' is serialized using the new contract type."),
                ("Verify incompatible values are rejected with a clear error."),
                ("Verify representative existing values migrate without data loss."),
            ]

            warnings.append("Confirm conversion semantics in the provider documentation.")

        case ChangeType.RESPONSE_FIELD_REMOVED | ChangeType.RESPONSE_STATUS_REMOVED:
            summary = f"Stop depending on the removed response contract in {location}."

            steps = [
                (f"Search response parsing and downstream logic for '{subject}'."),
                ("Replace the dependency with a documented alternative or make it optional."),
                "Update response models and null/error handling.",
                ("Update tests and fixtures to reflect the new response shape."),
            ]

            tests = [
                ("Verify response parsing succeeds when the removed element is absent."),
                ("Verify downstream behavior remains safe without the old value."),
                ("Verify unexpected response shapes produce a controlled error."),
            ]

        case ChangeType.RESPONSE_FIELD_TYPE_CHANGED:
            summary = f"Update response parsing for the new type of '{subject}' in {location}."

            steps = [
                (f"Update the response model and parser for '{subject}'."),
                ("Add compatibility handling only if the provider documents a transition period."),
                ("Review calculations, comparisons, and persistence that consume the value."),
                ("Update response fixtures and boundary-value tests."),
            ]

            tests = [
                f"Verify '{subject}' is parsed using the new type.",
                "Verify malformed or legacy values fail safely.",
                ("Verify downstream computations use the converted value correctly."),
            ]

        case ChangeType.AUTHENTICATION_ADDED | ChangeType.AUTHENTICATION_CHANGED:
            summary = f"Update authentication for {location}."

            steps = [
                ("Confirm the required authentication scheme and credential scope."),
                (
                    "Update the shared API client to attach credentials "
                    "using the documented mechanism."
                ),
                ("Store credentials in environment or secret management, never in source code."),
                ("Update token refresh, expiry, and authorization-error handling."),
                ("Add authentication tests without using real production secrets."),
            ]

            tests = [
                ("Verify authenticated requests include the required scheme."),
                ("Verify missing or expired credentials fail with a controlled error."),
                ("Verify secrets are never written to logs or persisted analysis output."),
            ]

            warnings.append("Never hard-code the new credential in the repository.")

            confidence = 0.9

        case ChangeType.ENUM_VALUE_REMOVED:
            summary = f"Stop sending or relying on the removed enum value '{subject}'."

            steps = [
                (f"Find producers and consumers of the enum value '{subject}'."),
                ("Map existing application behavior to a currently supported value."),
                ("Update validation, types, database mappings, and user-facing options."),
                ("Plan data migration if the removed value is stored persistently."),
            ]

            tests = [
                (f"Verify '{subject}' can no longer be selected or serialized."),
                "Verify supported enum values continue to work.",
                ("Verify stored legacy values are handled according to the migration policy."),
            ]

            warnings.append("The correct replacement enum value was not supplied.")

        case ChangeType.DESCRIPTION_ONLY:
            summary = f"Review the documentation-only change for {location}."

            why = (
                "The detected change affects descriptive text and does "
                "not alter the normalized contract."
            )

            affected = "No code modification is indicated by the available contract evidence."

            steps = [
                ("Review the updated description for clarified behavior or operational guidance."),
                ("Update internal documentation only if the clarification affects team usage."),
            ]

            tests = [
                (
                    "No new automated test is required unless the "
                    "description clarifies previously untested behavior."
                )
            ]

            confidence = 0.97

        case _:
            steps = [
                (f"Review the before and after contract values for '{subject}'."),
                ("Update matched integration code to conform to the new contract."),
                ("Update validation, types, fixtures, and error handling as needed."),
                ("Run focused unit and integration tests for the affected operation."),
            ]

            tests = [
                (f"Verify {location} requests and responses match the new contract."),
                "Verify invalid legacy behavior fails safely.",
            ]

    return GeneratedMigrationContent(
        summary=summary,
        why_it_matters=why,
        affected_code_explanation=affected,
        migration_steps=steps,
        suggested_tests=tests,
        code_example=code_example,
        assumptions=assumptions,
        warnings=warnings,
        confidence=confidence,
    )


def _impact_text(
    match_count: int,
    file_count: int,
) -> str:
    if not match_count:
        return (
            "No matching repository usage was detected, so repository-specific impact is uncertain."
        )

    return f"DriftGuard found {match_count} matching usage(s) across {file_count} file(s)."


def _affected_explanation(
    context: MigrationContext,
) -> str:
    matches = context.impact.matches

    if not matches:
        return (
            "No source location was matched; review dynamic URL "
            "construction and indirect client wrappers manually."
        )

    paths = sorted({_short(match.file_path, 180) for match in matches})

    shown = ", ".join(paths[:4])
    suffix = "" if len(paths) <= 4 else f" and {len(paths) - 4} more file(s)"

    return _short(
        (
            f"Matched API usage appears in {shown}{suffix}; "
            "update those call sites and their shared client code."
        ),
        1_000,
    )


def _short(
    value: object,
    max_chars: int,
) -> str:
    return str(value)[:max_chars]


def _body_field_example(
    method: str,
    path: str,
    subject: str,
) -> str:
    if not subject or not subject.replace("_", "").isalnum():
        return ""

    return (
        "# Pseudocode only — adapt to your client\n"
        f'client.{method.lower()}("{path}", json={{\n'
        f'    "{subject}": resolved_value,\n'
        "    # existing supported fields\n"
        "})"
    )


def _parameter_example(
    method: str,
    path: str,
    subject: str,
) -> str:
    if not subject or not subject.replace("_", "").isalnum():
        return ""

    return (
        "# Pseudocode only — place the value in the documented "
        "parameter location\n"
        f'client.{method.lower()}("{path}", '
        f'params={{"{subject}": resolved_value}})'
    )
