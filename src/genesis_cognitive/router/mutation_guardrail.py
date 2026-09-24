"""Mutation guardrail — blocks ACCOUNT_MOVEMENTS_READ misused as transfer/mutation."""

from __future__ import annotations

from typing import Any


def block_movements_as_mutation(
    status: str,
    actions_dump: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Block ACCOUNT_MOVEMENTS_READ if it has amount or destination (mutation misuse).

    Returns (status, actions_dump, unsupported_segments).

    If ACCOUNT_MOVEMENTS_READ has amount or destination_account_ref set,
    the pipeline incorrectly mapped a mutation as a read → return UNSUPPORTED.
    """
    if status != "VALID_CONTRACT" or not actions_dump:
        return status, actions_dump, []

    action = actions_dump[0]
    if action.get("intent_id") != "ACCOUNT_MOVEMENTS_READ":
        return status, actions_dump, []

    entities = action.get("detected_entities", {})
    has_amount = entities.get("amount") is not None
    has_destination = entities.get("destination_account_ref") is not None

    if has_amount or has_destination:
        unsupported = [{
            "segment_description": "Operación de transferencia o pago no habilitada en este canal",
            "reason": "OPERATION_NOT_ENABLED",
        }]
        return "UNSUPPORTED", [], unsupported

    return status, actions_dump, []
