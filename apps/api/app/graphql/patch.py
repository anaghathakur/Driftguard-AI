"""Conservative structured edits for statically parsed GraphQL documents."""

from __future__ import annotations

import re

from apps.api.app.schemas.patch import StructuredPatchEdit


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
