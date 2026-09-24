"""CD tasa/intereses + TC corte/balances/expiración — exposición completa de portafolio."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.product_context_service import (
    GetCustomerProductsQuery,
    ProductContextService,
    ProductContextToolType,
    TrustedSessionIdentity,
)
from genesis_cognitive.context.reactive_store import ReactiveSessionStore
from genesis_cognitive.context.response_formatting import (
    build_rich_card_detail,
    build_rich_deposit_detail,
)
from genesis_cognitive.router.final_response_agent import (
    build_card_detail_response,
    build_deposit_detail_response,
)


def test_cd_maps_rate_and_interest_amount() -> None:
    mapped = map_core_portfolio(
        {
            "products": [
                {
                    "productCategory": "CD",
                    "productIdentification": "104501000005511",
                    "productDescription": "Certificado de Depósito",
                    "currencyCode": "214",
                    "productStatus": "1",
                    "availableBalance": 150000,
                    "currentBalance": 180755.33,
                    "interestRateCd": 8.15,
                    "interestAmountCd": 3515.196096,
                    "maturityDate": "2026-09-19 00:00:00",
                }
            ]
        }
    )
    dap = mapped.snapshot.products[0]
    assert dap.interest_rate == Decimal("8.15")
    assert dap.interest_amount == Decimal("3515.196096")
    rich = build_rich_deposit_detail(dap)
    assert "8.15" in rich
    assert "Intereses acumulados" in rich
    assert "3,515" in rich or "3515" in rich.replace(",", "")


def test_cd_compound_rate_and_interest_response() -> None:
    dap = ProductSnapshot(
        product_id="CD1",
        product_type="TERM_DEPOSIT",
        alias="Certificado de Depósito",
        currency="DOP",
        status="active",
        available_balance=Decimal("180755.33"),
        ledger_balance=Decimal("180755.33"),
        interest_rate=Decimal("8.15"),
        interest_amount=Decimal("3515.196096"),
        maturity_date="2026-09-19",
    )
    text = build_deposit_detail_response(
        "cual es la tasa de interes y los intereses acumulados de mi certificado",
        dap,
        "Cliente",
        "Certificado (...5511)",
    )
    low = text.lower()
    assert "8.15" in text
    assert "acumulad" in low
    assert "3515" in text.replace(",", "") or "3,515" in text


def test_tc_maps_cutoff_balances_expiry() -> None:
    mapped = map_core_portfolio(
        {
            "products": [
                {
                    "productCategory": "TC",
                    "productIdentification": "250906114000000305",
                    "productDescription": "Visa Bravo Santa Cruz",
                    "currencyCode": "214",
                    "productStatus": "1",
                    "availableBalance": 30000,
                    "maturityDate": "2026-08-27 00:00:00",
                    "currentBalance": 5738.13,
                    "availablePurchasesDomestic": 24261.87,
                    "availablePurchasesForeign": 402.61,
                    "maskedCardNumber": "**6203",
                    "statementBalanceTcRd": 21119.82,
                    "statementBalanceTcUs": 85.3,
                    "statementCutoffDay": 1,
                    "cardExpiryDate": 203009,
                    "multiCurrency": "1",
                }
            ]
        }
    )
    tc = mapped.snapshot.products[0]
    assert tc.credit_limit == Decimal("30000")
    assert tc.ledger_balance == Decimal("5738.13")
    assert tc.available_purchases_domestic == Decimal("24261.87")
    assert tc.cutoff_day == 1
    assert tc.card_expiry == "09/30"
    assert tc.payment_due_date == "2026-08-27"
    rich = build_rich_card_detail(tc)
    assert "Fecha de corte" in rich and "1" in rich
    assert "09/30" in rich or "expir" in rich.lower()
    assert "Balance actual" in rich or "Saldo adeudado" in rich
    assert "30,000" in rich or "30000" in rich.replace(",", "")


def test_tc_field_questions_return_portfolio_data() -> None:
    card = ProductSnapshot(
        product_id="TC6203",
        product_type="CREDIT_CARD",
        alias="Visa Bravo Santa Cruz",
        currency="DOP",
        status="active",
        card_mask="**6203",
        credit_limit=Decimal("30000"),
        ledger_balance=Decimal("5738.13"),
        available_balance=Decimal("24261.87"),
        available_purchases_domestic=Decimal("24261.87"),
        cutoff_day=1,
        card_expiry="09/30",
        payment_due_date="2026-08-27",
        statement_balance_rd=Decimal("21119.82"),
    )
    cutoff = build_card_detail_response(
        "cual es la fecha de corte", card, "Cliente", "Visa Bravo (**6203)"
    )
    assert "1" in cutoff and "corte" in cutoff.lower()
    actual = build_card_detail_response(
        "cual es el balance actual", card, "Cliente", "Visa Bravo (**6203)"
    )
    assert "5738" in actual.replace(",", "") or "5,738" in actual
    expiry = build_card_detail_response(
        "cuando expira mi tarjeta", card, "Cliente", "Visa Bravo (**6203)"
    )
    assert "09/30" in expiry
    avail = build_card_detail_response(
        "cual es el balance disponible", card, "Cliente", "Visa Bravo (**6203)"
    )
    assert "24261" in avail.replace(",", "") or "24,261" in avail


def test_product_context_exposes_cd_interest_and_tc_fields() -> None:
    store = ReactiveSessionStore(session_ttl_s=3600.0)
    snap = CustomerContextSnapshot(
        customer_id="726588",
        display_name="Cliente",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CD1",
                product_type="TERM_DEPOSIT",
                alias="Certificado",
                currency="DOP",
                status="active",
                ledger_balance=Decimal("180755.33"),
                interest_rate=Decimal("8.15"),
                interest_amount=Decimal("3515.19"),
                maturity_date="2026-09-19",
            ),
            ProductSnapshot(
                product_id="TC1",
                product_type="CREDIT_CARD",
                alias="Visa Bravo",
                currency="DOP",
                status="active",
                credit_limit=Decimal("30000"),
                ledger_balance=Decimal("5738.13"),
                available_purchases_domestic=Decimal("24261.87"),
                cutoff_day=1,
                card_expiry="09/30",
                statement_balance_rd=Decimal("21119.82"),
            ),
        ),
        loans=(),
    )
    sess = store.create_session("conv-x", "726588")
    sess.snapshot = snap
    store.put_session("conv-x", sess)
    svc = ProductContextService(store)
    identity = TrustedSessionIdentity(conversation_id="conv-x", customer_id="726588")

    dep = svc.get_customer_products(
        identity, GetCustomerProductsQuery(product_type=ProductContextToolType.DEPOSIT)
    )
    assert dep["count"] == 1
    assert dep["products"][0]["interest_rate"] == 8.15
    assert dep["products"][0]["interest_amount"] == 3515.19

    cards = svc.get_customer_products(
        identity, GetCustomerProductsQuery(product_type=ProductContextToolType.CREDIT_CARD)
    )
    row = cards["products"][0]
    assert row["credit_limit"] == 30000.0
    assert row["current_balance"] == 5738.13
    assert row["cutoff_day"] == 1
    assert row["card_expiry"] == "09/30"
    assert row["available_purchases_domestic"] == 24261.87
