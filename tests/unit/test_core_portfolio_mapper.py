"""Unit tests for core_portfolio_mapper — Bloque B."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.context.core_portfolio_mapper import (
    MappedPortfolio,
    map_core_portfolio,
    _map_currency,
    _normalize_status,
)


# ---------------------------------------------------------------------------
# Fixture 1: CA + TC (no loans)
# ---------------------------------------------------------------------------

FIXTURE_CA_TC = {
    "primerNombre": "Carlos",
    "resultCode": 0,
    "resultMessage": "Consulta realizada exitosamente.",
    "products": [
        {
            "productCategory": "CA",
            "productIdentification": "CTA001",
            "productDescription": "Cuenta de Ahorros Personal",
            "productStatus": 3,
            "currencyCode": 214,
            "availableBalance": 85000.50,
            "currentBalance": 86000.00,
        },
        {
            "productCategory": "CA",
            "productIdentification": "CTA002",
            "productDescription": "Cuenta Corriente Principal",
            "productStatus": 2,
            "currencyCode": 214,
            "availableBalance": 0,
            "currentBalance": 0,
        },
        {
            "productCategory": "TC",
            "productIdentification": "TC001",
            "productDescription": "Visa Gold",
            "productStatus": 1,
            "currencyCode": 840,
            "maskedCardNumber": "****1234",
            "availableBalance": 5000.00,
            "availablePurchasesDomestic": 4500.00,
            "availablePurchasesForeign": 3000.00,
            "minimumPaymentTcRd": 150.00,
            "statementBalanceTcRd": 2000.00,
        },
        {
            "productCategory": "TC",
            "productIdentification": "TC002",
            "productDescription": "Mastercard Platinum",
            "productStatus": 3,
            "currencyCode": 214,
            "maskedCardNumber": "****5678",
            "availableBalance": 0,
        },
    ],
}


# ---------------------------------------------------------------------------
# Fixture 2: CA + TC + PR (with loan)
# ---------------------------------------------------------------------------

FIXTURE_WITH_PR = {
    "primerNombre": "Maria",
    "resultCode": 0,
    "products": [
        {
            "productCategory": "CA",
            "productIdentification": "AHO008",
            "productDescription": "Ahorros Nómina",
            "productStatus": 3,
            "currencyCode": 214,
            "availableBalance": 45000.00,
            "currentBalance": 45000.00,
        },
        {
            "productCategory": "PR",
            "productIdentification": "PRE008V",
            "productDescription": "Credito Vehiculo",
            "productStatus": 1,
            "currencyCode": 214,
            "pendingBalancePr": 19800.00,
            "interestRatePr": 12.5,
            "nextPaymentDatePr": "2026-08-20",
            "nextInstallmentDatePr": "2026-08-20",
            "currentBalance": 350000.75,
        },
        {
            "productCategory": "PR",
            "productIdentification": "PRE009",
            "productDescription": "Prestamo Personal",
            "productStatus": 3,
            "currencyCode": 214,
            "pendingBalancePr": 8500.00,
            "interestRatePr": 18.0,
            "nextPaymentDatePr": "2026-07-15",
            "nextInstallmentDatePr": "2026-07-15",
            "currentBalance": 50000.00,
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCurrencyMapping:
    def test_214_is_dop(self) -> None:
        assert _map_currency(214) == "DOP"

    def test_840_is_usd(self) -> None:
        assert _map_currency(840) == "USD"

    def test_string_214(self) -> None:
        assert _map_currency("214") == "DOP"

    def test_unknown_code(self) -> None:
        assert _map_currency(978) == "978"

    def test_none_defaults_dop(self) -> None:
        assert _map_currency(None) == "DOP"


class TestStatusNormalization:
    def test_ca_3_active(self) -> None:
        assert _normalize_status("CA", 3) == "active"

    def test_ca_2_inactive(self) -> None:
        assert _normalize_status("CA", 2) == "inactive"

    def test_tc_1_active(self) -> None:
        assert _normalize_status("TC", 1) == "active"

    def test_tc_3_blocked(self) -> None:
        assert _normalize_status("TC", 3) == "blocked"

    def test_cd_letter_a_active(self) -> None:
        """Core BD: certificados con productStatus 'A' = activo."""
        assert _normalize_status("CD", "A") == "active"
        assert _normalize_status("DAP", "a") == "active"
        assert _normalize_status("DP", "ACTIVE") == "active"

    def test_cd_letter_i_inactive(self) -> None:
        assert _normalize_status("CD", "I") == "inactive"

    def test_ca_status_1_active(self) -> None:
        assert _normalize_status("CA", 1) == "active"
        assert _normalize_status("CA", "1") == "active"

    def test_cc_category_checking(self) -> None:
        result = map_core_portfolio(
            {
                "products": [
                    {
                        "productCategory": "CC",
                        "productIdentification": "2200112233",
                        "productDescription": "Cuenta Corriente",
                        "productStatus": "3",
                        "currencyCode": "214",
                        "availableBalance": 1500,
                        "currentBalance": 1500,
                    }
                ]
            }
        )
        assert result.snapshot.products[0].product_type == "CHECKING"
        assert result.snapshot.products[0].status == "active"

    def test_tc_expiry_and_multicurrency(self) -> None:
        result = map_core_portfolio(
            {
                "products": [
                    {
                        "productCategory": "TC",
                        "productIdentification": "220818155480001032",
                        "productDescription": "Visa Infinite",
                        "productStatus": "1",
                        "currencyCode": "214",
                        "availableBalance": 300000,
                        "currentBalance": 93863,
                        "multiCurrency": "1",
                        "foreignCurrencyBalance": 84,
                        "domesticCurrencyBalance": 62626.11,
                        "availablePurchasesDomestic": 12000,
                        "availablePurchasesForeign": 7916,
                        "cardExpiryDate": 202606,
                        "maskedCardNumber": "****1032",
                    }
                ]
            }
        )
        tc = result.snapshot.products[0]
        assert tc.credit_limit == Decimal("300000")
        assert tc.ledger_balance == Decimal("93863")
        assert tc.available_balance == Decimal("12000")
        assert tc.multi_currency is True
        assert tc.foreign_currency_balance == Decimal("84")
        assert tc.card_expiry == "06/26"

    def test_tc_maturity_date_maps_to_payment_due(self) -> None:
        """Core envía la fecha de pago TC en maturityDate (sin paymentDueDateTc)."""
        result = map_core_portfolio(
            {
                "products": [
                    {
                        "productCategory": "TC",
                        "productIdentification": "220709213940583959",
                        "productDescription": "Credito Joven Empleado",
                        "productStatus": "1",
                        "currencyCode": "214",
                        "availableBalance": 50000,
                        "currentBalance": 34529,
                        "maturityDate": "2026-09-03 00:00:00",
                        "statementCutoffDay": 8,
                        "cardExpiryDate": 202704,
                        "maskedCardNumber": "****6374",
                        "availablePurchasesDomestic": 15471,
                        "minimumPaymentTcRd": 0,
                        "statementBalanceTcRd": 50251.03,
                    }
                ]
            }
        )
        tc = result.snapshot.products[0]
        assert tc.payment_due_date == "2026-09-03"
        assert tc.card_expiry == "04/27"
        assert tc.cutoff_day == 8
        # No confundir fecha de pago con vencimiento contractual / plástico
        assert tc.maturity_date is None

    def test_tc_explicit_payment_due_prefers_over_maturity(self) -> None:
        result = map_core_portfolio(
            {
                "products": [
                    {
                        "productCategory": "TC",
                        "productIdentification": "TC1",
                        "productDescription": "Visa",
                        "productStatus": "1",
                        "currencyCode": "214",
                        "availableBalance": 1000,
                        "currentBalance": 100,
                        "maturityDate": "2026-09-03 00:00:00",
                        "paymentDueDateTc": "2026-09-15 00:00:00",
                        "cardExpiryDate": 202801,
                        "maskedCardNumber": "****1111",
                    }
                ]
            }
        )
        tc = result.snapshot.products[0]
        assert tc.payment_due_date == "2026-09-15"
        assert tc.maturity_date is None
        assert tc.card_expiry == "01/28"

    def test_cd_zero_interest_omitted(self) -> None:
        result = map_core_portfolio(
            {
                "products": [
                    {
                        "productCategory": "CD",
                        "productIdentification": "301",
                        "productDescription": "Certificado",
                        "productStatus": "A",
                        "currencyCode": 214,
                        "currentBalance": 1000,
                        "interestRateCd": 0,
                        "interestAmountCd": 0,
                    }
                ]
            }
        )
        dap = result.snapshot.products[0]
        assert dap.status == "active"
        assert dap.interest_rate is None
        assert dap.interest_amount is None

    def test_cd_product_status_a_maps_active_in_portfolio(self) -> None:
        result = map_core_portfolio(
            {
                "primerNombre": "ClienteCD",
                "products": [
                    {
                        "productCategory": "CD",
                        "productIdentification": "301234567890",
                        "productDescription": "Certificado a Plazo",
                        "productStatus": "A",
                        "currencyCode": "214",
                        "currentBalance": 150000.0,
                        "interestRateCd": 7.5,
                        "maturityDate": "2027-01-15 00:00:00",
                    }
                ],
            }
        )
        assert result.total_count == 1
        assert result.active_count == 1
        dap = result.snapshot.products[0]
        assert dap.product_type == "TERM_DEPOSIT"
        assert dap.status == "active"
        assert dap.available_balance == Decimal("150000.0")

    def test_tc_4_delinquent(self) -> None:
        assert _normalize_status("TC", 4) == "delinquent"

    def test_pr_1_active(self) -> None:
        assert _normalize_status("PR", 1) == "active"

    def test_pr_3_delinquent(self) -> None:
        assert _normalize_status("PR", 3) == "delinquent"


class TestFixtureCaTC:
    """Fixture 1: only CA + TC, no loans."""

    def test_total_count(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        assert result.total_count == 4

    def test_active_count(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        # CA CTA001 active(3), CA CTA002 inactive(2), TC TC001 active(1), TC TC002 blocked(3)
        assert result.active_count == 2

    def test_inactive_count(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        assert result.inactive_count == 2

    def test_no_loans(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        assert len(result.snapshot.loans) == 0

    def test_display_name(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        assert result.snapshot.display_name == "Carlos"

    def test_savings_type_from_description(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        cta001 = next(p for p in result.snapshot.products if p.product_id == "CTA001")
        assert cta001.product_type == "SAVINGS"

    def test_checking_type_from_description(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        cta002 = next(p for p in result.snapshot.products if p.product_id == "CTA002")
        assert cta002.product_type == "CHECKING"

    def test_tc_type(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        tc001 = next(p for p in result.snapshot.products if p.product_id == "TC001")
        assert tc001.product_type == "CREDIT_CARD"
        assert tc001.currency == "USD"

    def test_balance_mapping(self) -> None:
        result = map_core_portfolio(FIXTURE_CA_TC)
        cta001 = next(p for p in result.snapshot.products if p.product_id == "CTA001")
        assert cta001.available_balance == Decimal("85000.50")
        assert cta001.ledger_balance == Decimal("86000.00")


class TestFixtureWithPR:
    """Fixture 2: CA + PR (with loans)."""

    def test_total_count(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        assert result.total_count == 3

    def test_loan_count(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        assert len(result.snapshot.loans) == 2

    def test_active_loan(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        pre008 = next(l for l in result.snapshot.loans if l.product_id == "PRE008V")
        assert pre008.outstanding_principal == Decimal("350000.75")
        assert pre008.installment_amount == Decimal("0")  # cuota contractual no viene del API
        assert pre008.overdue_amount == Decimal("19800.00")  # pendingBalancePr = mora
        assert pre008.annual_interest_rate == Decimal("12.5")
        assert pre008.next_due_date == "2026-08-20"

    def test_delinquent_loan(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        pre009 = next(l for l in result.snapshot.loans if l.product_id == "PRE009")
        assert pre009.delinquency_days == 1  # status=delinquent → 1
        assert pre009.outstanding_principal == Decimal("50000.00")
        assert pre009.installment_amount == Decimal("0")
        assert pre009.overdue_amount == Decimal("8500.00")

    def test_display_name(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        assert result.snapshot.display_name == "Maria"

    def test_default_currency_majority(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        assert result.snapshot.default_currency == "DOP"

    def test_loan_product_type(self) -> None:
        result = map_core_portfolio(FIXTURE_WITH_PR)
        pr_product = next(p for p in result.snapshot.products if p.product_id == "PRE008V")
        assert pr_product.product_type == "LOAN"
        assert pr_product.status == "active"
        # Loans have ledger_balance = currentBalance (deuda total)
        assert pr_product.ledger_balance == Decimal("350000.75")
        assert pr_product.available_balance is None


class TestEdgeCases:
    """Edge cases and empty data."""

    def test_empty_products(self) -> None:
        result = map_core_portfolio({"products": []})
        assert result.total_count == 0
        assert result.snapshot.display_name == "Cliente"

    def test_missing_products_key(self) -> None:
        result = map_core_portfolio({"primerNombre": "Test"})
        assert result.total_count == 0

    def test_invalid_item_skipped(self) -> None:
        result = map_core_portfolio({"products": ["not_a_dict", None, 42]})
        assert result.total_count == 0

    def test_missing_id_skipped(self) -> None:
        result = map_core_portfolio({"products": [{"productCategory": "CA"}]})
        assert result.total_count == 0

    def test_orchestrator_envelope(self) -> None:
        envelope = {
            "isSucceded": True,
            "code": "EGEN000",
            "data": [
                {
                    "productCategory": "PR",
                    "productIdentification": "227615",
                    "productDescription": "Préstamo",
                    "productStatus": "1",
                    "currencyCode": "214",
                    "availableBalance": 800000,
                    "currentBalance": 29255.87,
                    "domesticCurrencyBalance": 32000.39,
                    "pendingBalancePr": 32000.39,
                    "interestRatePr": 10,
                    "nextPaymentDatePr": "2026-04-07 00:00:00",
                    "maturityDate": "2027-04-07 00:00:00",
                }
            ],
        }
        result = map_core_portfolio(envelope)
        assert result.total_count == 1
        loan = result.snapshot.loans[0]
        assert loan.outstanding_principal == Decimal("29255.87")
        assert loan.disbursed_amount == Decimal("800000")
        assert loan.payoff_amount == Decimal("32000.39")
        assert loan.installment_amount == Decimal("0")
        assert loan.overdue_amount == Decimal("32000.39")
        assert loan.next_due_date == "2026-04-07"
        assert loan.maturity_date == "2027-04-07"
        assert loan.last_four == "7615"


    def test_payoff_when_distinct_from_installment(self) -> None:
        envelope = {
            "data": [
                {
                    "productCategory": "PR",
                    "productIdentification": "325056",
                    "productDescription": "Préstamo Hipotecario",
                    "productStatus": "1",
                    "currencyCode": "214",
                    "currentBalance": 10245253.35,
                    "domesticCurrencyBalance": 10512521.36,
                    "pendingBalancePr": 248349.3,
                    "interestRatePr": 8,
                }
            ]
        }
        loan = map_core_portfolio(envelope).snapshot.loans[0]
        assert loan.payoff_amount == Decimal("10512521.36")
        assert loan.last_four == "5056"
