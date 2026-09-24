"""Unit tests for enforce_deposit_clarification — no model, no network."""

from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.router.deposit_guardrail import enforce_deposit_clarification


def _snapshot_3_deposits() -> CustomerContextSnapshot:
    """CUST001-like: 3 DOP deposit accounts + 2 loans."""
    return CustomerContextSnapshot(
        customer_id="CUST001",
        display_name="Ana Gomez",
        default_currency="DOP",
        products=(
            ProductSnapshot(product_id="COR001", product_type="CHECKING", alias="Cuenta corriente principal", currency="DOP", status="ACTIVE"),
            ProductSnapshot(product_id="NOM001", product_type="PAYROLL", alias="Cuenta de nomina", currency="DOP", status="ACTIVE"),
            ProductSnapshot(product_id="AHO001", product_type="SAVINGS", alias="Ahorros de emergencia", currency="DOP", status="ACTIVE"),
            ProductSnapshot(product_id="PRE001", product_type="LOAN", alias="Prestamo Libre Inversion", currency="DOP", status="ACTIVE"),
        ),
        loans=(
            LoanSnapshot(product_id="PRE001", loan_type="LIBRE_INVERSION", installment_amount=Decimal("14500"), annual_interest_rate=Decimal("17.5"), outstanding_principal=Decimal("278000"), delinquency_days=0, next_due_date="2026-08-10"),
        ),
    )


def _snapshot_1_deposit() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="CUST099",
        display_name="Solo Una",
        default_currency="DOP",
        products=(
            ProductSnapshot(product_id="COR099", product_type="CHECKING", alias="Unica cuenta", currency="DOP", status="ACTIVE"),
        ),
        loans=(),
    )


def _action(intent_id: str = "ACCOUNT_BALANCE_READ", ref: str | None = "COR001") -> list[dict]:
    return [{"intent_id": intent_id, "detected_entities": {"account_ref": ref, "amount": None, "destination_account_ref": None}}]


def test_force_clarification_generic_saldo():
    """'saldo de mi cuenta?' + 3 deposits + COR001 → CLARIFICATION."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "COR001"),
        _snapshot_3_deposits(), "saldo de mi cuenta?", has_pending=False,
    )
    assert status == "CLARIFICATION_REQUIRED"
    assert actions == []
    assert len(clars) == 1
    assert "account_ref" in clars[0]["missing_requirements"]
    assert "Cuenta corriente principal" in clars[0]["suggested_question"]


def test_allow_with_explicit_type_ahorros():
    """'saldo de mi cuenta de ahorros?' + AHO001 → VALID (match unico 'ahorro')."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "AHO001"),
        _snapshot_3_deposits(), "saldo de mi cuenta de ahorros?", has_pending=False,
    )
    assert status == "VALID_CONTRACT"
    assert clars == []


def test_allow_with_alias_match():
    """'Ahorros de emergencia' matches only AHO001 → VALID."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "AHO001"),
        _snapshot_3_deposits(), "Ahorros de emergencia", has_pending=False,
    )
    assert status == "VALID_CONTRACT"


def test_allow_with_product_id():
    """'AHO001' in text → VALID."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "AHO001"),
        _snapshot_3_deposits(), "AHO001", has_pending=False,
    )
    assert status == "VALID_CONTRACT"


def test_allow_pending_continuation():
    """has_pending=True → never force (exception 1)."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "COR001"),
        _snapshot_3_deposits(), "saldo de mi cuenta?", has_pending=True,
    )
    assert status == "VALID_CONTRACT"
    assert clars == []


def test_allow_single_deposit():
    """Only 1 deposit → OK regardless of text."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "COR099"),
        _snapshot_1_deposit(), "saldo de mi cuenta?", has_pending=False,
    )
    assert status == "VALID_CONTRACT"


def test_no_touch_loan_intent():
    """LOAN_DETAIL_READ → never touched."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("LOAN_DETAIL_READ", "PRE001"),
        _snapshot_3_deposits(), "cuota de mi prestamo", has_pending=False,
    )
    assert status == "VALID_CONTRACT"
    assert clars == []


def test_no_touch_null_ref():
    """account_ref=null → nothing to force."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", None),
        _snapshot_3_deposits(), "saldo de mi cuenta?", has_pending=False,
    )
    assert status == "VALID_CONTRACT"


def test_force_corriente_not_typed():
    """'mi cuenta' doesn't uniquely identify (matches corriente alias substring)
    but also matches others? Actually 'cuenta' appears in all aliases.
    With 3 deposits all having 'cuenta' in alias → force CLARIFICATION."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "COR001"),
        _snapshot_3_deposits(), "mi cuenta", has_pending=False,
    )
    # "cuenta" matches COR001 alias "Cuenta corriente principal" AND NOM001 "Cuenta de nomina"
    # → 2+ candidates → FORCE
    assert status == "CLARIFICATION_REQUIRED"


def test_allow_corriente_explicit():
    """'cuenta corriente' matches only COR001 → VALID."""
    status, actions, clars = enforce_deposit_clarification(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", "COR001"),
        _snapshot_3_deposits(), "saldo de mi cuenta corriente", has_pending=False,
    )
    assert status == "VALID_CONTRACT"
