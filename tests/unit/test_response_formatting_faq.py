"""Tests for markdown product formatting and FAQ KB."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import ProductSnapshot
from genesis_cognitive.context.response_formatting import build_rich_card_detail, format_money
from genesis_cognitive.router.faq_guardrail import match_faq


def test_format_money_rd() -> None:
    assert format_money(Decimal("50000"), "DOP") == "RD$50,000.00"
    assert format_money(Decimal("4498.44"), "DOP") == "RD$4,498.44"
    assert format_money(Decimal("50.19"), "USD") == "USD$50.19"


def test_rich_card_detail_markdown() -> None:
    card = ProductSnapshot(
        product_id="220818155480001032",
        product_type="CREDIT_CARD",
        alias="Visa Infinite",
        currency="DOP",
        status="active",
        available_balance=Decimal("4498.44"),
        ledger_balance=Decimal("49931.56"),
        card_mask="****6374",
        last_four="6374",
        credit_limit=Decimal("50000"),
        min_payment_rd=Decimal("0"),
        statement_balance_rd=Decimal("34780.48"),
        statement_balance_us=Decimal("50.19"),
        cutoff_day=8,
        available_purchases_domestic=Decimal("4498.44"),
        available_purchases_foreign=Decimal("449.81"),
    )
    text = build_rich_card_detail(card)
    assert "6374" in text
    assert "**RD$50,000.00**" in text
    assert "**RD$49,931.56**" in text
    assert "Saldo adeudado" in text or "Balance actual" in text
    assert "Último corte (USD)" in text
    assert "**USD$50.19**" in text
    assert "• Límite de crédito:" in text
    assert "Fecha de corte" in text


def test_faq_mission_from_excel() -> None:
    hit = match_faq("¿Cuál es la misión del Banco?")
    assert hit is not None
    assert "institución financiera" in hit["answer"].lower() or "institucion financiera" in hit["answer"].lower()
