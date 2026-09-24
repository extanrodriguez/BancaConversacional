from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.router.field_guardrails import (
    apply_card_digits_guardrail,
    apply_card_field_guardrail,
    apply_generic_balance_guardrail,
    apply_greeting_guardrail,
    apply_loan_fastpath_guardrail,
    apply_movements_guardrail,
    apply_specific_deposit_balance_guardrail,
    apply_transfer_guardrail,
    is_card_field_question,
    is_currency_switch_question,
    is_generic_balance_question,
    is_movements_question,
    is_specific_deposit_balance_question,
    is_transfer_question,
    run_field_fastpath,
)


def _andres_snapshot() -> CustomerContextSnapshot:
    products = (
        ProductSnapshot(
            product_id="11042010152142", product_type="SAVINGS",
            alias="Cuenta de Ahorros", currency="DOP", status="active",
            available_balance=Decimal("5267.58"),
        ),
        ProductSnapshot(
            product_id="21042020016468", product_type="SAVINGS",
            alias="Cuenta de Ahorros", currency="USD", status="active",
            available_balance=Decimal("0.24"),
        ),
        ProductSnapshot(
            product_id="250925031840000011", product_type="CREDIT_CARD",
            alias="Visa Bravo Santa Cruz", currency="DOP", status="active",
            available_balance=Decimal("83876.9"), credit_limit=Decimal("100000"),
            cutoff_day=1, card_mask="****3446",
        ),
        ProductSnapshot(
            product_id="220710021030100868", product_type="CREDIT_CARD",
            alias="Visa Full Car", currency="DOP", status="active",
            available_balance=Decimal("5052.43"), credit_limit=Decimal("5000"),
            cutoff_day=8, card_mask="****2240",
        ),
    )
    return CustomerContextSnapshot(
        customer_id="TEST-QA-001",
        display_name="Andres david",
        default_currency="DOP",
        products=products,
        loans=(),
    )


def test_generic_balance_clarifies_when_multiple() -> None:
    snap = _andres_snapshot()
    status, actions, text, sug = apply_generic_balance_guardrail(
        "CLARIFICATION_REQUIRED", [], snap, "¿Cuál es mi saldo?",
    )
    assert status == "CLARIFICATION_REQUIRED"
    assert actions
    assert actions[0].get("missing_requirements") == ["account_ref"]
    assert "terminada en" in (text or "").lower() or "deseas consultar" in (text or "").lower()
    assert "5267.58" not in (text or "")
    assert sug is None


def test_generic_balance_dame_el_balance_de_la_cuenta() -> None:
    """Bug APK: frase genérica no debe devolver una sola cuenta si hay 2+."""
    snap = _andres_snapshot()
    q = "dame el balance de la cuenta"
    assert is_generic_balance_question(q)
    assert not is_specific_deposit_balance_question(q)
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    status, _actions, text, _sug, step, *_rest = hit
    assert status == "CLARIFICATION_REQUIRED"
    assert step == "balance"
    assert "5267.58" not in (text or "")
    assert "52142" in (text or "") or "deseas consultar" in (text or "").lower()


def test_balance_cuenta_en_pesos_resolves_without_clarification() -> None:
    """Si hay 1 cuenta DOP y 1 USD, 'balance ... en pesos' debe devolver el saldo DOP."""
    snap = _andres_snapshot()
    q = "cual es el balance de la cuenta en pesos?"
    assert not is_generic_balance_question(q)
    assert is_specific_deposit_balance_question(q)
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    status, actions, text, _sug, step, intent, ref = hit
    assert status == "VALID_CONTRACT"
    assert step == "specific_balance"
    assert intent == "ACCOUNT_BALANCE_READ"
    assert ref == "11042010152142"
    assert "5267.58" in (text or "")
    assert "deseas consultar" not in (text or "").lower()
    assert actions[0].get("detected_entities", {}).get("account_ref") == "11042010152142"


