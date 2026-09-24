"""Tests for app_channel options and disambiguation (Matriz_Cuentas)."""

from decimal import Decimal

from genesis_cognitive.context.app_channel import (
    assemble_app_channel,
    build_account_disambiguation_question,
    build_card_disambiguation_question,
    build_dap_disambiguation_question,
    build_loan_disambiguation_question,
    build_product_option,
    build_product_options,
    map_app_status,
)
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)


def _carlos_multi() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="CARLOS",
        display_name="Carlos",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="11042010004587", product_type="SAVINGS",
                alias="Cuenta de Ahorros", currency="DOP", status="active",
                available_balance=Decimal("24980.15"),
            ),
            ProductSnapshot(
                product_id="11042020007731", product_type="CHECKING",
                alias="Cuenta Corriente", currency="DOP", status="active",
                available_balance=Decimal("18250"),
            ),
        ),
        loans=(),
    )


def test_disambiguation_question_matriz_row7() -> None:
    snap = _carlos_multi()
    accounts = list(snap.products)
    q = build_account_disambiguation_question(accounts)
    assert "4587" in q
    assert "7731" in q
    assert "ahorros" in q.lower()
    assert "corriente" in q.lower()


def test_product_option_contract() -> None:
    p = _carlos_multi().products[0]
    opt = build_product_option(p, list(_carlos_multi().products))
    assert opt["product_type"] == "savings_account"
    assert opt["currency"] == "DOP"
    assert opt["label"].startswith("Cuenta de ahorro")
    assert "···" in opt["label"]
    assert opt["ref"].startswith("CUENTA_AHORRO_")
    assert opt["selection"]["selected_option_ref"] == opt["ref"]
    # Labels deben ser únicos cuando hay varias cuentas del mismo tipo
    opts = build_product_options(list(_carlos_multi().products))
    labels = [o["label"] for o in opts]
    assert len(labels) == len(set(labels))


def test_term_deposit_options_include_requested_field_and_currency() -> None:
    deposits = [
        ProductSnapshot(
            product_id="DAP05511", product_type="TERM_DEPOSIT",
            alias="Certificado", currency="DOP", status="active",
            interest_rate=Decimal("8.15"), maturity_date="2026-09-19",
        ),
        ProductSnapshot(
            product_id="DAP07248", product_type="TERM_DEPOSIT",
            alias="Certificado", currency="USD", status="active",
            interest_rate=Decimal("7.40"), maturity_date="2027-01-05",
        ),
    ]

    rates = build_product_options(deposits, question="cuál es la tasa de mis certificados")
    assert rates[0]["subtitle"] == "Tasa de interés: 8.15% · Moneda: DOP"
    assert rates[0]["context"] == {
        "field": "rate",
        "label": "Tasa de interés",
        "formatted_value": "8.15%",
        "currency": "DOP",
    }
    assert rates[0]["selection"]["message"] == (
        "¿Cuál es la tasa de interés de mi certificado de depósito (...05511)?"
    )

    maturities = build_product_options(deposits, question="cuándo vence mi depósito a plazo")
    assert maturities[0]["subtitle"] == "Vence: 19/09/2026 · Moneda: DOP"
    assert maturities[0]["selection"]["message"] == (
        "¿Cuándo vence mi certificado de depósito (...05511)?"
    )
    assert maturities[1]["context"]["formatted_value"] == "05/01/2027"


def test_payment_date_clarification_exposes_loan_options() -> None:
    products = (
        ProductSnapshot("LOAN27615", "LOAN", "Préstamo", "DOP", "active"),
        ProductSnapshot("LOAN90123", "LOAN", "Préstamo", "DOP", "active"),
    )
    snapshot = CustomerContextSnapshot(
        customer_id="726588",
        display_name="Félix",
        default_currency="DOP",
        products=products,
        loans=(
            LoanSnapshot(
                product_id="LOAN27615", loan_type="PERSONAL",
                installment_amount=None, annual_interest_rate=None,
                outstanding_principal=None, delinquency_days=0,
                next_due_date="2026-09-25",
            ),
            LoanSnapshot(
                product_id="LOAN90123", loan_type="PERSONAL",
                installment_amount=None, annual_interest_rate=None,
                outstanding_principal=None, delinquency_days=0,
                next_due_date="2026-10-01",
            ),
        ),
    )
    data = {
        "status": "CLARIFICATION_REQUIRED",
        "client_response": "¿Sobre cuál préstamo deseas consultar?",
        "clarifications": [{
            "missing_requirements": ["account_ref"],
            "suggested_question": "¿Sobre cuál préstamo deseas consultar?",
        }],
        "actions": [{"intent_id": "PAYMENT_DATE_READ"}],
    }

    result = assemble_app_channel(
        data, snapshot=snapshot, question="¿Cuál es mi fecha límite de pago?",
    )

    assert result["status"] == "requires_selection"
    assert len(result["options"]) == 2
    assert result["options"][0]["context"]["field"] == "due_date"


