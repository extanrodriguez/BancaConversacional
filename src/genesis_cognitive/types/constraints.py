"""Reusable constrained types for the cognitive layer."""

from typing import Annotated

from pydantic import StringConstraints

# A requirement name: non-empty, max 128 chars
RequirementName = Annotated[str, StringConstraints(min_length=1, max_length=128)]

# A non-empty identifier that can be null
NonEmptyId = Annotated[str, StringConstraints(min_length=1)]

# Intent/capability name with pattern matching JSON Schema
CapabilityName = Annotated[
    str,
    StringConstraints(min_length=3, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{2,127}$"),
]

IntentName = Annotated[
    str,
    StringConstraints(min_length=3, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{2,127}$"),
]

# Entity name: non-empty, max 128
EntityName = Annotated[str, StringConstraints(min_length=1, max_length=128)]

# Canonical entity field names for already_known
ENTITY_FIELD_NAMES = frozenset(
    {
        "account_ref",
        "source_account_ref",
        "destination_account_ref",
        "amount",
        "currency",
        "knowledge_topic",
    }
)

EntityFieldName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
]