def test_balance_cuenta_en_dolares_resolves_without_clarification() -> None:
    snap = _andres_snapshot()
    q = "cual es el balance de la cuenta en dolares?"
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    status, _actions, text, _sug, step, _intent, ref = hit
    assert status == "VALID_CONTRACT"
    assert step == "specific_balance"
    assert ref == "21042020016468"
    assert "0.24" in (text or "")
    assert "deseas consultar" not in (text or "").lower()


def test_generic_balance_single_account() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X", display_name="Pedro", default_currency="DOP",
        products=(ProductSnapshot(
            product_id="CA1", product_type="SAVINGS", alias="Cuenta de Ahorros",
            currency="DOP", status="active", available_balance=Decimal("100"),
        ),),
        loans=(),
    )
    status, _, text, _ = apply_generic_balance_guardrail(
        "CLARIFICATION_REQUIRED", [], snap, "¿Cuánto tengo?",
    )
    assert status == "VALID_CONTRACT"
    assert "100" in (text or "")


def test_card_limit_not_balance() -> None:
    assert is_card_field_question("¿Cuál es mi límite?")
    assert not is_generic_balance_question("¿Cuál es mi límite?")
    snap = _andres_snapshot()
    status, actions, text, _ = apply_card_field_guardrail(
        "NON_OPERATIONAL", [], snap, "¿Cuál es mi límite?",
    )
    assert status == "CLARIFICATION_REQUIRED"
    assert "tarjeta" in (text or "").lower()


def test_card_cutoff_single_card() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X", display_name="Pedro", default_currency="DOP",
        products=(ProductSnapshot(
            product_id="TC1", product_type="CREDIT_CARD", alias="Visa", currency="DOP",
            status="active", available_balance=Decimal("100"), credit_limit=Decimal("5000"),
            cutoff_day=15, card_mask="****1234",
        ),),
        loans=(),
    )
    status, actions, text, _ = apply_card_field_guardrail(
        "VALID_CONTRACT", [], snap, "¿Cuándo corta mi tarjeta?",
    )
    assert status == "VALID_CONTRACT"
    assert "15" in (text or "")


def test_movements_not_random_balance() -> None:
    snap = _andres_snapshot()
    status, actions, text, _ = apply_movements_guardrail(
        "VALID_CONTRACT", [], snap, "Muéstrame mis últimos movimientos",
    )
    assert "5267.58" not in (text or "")
    assert status == "CLARIFICATION_REQUIRED"
    assert "movimiento" in (text or "").lower()


def test_movements_single_account_not_available() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X", display_name="Pedro", default_currency="DOP",
        products=(ProductSnapshot(
            product_id="CA1", product_type="SAVINGS", alias="Cuenta de Ahorros",
            currency="DOP", status="active", available_balance=Decimal("100"),
        ),),
        loans=(),
    )
    status, actions, text, _ = apply_movements_guardrail(
        "VALID_CONTRACT", [], snap, "Muéstrame mis últimos movimientos",
    )
    assert "no está disponible" in (text or "").lower()
    assert "100" not in (text or "")


def test_revisa_not_card_limit() -> None:
    assert not is_card_field_question("Ahora revisa el de dólares")
    assert is_currency_switch_question("Ahora revisa el de dólares")


def test_greeting_fastpath() -> None:
    snap = _andres_snapshot()
    out = apply_greeting_guardrail(snap, "Hola")
    assert out is not None
    assert "Hola" in (out[2] or "")


def test_greeting_with_products_goes_to_portfolio() -> None:
    from genesis_cognitive.router.field_guardrails import (
        is_greeting_question,
        is_portfolio_list_question,
        run_field_fastpath,
    )

    q = "hola puedes darme informacion sobre mis productos?"
    assert is_portfolio_list_question(q)
    assert not is_greeting_question(q)
    snap = _andres_snapshot()
    fp = run_field_fastpath(snap, q, None)
    assert fp is not None
    assert fp[4] == "portfolio"
    assert fp[5] == "PORTFOLIO_LIST"
    assert "productos activos" in (fp[2] or "").lower()


