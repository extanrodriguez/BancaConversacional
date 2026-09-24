"""Genesis Contract 1.2.0 — operation_request adapter.

Maps cognitive pipeline output → operation_request 1.2 format.
NEVER executes against Core. Emits the request only.

Contract nature:
  - Query (requires_confirmation=false, next_action=execute_operation)
  - Mutant (requires_confirmation=true, next_action=await_confirmation)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Contract type mapping: intent_id → Genesis 1.2.0 operation
# ---------------------------------------------------------------------------

_INTENT_TO_OPERATION: dict[str, dict[str, Any]] = {
    "PORTFOLIO_LIST": {
        "operation_type": "PASSIVE_PORTFOLIO_QUERY",
        "contract_code": "P01",
        "nature": "query",
        "requires_confirmation": False,
        "next_action": "execute_operation",
    },
    "ACCOUNT_BALANCE_READ": {
        "operation_type": "ACCOUNT_QUERY",
        "contract_code": "P02",
        "nature": "query",
        "requires_confirmation": False,
        "next_action": "execute_operation",
    },
    "LOAN_DETAIL_READ": {
        "operation_type": "LOAN_QUERY",
        "contract_code": "P12",
        "nature": "query",
        "requires_confirmation": False,
        "next_action": "execute_operation",
    },
    "FEASIBILITY_READ": {
        "operation_type": "FEASIBILITY_QUERY",
        "contract_code": "P20",
        "nature": "query",
        "requires_confirmation": False,
        "next_action": "execute_operation",
    },
    "TRANSFER_BETWEEN_OWN_ACCOUNTS": {
        "operation_type": "TRANSFER_OWN_VALIDATE",
        "contract_code": "M01",
        "nature": "mutant",
        "requires_confirmation": True,
        "next_action": "await_confirmation",
    },
    "LOAN_PAYMENT_VALIDATE": {
        "operation_type": "LOAN_SERVICING_VALIDATE",
        "contract_code": "M10",
        "nature": "mutant",
        "requires_confirmation": True,
        "next_action": "await_confirmation",
    },
}


def build_operation_request(
    *,
    status: str,
    actions: list[dict[str, Any]],
    customer_id: str,
    conversation_id: str,
    turn_number: int,
    loan_detail: dict[str, Any] | None = None,
    customer_snapshot_summary: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Build a Genesis 1.2.0 operation_request from pipeline output.

    Returns None if status is not VALID_CONTRACT or no mappable intent.
    NEVER executes against Core.
    """
    if status != "VALID_CONTRACT":
        return None

    if not actions:
        return None

    action = actions[0]
    intent_id = action.get("intent_id", "")
    mapping = _INTENT_TO_OPERATION.get(intent_id)

    if mapping is None:
        return None

    entities = action.get("detected_entities", {})

    # Build operation-specific contract payload
    contract_payload = _build_contract_payload(
        intent_id=intent_id,
        entities=entities,
        loan_detail=loan_detail,
        customer_snapshot_summary=customer_snapshot_summary,
    )

    operation_request: dict[str, Any] = {
        "schema_version": "1.2.0",
        "request_id": request_id or str(uuid.uuid4()),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "operation": {
            "type": mapping["operation_type"],
            "contract_code": mapping["contract_code"],
            "nature": mapping["nature"],
            "requires_confirmation": mapping["requires_confirmation"],
            "next_action": mapping["next_action"],
        },
        "identity": {
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "turn_number": turn_number,
        },
        "capability": {
            "intent_id": intent_id,
            "capability_candidate": action.get("capability_candidate"),
            "selected_route": action.get("selected_route"),
            "confidence": action.get("confidence", 1.0),
        },
        "contract": contract_payload,
        "telemetry": {
            "cognitive_status": status,
            "pipeline_version": "0.8.0",
        },
    }

    return operation_request


def _build_contract_payload(
    *,
    intent_id: str,
    entities: dict[str, Any],
    loan_detail: dict[str, Any] | None,
    customer_snapshot_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the operation-specific contract payload."""

    if intent_id == "PORTFOLIO_LIST":
        return {
            "query_type": "full_portfolio",
            "include_balances": True,
            "include_loans": True,
        }

    if intent_id == "ACCOUNT_BALANCE_READ":
        return {
            "query_type": "account_balance",
            "account_ref": entities.get("account_ref"),
            "fields": ["available_balance", "ledger_balance", "hold_amount", "currency"],
        }

    if intent_id == "LOAN_DETAIL_READ":
        payload: dict[str, Any] = {
            "query_type": "loan_detail",
            "account_ref": entities.get("account_ref"),
            "fields": ["installment_amount", "outstanding_principal", "annual_interest_rate",
                       "next_due_date", "delinquency_days", "loan_type"],
        }
        if loan_detail:
            payload["snapshot_data"] = loan_detail
        return payload

    if intent_id == "FEASIBILITY_READ":
        return {
            "query_type": "feasibility_check",
            "loan_ref": entities.get("account_ref"),
            "comparison_type": "installment_vs_balance",
        }

    if intent_id in ("TRANSFER_BETWEEN_OWN_ACCOUNTS", "LOAN_PAYMENT_VALIDATE"):
        return {
            "operation_type": "validate_only",
            "source_account_ref": entities.get("source_account_ref") or entities.get("account_ref"),
            "destination_account_ref": entities.get("destination_account_ref"),
            "amount": entities.get("amount"),
            "currency": entities.get("currency"),
            "note": "VALIDATE ONLY — NO EXECUTION against Core",
        }

    return {"raw_entities": entities}
