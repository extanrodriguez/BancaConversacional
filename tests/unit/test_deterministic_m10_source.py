"""Unit tests for M10 deterministic dispatch — source account (desde) OBLIGATORIO."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.contracts.deterministic_dispatch import (
    build_dispatch_request,
    parse_command,
)


class TestM10WithSource:
    """M10 paga prestamo — 'desde' es OBLIGATORIO."""

    def test_parse_m10_with_desde(self) -> None:
        """'Paga prestamo PRE001 valor 14500 moneda DOP desde COR001' → source_account_id == COR001."""
        result = parse_command("Paga prestamo PRE001 valor 14500 moneda DOP desde COR001")
        assert result is not None
        assert result["contract_code"] == "M10"
        assert result["intent_id"] == "LOAN_PAYMENT_VALIDATE"
        assert result["contract"]["loan_id"] == "PRE001"
        assert result["contract"]["source_account_id"] == "COR001"
        assert result["contract"]["service_parameters"]["payment_amount"] == "14500"
        assert result["contract"]["service_parameters"]["currency"] == "DOP"

    def test_parse_m10_without_desde_returns_none(self) -> None:
        """'Paga prestamo PRE001 valor 14500 moneda DOP' (sin desde) → None."""
        result = parse_command("Paga prestamo PRE001 valor 14500 moneda DOP")
        assert result is None

    def test_dispatch_m10_with_source(self) -> None:
        """Full dispatch with source account populates source_account_id."""
        result = build_dispatch_request(
            customer_id="CUST001",
            conversation_id="test-conv",
            turn_number=1,
            command="Paga prestamo PRE001 valor 14500 moneda DOP desde COR001",
            phase="VALIDATE",
        )
        assert result["status"] == "CONTRACT_EMITTED"
        op = result["operation_request"]
        assert op["contract"]["source_account_id"] == "COR001"
        assert op["contract"]["loan_id"] == "PRE001"
        assert op["operation"] == "LOAN_SERVICING_VALIDATE"
        assert op["requires_confirmation"] is True

    def test_dispatch_m10_without_source_raises(self) -> None:
        """Dispatch without 'desde' raises ValueError (command not recognized)."""
        with pytest.raises(ValueError, match="Comando no reconocido"):
            build_dispatch_request(
                customer_id="CUST001",
                conversation_id="test-conv",
                turn_number=1,
                command="Paga prestamo PRE001 valor 14500 moneda DOP",
                phase="VALIDATE",
            )
