"""Conservative structured edits for statically parsed GraphQL documents."""

from __future__ import annotations

import re

from apps.api.app.schemas.patch import StructuredPatchEdit


def graphql_argument_removal_edits(
    source: str,
    name: str,
    change_ids: list[str],
) -> list[StructuredPatchEdit]:
    """Remove one obsolete operation argument and its unused declaration.

    This intentionally edits only uniquely located GraphQL syntax. Application
    values are not removed unless a separate, explicit source edit proves it is
    safe to do so. That keeps an ambiguous schema replacement reviewable rather
    than pretending to know what a new required value should be.
    """

    declaration_pattern = re.compile(
        rf"(?m)^.*\${re.escape(name)}\s*:\s*[\[\]!_A-Za-z][\[\]!_0-9A-Za-z]*.*(?:\n|$)"
    )
    argument_pattern = re.compile(
        rf"(?m)^.*\b{re.escape(name)}\s*:\s*\${re.escape(name)}\b.*(?:\n|$)"
    )
    declarations = declaration_pattern.findall(source)
    arguments = argument_pattern.findall(source)
    if len(declarations) != 1 or len(arguments) != 1:
        return []

    declaration = declarations[0]
    argument = arguments[0]
    declaration_replacement = _remove_variable_definition(declaration, name)
    argument_replacement = _remove_argument(argument, name)
    if not declaration_replacement or argument_replacement == argument:
        return []

    related = sorted(set(change_ids))
    if declaration == argument:
        combined = _remove_argument(declaration_replacement, name)
        if not combined or combined == declaration:
            return []
        return [
            StructuredPatchEdit(
                expected_original=declaration,
                replacement=combined,
                reason=f"Remove obsolete GraphQL argument '{name}' and its variable declaration.",
                related_change_ids=related,
            )
        ]
    return [
        StructuredPatchEdit(
            expected_original=declaration,
            replacement=declaration_replacement,
            reason=f"Remove unused GraphQL variable '${name}'.",
            related_change_ids=related,
        ),
        StructuredPatchEdit(
            expected_original=argument,
            replacement=argument_replacement,
            reason=f"Stop supplying removed GraphQL argument '{name}'.",
            related_change_ids=related,
        ),
    ]


def graphql_argument_rename_edits(
    source: str,
    old_name: str,
    new_name: str,
    old_type: str | None,
    new_type: str | None,
    change_ids: list[str],
) -> list[StructuredPatchEdit]:
    """Rename only GraphQL syntax; never invent an application value mapping."""

    declaration_pattern = re.compile(
        rf"(?m)^.*\${re.escape(old_name)}\s*:\s*{re.escape(old_type or '[^,)]+')}.*$"
    )
    argument_pattern = re.compile(
        rf"(?m)^.*\b{re.escape(old_name)}\s*:\s*\${re.escape(old_name)}\b.*$"
    )
    declarations = declaration_pattern.findall(source)
    arguments = argument_pattern.findall(source)
    if len(declarations) != 1 or len(arguments) != 1:
        return []
    declaration = declarations[0]
    argument = arguments[0]
    declaration_replacement = re.sub(
        rf"\${re.escape(old_name)}\s*:\s*{re.escape(old_type or '')}",
        f"${new_name}: {new_type or old_type or 'String'}",
        declaration,
        count=1,
    )
    argument_replacement = re.sub(
        rf"\b{re.escape(old_name)}\s*:\s*\${re.escape(old_name)}\b",
        f"{new_name}: ${new_name}",
        argument,
        count=1,
    )
    if declaration_replacement == declaration or argument_replacement == argument:
        return []
    related = sorted(set(change_ids))
    return [
        StructuredPatchEdit(
            expected_original=declaration,
            replacement=declaration_replacement,
            reason=(
                f"Propose GraphQL variable candidate '{old_name}' -> '{new_name}'; "
                "confirm resolver/client mapping during review."
            ),
            related_change_ids=related,
        ),
        StructuredPatchEdit(
            expected_original=argument,
            replacement=argument_replacement,
            reason=(
                f"Propose GraphQL argument candidate '{old_name}' -> '{new_name}'; "
                "confirm resolver/client mapping during review."
            ),
            related_change_ids=related,
        ),
    ]


def _remove_variable_definition(line: str, name: str) -> str | None:
    match = re.search(
        rf"\${re.escape(name)}\s*:\s*[\[\]!_A-Za-z][\[\]!_0-9A-Za-z]*", line
    )
    if match is None:
        return None
    opening = line.rfind("(", 0, match.start())
    closing = line.find(")", match.end())
    if opening < 0 or closing < 0:
        return None
    contents = line[opening + 1 : closing]
    without = contents[: match.start() - opening - 1] + contents[match.end() - opening - 1 :]
    if not without.strip(" \t,"):
        return line[:opening] + line[closing + 1 :]
    definition = rf"\${re.escape(name)}\s*:\s*[\[\]!_A-Za-z][\[\]!_0-9A-Za-z]*"
    replacement = re.sub(rf",\s*{definition}", "", line, count=1)
    if replacement == line:
        replacement = re.sub(rf"{definition}\s*,\s*", "", line, count=1)
    return replacement if replacement != line else None


def _remove_argument(line: str, name: str) -> str:
    replacement = re.sub(
        rf",\s*\b{re.escape(name)}\s*:\s*\${re.escape(name)}\b", "", line, count=1
    )
    if replacement == line:
        replacement = re.sub(
            rf"\b{re.escape(name)}\s*:\s*\${re.escape(name)}\b\s*,\s*", "", line, count=1
        )
    return replacement
