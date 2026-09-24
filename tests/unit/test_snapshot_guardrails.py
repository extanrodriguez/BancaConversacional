"""Unit tests for snapshot_guardrails — no model, no network."""

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.router.snapshot_guardrails import apply_loan_guardrail
from decimal import Decimal


def _snapshot_1_loan() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="CUST002",
        display_name="Luis Pena",
        default_currency="DOP",
        products=(
            ProductSnapshot(product_id="COR002", product_type="CHECKING", alias="Corriente", currency="DOP", status="ACTIVE"),
            ProductSnapshot(product_id="PRE002Q", product_type="LOAN", alias="Credito Rapido", currency="DOP", status="ACTIVE"),
        ),
        loans=(
            LoanSnapshot(product_id="PRE002Q", loan_type="CREDITO_RAPIDO", installment_amount=Decimal("7800"), annual_interest_rate=Decimal("24.5"), outstanding_principal=Decimal("52000"), delinquency_days=0, next_due_date="2026-08-01"),
        ),
    )


def _snapshot_2_loans() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="CUST001",
        display_name="Ana Gomez",
        default_currency="DOP",
        products=(
            ProductSnapshot(product_id="COR001", product_type="CHECKING", alias="Corriente", currency="DOP", status="ACTIVE"),
            ProductSnapshot(product_id="PRE001", product_type="LOAN", alias="Libre Inversion", currency="DOP", status="ACTIVE"),
            ProductSnapshot(product_id="PRE001V", product_type="LOAN", alias="Vehiculo", currency="DOP", status="ACTIVE"),
        ),
        loans=(
            LoanSnapshot(product_id="PRE001", loan_type="LIBRE_INVERSION", installment_amount=Decimal("14500"), annual_interest_rate=Decimal("17.5"), outstanding_principal=Decimal("278000"), delinquency_days=0, next_due_date="2026-08-10"),
            LoanSnapshot(product_id="PRE001V", loan_type="VEHICULO", installment_amount=Decimal("31500"), annual_interest_rate=Decimal("15.2"), outstanding_principal=Decimal("980000"), delinquency_days=0, next_due_date="2026-08-05"),
        ),
    )


def test_loan_detail_read_1_loan_null_ref_forces():
    """1 LOAN + LOAN_DETAIL_READ + null ref → force PRE002Q."""
    actions = [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": None}}]
    result = apply_loan_guardrail("VALID_CONTRACT", actions, _snapshot_1_loan())
    assert result[0]["detected_entities"]["account_ref"] == "PRE002Q"


def test_loan_detail_read_1_loan_already_resolved():
    """1 LOAN + LOAN_DETAIL_READ + ref already set → no change."""
    actions = [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": "PRE002Q"}}]
    result = apply_loan_guardrail("VALID_CONTRACT", actions, _snapshot_1_loan())
    assert result[0]["detected_entities"]["account_ref"] == "PRE002Q"


def test_loan_detail_read_2_loans_null_ref_no_force():
    """2 LOANs + LOAN_DETAIL_READ + null ref → do NOT force."""
    actions = [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": None}}]
    result = apply_loan_guardrail("VALID_CONTRACT", actions, _snapshot_2_loans())
    assert result[0]["detected_entities"]["account_ref"] is None


def test_account_balance_read_not_touched():
    """ACCOUNT_BALANCE_READ → never touched, even with LOANs."""
    actions = [{"intent_id": "ACCOUNT_BALANCE_READ", "detected_entities": {"account_ref": None}}]
    result = apply_loan_guardrail("VALID_CONTRACT", actions, _snapshot_1_loan())
    assert result[0]["detected_entities"]["account_ref"] is None


def test_clarification_status_not_touched():
    """Non-VALID_CONTRACT status → no change."""
    actions = [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": None}}]
    result = apply_loan_guardrail("CLARIFICATION_REQUIRED", actions, _snapshot_1_loan())
    assert result[0]["detected_entities"]["account_ref"] is None


def test_no_snapshot_no_change():
    """None snapshot → no change."""
    actions = [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": None}}]
    result = apply_loan_guardrail("VALID_CONTRACT", actions, None)
    assert result[0]["detected_entities"]["account_ref"] is None


def test_empty_actions_no_crash():
    """Empty actions → no crash."""
    result = apply_loan_guardrail("VALID_CONTRACT", [], _snapshot_1_loan())
    assert result == []


def test_loan_field_question_detects_excel_cases():
    from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question

    assert is_loan_field_question("¿Cuándo vence mi próxima cuota?")
    assert is_loan_field_question("¿Cuánto tengo que pagar para saldar?")
    assert is_loan_field_question("¿Cuándo termina mi préstamo?")
    assert is_loan_field_question("Muéstrame los últimos movimientos del préstamo")
    assert is_loan_field_question("Cambia al personal")
    assert is_loan_field_question("Y del préstamo de vehículo?")
    assert is_loan_field_question("Dame todos los detalles de mi préstamo")
    assert not is_loan_field_question("requisitos para un crédito Hipotecario")
    assert not is_loan_field_question("Préstamo 12345")


def test_loan_field_one_loan_resolves_generic_clarification():
    from genesis_cognitive.router.snapshot_guardrails import apply_loan_field_guardrail

    status, actions, clars = apply_loan_field_guardrail(
        "CLARIFICATION_REQUIRED",
        [],
        _snapshot_1_loan(),
        "¿Cuándo vence mi próxima cuota?",
    )
    assert status == "VALID_CONTRACT"
    assert actions[0]["detected_entities"]["account_ref"] == "PRE002Q"
    assert clars == []


def test_loan_field_two_loans_clarifies():
    from genesis_cognitive.router.snapshot_guardrails import apply_loan_field_guardrail

    status, actions, clars = apply_loan_field_guardrail(
        "CLARIFICATION_REQUIRED",
        [],
        _snapshot_2_loans(),
        "¿Cuánto tengo que pagar para saldar?",
    )
    assert status == "CLARIFICATION_REQUIRED"
    assert clars
    assert "account_ref" in clars[0]["missing_requirements"]
    q = clars[0]["suggested_question"].lower()
    assert "consultar" in q or "préstamo" in q or "prestamo" in q


def test_loan_field_two_loans_uses_last_resolved():
    from genesis_cognitive.router.snapshot_guardrails import apply_loan_field_guardrail

    status, actions, clars = apply_loan_field_guardrail(
        "CLARIFICATION_REQUIRED",
        [],
        _snapshot_2_loans(),
        "¿Cuándo termina mi préstamo?",
        last_resolved_ref="PRE001V",
    )
    assert status == "VALID_CONTRACT"
    assert actions[0]["detected_entities"]["account_ref"] == "PRE001V"
    assert clars == []


def test_hipotecario_hint_resolves_among_many():
    from genesis_cognitive.router.snapshot_guardrails import resolve_loan_type_hint

    snap = CustomerContextSnapshot(
        customer_id="X",
        display_name="Sofia",
        default_currency="DOP",
        products=(
            ProductSnapshot(product_id="325056", product_type="LOAN", alias="Préstamo Hipotecario", currency="DOP", status="active"),
            ProductSnapshot(product_id="325057", product_type="LOAN", alias="Préstamo de Vehículo", currency="DOP", status="active"),
        ),
        loans=(),
    )
    actions = [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": None}}]
    status, result = resolve_loan_type_hint("CLARIFICATION_REQUIRED", actions, snap, "Cuánto debo del hipotecario?")
    assert status == "VALID_CONTRACT"
    assert result[0]["detected_entities"]["account_ref"] == "325056"