def test_assemble_app_channel_requires_selection() -> None:
    snap = _carlos_multi()
    data = {
        "status": "CLARIFICATION_REQUIRED",
        "client_response": "placeholder",
        "clarifications": [{
            "target_action_sequence": 1,
            "missing_requirements": ["account_ref"],
            "suggested_question": "x",
            "already_known": [],
        }],
        "actions": [{
            "intent_id": "ACCOUNT_BALANCE_READ",
            "detected_entities": {"account_ref": None},
        }],
        "conversation_id": "c1",
        "turn_number": 2,
    }
    app = assemble_app_channel(data, snapshot=snap, question="¿Cuál es mi saldo?")
    assert app["status"] == "requires_selection"
    # Intent operativo hacia el orquestador (no dominio ACCOUNTS)
    assert app["intent_id"] == "ACCOUNT_BALANCE_READ"
    assert len(app["options"]) == 2
    assert app["options"][0]["product_type"] in ("savings_account", "checking_account")
    assert app["clarifications"][0]["missing_requirements"] == ["tipo_de_cuenta"]
    assert "4587" in (app["client_response"] or "")
    assert app["content_format"] == "markdown"
    assert app["rich_content"]["version"] == "1.0"
    assert any(
        block["type"] == "card_group"
        for block in app["rich_content"]["blocks"]
    )


def test_map_app_status() -> None:
    assert map_app_status("CLARIFICATION_REQUIRED", has_options=True) == "requires_selection"
    assert map_app_status("VALID_CONTRACT", has_options=False) == "VALID_CONTRACT"


def test_card_disambiguation_question() -> None:
    cards = (
        ProductSnapshot(
            product_id="220710021030100868", product_type="CREDIT_CARD",
            alias="Visa", currency="DOP", status="active", card_mask="****6582",
        ),
        ProductSnapshot(
            product_id="250925031840000011", product_type="CREDIT_CARD",
            alias="Visa Bravo", currency="DOP", status="active", card_mask="****9147",
        ),
    )
    q = build_card_disambiguation_question(list(cards))
    assert "6582" in q
    assert "9147" in q
    assert q.count("\n• **") == 2
    assert "****" not in q


def test_loan_disambiguation_question() -> None:
    loans = (
        ProductSnapshot(product_id="PR00001", product_type="LOAN", alias="Préstamo personal", currency="DOP", status="active"),
        ProductSnapshot(product_id="PR00002", product_type="LOAN", alias="Préstamo hipotecario", currency="DOP", status="active"),
    )
    q = build_loan_disambiguation_question(list(loans))
    assert "personal" in q.lower()
    assert "hipotec" in q.lower()


def test_dap_disambiguation_question() -> None:
    daps = (
        ProductSnapshot(product_id="33012010005511", product_type="TERM_DEPOSIT", alias="DAP 12m", currency="DOP", status="active"),
        ProductSnapshot(product_id="33012010008842", product_type="TERM_DEPOSIT", alias="DAP USD", currency="USD", status="active"),
    )
    q = build_dap_disambiguation_question(list(daps))
    assert "5511" in q or "dap 12m" in q.lower()
    assert "8842" in q or "dap usd" in q.lower()
    assert "dap" in q.lower()


def test_assemble_app_channel_loans_requires_selection() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X",
        display_name="Ana",
        default_currency="DOP",
        products=(
            ProductSnapshot(product_id="PR00001", product_type="LOAN", alias="Personal", currency="DOP", status="active"),
            ProductSnapshot(product_id="PR00002", product_type="LOAN", alias="Hipotecario", currency="DOP", status="active"),
        ),
        loans=(),
    )
    data = {
        "status": "CLARIFICATION_REQUIRED",
        "client_response": "placeholder",
        "clarifications": [{
            "target_action_sequence": 1,
            "missing_requirements": ["account_ref"],
            "suggested_question": "x",
            "already_known": [],
        }],
        "actions": [{"intent_id": "LOAN_DETAIL_READ", "detected_entities": {"account_ref": None}}],
    }
    app = assemble_app_channel(data, snapshot=snap, question="¿Cuánto debo?")
    assert app["status"] == "requires_selection"
    assert app["intent_id"] == "LOAN_DETAIL_READ"
    assert app["clarifications"][0]["missing_requirements"] == ["tipo_de_prestamo"]


def test_assemble_app_channel_keeps_reclamacion_clarification() -> None:
    """Fase 1: clarificación de canal no debe reescribirse como selección de cuentas."""
    snap = _carlos_multi()
    msg = (
        "Puedes realizar tu reclamación por varios canales. ¿Cuál prefieres?\n"
        "• Centro de Contacto (809.726.1000)"
    )
    data = {
        "status": "CLARIFICATION_REQUIRED",
        "client_response": msg,
        "clarifications": [{
            "target_action_sequence": 1,
            "missing_requirements": ["reclamacion_channel"],
            "suggested_question": msg,
            "already_known": [],
        }],
        "actions": [{
            "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
            "detected_entities": {"account_ref": None, "knowledge_topic": "RECLAMACION_CHANNEL"},
        }],
        "conversation_id": "c-rec",
        "turn_number": 1,
    }
    app = assemble_app_channel(data, snapshot=snap, question="proceso para una reclamacion")
    assert app["status"] == "CLARIFICATION_REQUIRED"
    assert app["options"] == []
    assert "809.726.1000" in (app["client_response"] or "")
    assert "tel:+18097261000" in (app["client_response"] or "")
    assert app["rich_content"]["version"] == "1.0"
    assert "4587" not in (app["client_response"] or "")
    assert "terminada en" not in (app["client_response"] or "")


def test_current_social_intent_precedes_pending_product_intent() -> None:
    data = {
        "status": "NON_OPERATIONAL",
        "intent_id": "CHITCHAT_PRESENCE",
        "client_response": "Sí, aquí estoy. ¿En qué te puedo ayudar?",
        "actions": [],
        "conversation_id": "c-social",
        "turn_number": 2,
    }

    app = assemble_app_channel(
        data,
        snapshot=None,
        question="¿estás ahí?",
        pending_intent="TERM_DEPOSIT_DETAIL_READ",
    )

    assert app["intent_id"] == "CHITCHAT_PRESENCE"
    assert app["options"] == []