def test_loan_fastpath_single_loan() -> None:
    from genesis_cognitive.context.customer_context_snapshot import LoanSnapshot
    snap = CustomerContextSnapshot(
        customer_id="M", display_name="Mario", default_currency="DOP",
        products=(ProductSnapshot(
            product_id="227615", product_type="LOAN", alias="Préstamo", currency="DOP",
            status="active", available_balance=Decimal("800000"),
        ),),
        loans=(LoanSnapshot(
            product_id="227615",
            loan_type="Préstamo",
            installment_amount=Decimal("32000.39"),
            annual_interest_rate=Decimal("10"),
            outstanding_principal=Decimal("29255.87"),
            delinquency_days=0,
            next_due_date="2026-04-07",
            disbursed_amount=Decimal("800000"),
        ),),
    )
    out = apply_loan_fastpath_guardrail(snap, "¿Cuánto debo de mi préstamo?")
    assert out is not None
    assert "29255" in (out[2] or "")


def _andres_savings_snapshot() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="TEST-QA-001",
        display_name="Andres david",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="11042010063641", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="DOP", status="active",
                available_balance=Decimal("265.46"),
            ),
            ProductSnapshot(
                product_id="11042010114371", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="DOP", status="active",
                available_balance=Decimal("9998.37"),
            ),
            ProductSnapshot(
                product_id="21042020016468", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="USD", status="active",
                available_balance=Decimal("0.24"),
            ),
        ),
        loans=(),
    )


def test_savings_type_clarifies_multiple_savings() -> None:
    snap = _andres_savings_snapshot()
    out = apply_specific_deposit_balance_guardrail(snap, "Dime el saldo de mi cuenta de ahorros")
    assert out is not None
    assert out[0] == "CLARIFICATION_REQUIRED"
    text = out[2] or ""
    assert "terminada en" in text.lower() or "deseas consultar" in text.lower()
    assert "265.46" not in text


def test_usd_account_balance_single() -> None:
    snap = _andres_savings_snapshot()
    out = apply_specific_deposit_balance_guardrail(snap, "¿Cuánto tengo en mi cuenta en dólares?")
    assert out is not None
    text = out[2] or ""
    assert "0.24" in text
    assert "USD" in text
    assert "265.46" not in text


def test_usd_account_balance_multi() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X", display_name="Lucia", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="21042020016468", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="USD", status="active",
                available_balance=Decimal("0.24"),
            ),
            ProductSnapshot(
                product_id="21042020099999", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="USD", status="active",
                available_balance=Decimal("100.00"),
            ),
        ),
        loans=(),
    )
    out = apply_specific_deposit_balance_guardrail(snap, "¿Cuánto tengo en dólares?")
    assert out is not None
    assert out[0] == "CLARIFICATION_REQUIRED"
    text = out[2] or ""
    assert "6468" in text or "9999" in text


def test_specific_balance_no_checking() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X", display_name="Andres david", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="11042010063641", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="DOP", status="active",
                available_balance=Decimal("265.46"),
            ),
            ProductSnapshot(
                product_id="11042010114371", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="DOP", status="active",
                available_balance=Decimal("9998.37"),
            ),
        ),
        loans=(),
    )
    out = apply_specific_deposit_balance_guardrail(snap, "Ahora dime la corriente")
    assert out is not None
    assert "no tienes cuentas corrientes" in (out[2] or "").lower()


def test_specific_balance_unknown_digits() -> None:
    snap = _andres_snapshot()
    out = apply_specific_deposit_balance_guardrail(snap, "Dime el saldo de la cuenta 1234")
    assert out is not None
    assert "no existe" in (out[2] or "").lower()
    assert "None" not in (out[2] or "")


def test_run_field_fastpath_loan_and_greeting() -> None:
    snap = _andres_snapshot()
    hit = run_field_fastpath(snap, "Hola", None)
    assert hit is not None
    assert hit[4] == "greeting"

    assert is_transfer_question("Necesito hacer una transferencia de mi cuenta X a mi cuenta Y")
    status, actions, msg = apply_transfer_guardrail("VALID_CONTRACT", [], "transferir dinero")
    assert status == "UNSUPPORTED"
    assert "transfer" in (msg or "").lower()


