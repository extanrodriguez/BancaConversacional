"""Unit tests for the same-currency transfer policy (directrices 236–241).

Tests evaluate_transfer_currency_policy() as a pure deterministic validator
that executes exclusively AFTER model interpretation.
No API calls. No model invocations.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from run_openai_semantic_preflight import (  # noqa: E402
    TransferCurrencyDecision,
    evaluate_transfer_currency_policy,
    validate_same_currency_transfer,
)


def _make_interpretation(
    source_ref: str | None = "COR001",
    dest_ref: str | None = "AHO001",
    amount: str | None = "500",
    currency: str | None = "DOP",
) -> dict[str, Any]:
    return {
        "mode": "SINGLE",
        "actions": [
            {
                "sequence": 1,
                "intent_id": "TRANSFER_BETWEEN_OWN_ACCOUNTS",
                "capability_candidate": "TRANSFER",
                "selected_route": "TRANSFER_CONTRACT_BUILDER",
                "detected_entities": {
                    "account_ref": None,
                    "source_account_ref": source_ref,
                    "destination_account_ref": dest_ref,
                    "amount": amount,
                    "currency": currency,
                    "knowledge_topic": None,
                },
                "missing_requirements": [],
                "depends_on": [],
                "confidence": 0.95,
            }
        ],
        "clarifications": [],
        "unsupported_segments": [],
    }


def _make_context(
    source_currency: str = "DOP",
    dest_currency: str = "DOP",
    source_ref: str = "COR001",
    dest_ref: str = "AHO001",
) -> dict[str, Any]:
    return {
        "products": [
            {
                "product_ref": source_ref,
                "product_type": "CHECKING",
                "label": "Cuenta corriente",
                "alias": "cuenta principal",
                "currency": source_currency,
                "operational_state": "ACTIVE",
                "recent_balance": "12500.75",
                "known_reserved_amount": "500.00",
            },
            {
                "product_ref": dest_ref,
                "product_type": "SAVINGS",
                "label": "Cuenta de ahorros",
                "alias": "mis ahorros",
                "currency": dest_currency,
                "operational_state": "ACTIVE",
                "recent_balance": "3200.25",
                "known_reserved_amount": "0",
            },
        ]
    }


class TestTransferCurrencyPolicy:
    """Tests for evaluate_transfer_currency_policy (directrices 236–241)."""

    def test_dop_to_dop_with_action_currency_dop(self) -> None:
        """DOP → DOP with action.currency=DOP: SAME_CURRENCY_TRANSFER."""
        interpretation = _make_interpretation(currency="DOP")
        context = _make_context(source_currency="DOP", dest_currency="DOP")
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.SAME_CURRENCY_TRANSFER
        # Boolean wrapper check
        assert validate_same_currency_transfer(interpretation, context) is True

    def test_usd_to_usd_with_action_currency_usd(self) -> None:
        """USD → USD with action.currency=USD: SAME_CURRENCY_TRANSFER."""
        interpretation = _make_interpretation(currency="USD")
        context = _make_context(source_currency="USD", dest_currency="USD")
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.SAME_CURRENCY_TRANSFER

    def test_dop_to_usd_is_fx_operation_required(self) -> None:
        """DOP → USD: FX_OPERATION_REQUIRED."""
        interpretation = _make_interpretation(currency="DOP")
        context = _make_context(source_currency="DOP", dest_currency="USD")
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.FX_OPERATION_REQUIRED
        # Boolean wrapper check
        assert validate_same_currency_transfer(interpretation, context) is False

    def test_dop_to_dop_with_action_currency_usd(self) -> None:
        """DOP → DOP with action.currency=USD: ACTION_CURRENCY_MISMATCH."""
        interpretation = _make_interpretation(currency="USD")
        context = _make_context(source_currency="DOP", dest_currency="DOP")
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.ACTION_CURRENCY_MISMATCH

    def test_dop_to_dop_with_malformed_currency(self) -> None:
        """DOP → DOP with action.currency='DOP},': INVALID_CURRENCY_OUTPUT."""
        interpretation = _make_interpretation(currency="DOP},")
        context = _make_context(source_currency="DOP", dest_currency="DOP")
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.INVALID_CURRENCY_OUTPUT

    def test_source_account_not_found(self) -> None:
        """Source account not in context: ACCOUNT_REFERENCE_NOT_FOUND."""
        interpretation = _make_interpretation(source_ref="UNKNOWN")
        context = _make_context()
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.ACCOUNT_REFERENCE_NOT_FOUND

    def test_destination_account_not_found(self) -> None:
        """Destination account not in context: ACCOUNT_REFERENCE_NOT_FOUND."""
        interpretation = _make_interpretation(dest_ref="UNKNOWN")
        context = _make_context()
        decision = evaluate_transfer_currency_policy(interpretation, context)
        assert decision is TransferCurrencyDecision.ACCOUNT_REFERENCE_NOT_FOUND

    def test_function_does_not_modify_inputs(self) -> None:
        """The function must not modify TurnInterpretation nor context."""
        interpretation = _make_interpretation(currency="DOP")
        context = _make_context(source_currency="DOP", dest_currency="DOP")

        interpretation_before = copy.deepcopy(interpretation)
        context_before = copy.deepcopy(context)

        evaluate_transfer_currency_policy(interpretation, context)

        assert interpretation == interpretation_before
        assert context == context_before


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