def test_multi_deposit_balance_row9() -> None:
    snap = CustomerContextSnapshot(
        customer_id="CARLOS", display_name="Carlos", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="11042010004587", product_type="SAVINGS", alias="Ahorros",
                currency="DOP", status="active",                 available_balance=Decimal("24980.15"),
                ledger_balance=Decimal("25100"),
            ),
            ProductSnapshot(
                product_id="11042020007731", product_type="CHECKING", alias="Corriente",
                currency="DOP", status="active", available_balance=Decimal("18250"),
                ledger_balance=Decimal("18250"),
            ),
        ),
        loans=(),
    )
    out = apply_specific_deposit_balance_guardrail(
        snap, "Dime el saldo de mi cuenta de ahorros 4587 y de mi corriente 7731",
    )
    assert out is not None
    text = out[2] or ""
    assert "4587" in text and "7731" in text
    assert out[0] == "VALID_CONTRACT"


def test_card_digits_row22() -> None:
    snap = CustomerContextSnapshot(
        customer_id="ELENA", display_name="Elena", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="TC1", product_type="CREDIT_CARD", alias="Visa", currency="DOP",
                status="active", available_balance=Decimal("5000"), card_mask="****6582",
            ),
            ProductSnapshot(
                product_id="TC2", product_type="CREDIT_CARD", alias="Visa Bravo", currency="DOP",
                status="active", available_balance=Decimal("10000"), card_mask="****9147",
            ),
        ),
        loans=(),
    )
    out = apply_card_field_guardrail("VALID_CONTRACT", [], snap, "Saldo de mi tarjeta 6582")
    assert out[0] == "VALID_CONTRACT"
    assert "6582" in (out[2] or "")

    out2 = apply_card_digits_guardrail(snap, "Ahora revisa la 9147")
    assert out2 is not None
    assert out2[0] == "VALID_CONTRACT"
    assert "9147" in (out2[2] or "")


def _two_credit_cards_snap() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="U1",
        display_name="usuario 1",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="TC6374",
                product_type="CREDIT_CARD",
                alias="Credito Joven Empleado",
                currency="DOP",
                status="active",
                card_mask="****6374",
                ledger_balance=Decimal("10000"),
                available_balance=Decimal("40000"),
                available_purchases_domestic=Decimal("40000"),
                credit_limit=Decimal("50000"),
            ),
            ProductSnapshot(
                product_id="TC7111",
                product_type="CREDIT_CARD",
                alias="Multicredito Empleado",
                currency="DOP",
                status="active",
                card_mask="****7111",
                ledger_balance=Decimal("5000"),
                available_balance=Decimal("15000"),
                available_purchases_domestic=Decimal("15000"),
                credit_limit=Decimal("20000"),
            ),
        ),
        loans=(),
    )


def test_debit_cards_not_credit_clarification() -> None:
    """'tarjetas de débito' no debe listar TC ni pedir elegir una."""
    from genesis_cognitive.router.field_guardrails import asks_personal_debit_cards

    q = (
        "Cuanto debo en mis tarjetas de debito y cual de ellas "
        "tiene mas credito disponible?"
    )
    assert asks_personal_debit_cards(q) is True
    snap = _two_credit_cards_snap()
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    text = (hit[2] or "").lower()
    assert hit[0] == "VALID_CONTRACT"
    assert "débito" in text or "debito" in text
    assert "quieres consultar" not in text
    assert "6374" not in (hit[2] or "")
    assert "7111" not in (hit[2] or "")
    assert "credit_card" not in text


def test_multi_card_aggregate_no_clarification() -> None:
    """Con varias TC, deuda + cuál tiene más disponible → resumen de todas."""
    q = (
        "Cuanto debo en mis tarjetas de credito y cual de ellas "
        "tiene mas credito disponible?"
    )
    snap = _two_credit_cards_snap()
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    text = hit[2] or ""
    low = text.lower()
    assert hit[0] == "VALID_CONTRACT"
    assert "quieres consultar" not in low
    assert "10000" in text.replace(",", "") or "10,000" in text
    assert "5000" in text.replace(",", "") or "5,000" in text
    assert "6374" in text and "7111" in text
    assert "más crédito disponible" in low or "mas credito disponible" in low
    assert "joven" in low or "6374" in text
