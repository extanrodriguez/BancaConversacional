"""Mapper: Core portfolio (context.data) → CustomerContextSnapshot.

Pure function. No I/O, no store writes.
Converts the raw Core products array into typed ProductSnapshot/LoanSnapshot tuples.

Status mapping:
  CA: 3=active, 2=inactive (+ letras A/I / ACTIVE)
  TC: 1=active, 2=inactive, 3=blocked, 4=delinquent (+ A/I)
  PR: 1=active, 2=closed, 3=delinquent (+ A/I)
  CD/DAP/DP: 1|3|A=active, 2|I=inactive
    Nota Core real: certificados suelen llegar con productStatus=\"A\" (no numérico).

Currency mapping:
  214=DOP, 840=USD (others: raw code as string)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)

# ---------------------------------------------------------------------------
# Currency codes (ISO 4217 numeric → alpha)
# ---------------------------------------------------------------------------

_CURRENCY_MAP: dict[int | str, str] = {
    214: "DOP",
    840: "USD",
    "214": "DOP",
    "840": "USD",
}


def _map_currency(code: Any) -> str:
    """Map numeric or string currency code to alpha. Unknown → raw string."""
    if code is None:
        return "DOP"  # Default for Dominican bank
    mapped = _CURRENCY_MAP.get(code)
    if mapped:
        return mapped
    # Try int conversion
    try:
        mapped = _CURRENCY_MAP.get(int(code))
        if mapped:
            return mapped
    except (ValueError, TypeError):
        pass
    return str(code)


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------

_CA_STATUS: dict[int | str, str] = {
    1: "active", "1": "active",  # tabla genérica API: 1=Activo
    3: "active", "3": "active",  # variante usada en cuentas de ahorro
    2: "inactive", "2": "inactive",
}

_TC_STATUS: dict[int | str, str] = {
    1: "active", "1": "active",
    2: "inactive", "2": "inactive",
    3: "blocked", "3": "blocked",
    4: "delinquent", "4": "delinquent",
}

_PR_STATUS: dict[int | str, str] = {
    1: "active", "1": "active",
    2: "closed", "2": "closed",
    3: "delinquent", "3": "delinquent",
}

_CD_STATUS: dict[int | str, str] = {
    1: "active", "1": "active",
    3: "active", "3": "active",
    "A": "active", "a": "active",
    "ACTIVE": "active", "active": "active",
    "ACTIVO": "active", "activo": "active",
    2: "inactive", "2": "inactive",
    "I": "inactive", "i": "inactive",
    "INACTIVE": "inactive", "inactive": "inactive",
    "INACTIVO": "inactive", "inactivo": "inactive",
}

# Fallback cuando Core manda letra/texto en vez del código numérico del catálogo.
_LETTER_STATUS: dict[str, str] = {
    "A": "active",
    "ACTIVE": "active",
    "ACTIVO": "active",
    "I": "inactive",
    "INACTIVE": "inactive",
    "INACTIVO": "inactive",
    "C": "closed",
    "CLOSED": "closed",
    "CERRADO": "closed",
}


def _normalize_status(category: str, raw_status: Any) -> str:
    """Normalize product status by category."""
    table: dict[int | str, str] | None = None
    if category in ("CA", "CC"):
        table = _CA_STATUS
    elif category == "TC":
        table = _TC_STATUS
    elif category == "PR":
        table = _PR_STATUS
    elif category in ("CD", "DAP", "DP"):
        table = _CD_STATUS

    if table is not None and raw_status in table:
        return table[raw_status]

    # Core a veces envía "A"/"I" (o ACTIVE) en vez de 1/2/3.
    if isinstance(raw_status, str):
        letter = _LETTER_STATUS.get(raw_status.strip().upper())
        if letter:
            return letter

    # Categoría CC usa la misma tabla de estados que CA.
    if category == "CC":
        if raw_status in _CA_STATUS:
            return _CA_STATUS[raw_status]

    return f"unknown({raw_status})"


# ---------------------------------------------------------------------------
# Category → product_type
# ---------------------------------------------------------------------------

_CATEGORY_TYPE: dict[str, str] = {
    "CA": "SAVINGS",  # Default; could be CHECKING/PAYROLL based on description
    "CC": "CHECKING",
    "TC": "CREDIT_CARD",
    "PR": "LOAN",
    "CD": "TERM_DEPOSIT",
    "DAP": "TERM_DEPOSIT",
    "DP": "TERM_DEPOSIT",
}


def _infer_product_type(category: str, description: str | None) -> str:
    """Infer product_type from category + description heuristics."""
    if category == "CC":
        return "CHECKING"
    if category == "CA":
        desc_lower = (description or "").lower()
        if "corriente" in desc_lower or "checking" in desc_lower:
            return "CHECKING"
        if "nómina" in desc_lower or "nomina" in desc_lower or "payroll" in desc_lower:
            return "PAYROLL"
        return "SAVINGS"
    return _CATEGORY_TYPE.get(category, "OTHER")


def _date_only(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _card_expiry(value: Any) -> str | None:
    """API cardExpiryDate is YYYYMM (number) or 0 if N/A → MM/YY."""
    if value is None or value == "" or value == 0 or value == "0":
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 6:
        return f"{digits[4:6]}/{digits[2:4]}"
    if len(digits) == 4:
        return f"{digits[0:2]}/{digits[2:4]}"
    return None


def _multi_currency(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return str(value).strip() in ("1", "true", "True", "YES", "yes")


def _nonzero_decimal(value: Any) -> Decimal | None:
    """Like _to_decimal but treats 0 as absent (API envía 0 cuando N/A)."""
    amount = _to_decimal(value)
    if amount is None or amount == 0:
        return None
    return amount


def _payoff_amount(domestic: Any, principal_raw: Any) -> Decimal | None:
    """Monto de cancelación solo si Core reporta total distinto del capital.

    `currentBalance` (capital pendiente) no es payoff. `domesticCurrencyBalance`
    acredita cancelación únicamente cuando difiere del capital. Si son iguales
    o falta domestic → None (el ejecutor declara limitación, no sustituye).
    """
    domestic_amt = _to_decimal(domestic)
    principal = _to_decimal(principal_raw)
    if domestic_amt is None:
        return None
    if principal is not None and domestic_amt == principal:
        return None
    return domestic_amt


def _last_four(product_id: str) -> str:
    digits = "".join(ch for ch in product_id if ch.isdigit())
    source = digits or product_id
    return source[-4:] if len(source) >= 4 else source


def extract_core_products(context_data: Any) -> tuple[list[Any], str]:
    """Accept orchestrator envelope, mapper fixture, or raw product list."""
    if isinstance(context_data, list):
        return context_data, "Cliente"
    if not isinstance(context_data, dict):
        return [], "Cliente"

    name = str(context_data.get("primerNombre") or "Cliente")
    products = context_data.get("products")
    if isinstance(products, list):
        return products, name

    inner = context_data.get("data")
    if isinstance(inner, list):
        return inner, name
    if isinstance(inner, dict):
        nested_name = str(inner.get("primerNombre") or name)
        nested_products = inner.get("products")
        if isinstance(nested_products, list):
            return nested_products, nested_name
        nested_data = inner.get("data")
        if isinstance(nested_data, list):
            return nested_data, nested_name
    return [], name


# ---------------------------------------------------------------------------
# Safe Decimal
# ---------------------------------------------------------------------------

def _to_decimal(value: Any) -> Decimal | None:
    """Safely convert to Decimal; return None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Main mapper
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MappedPortfolio:
    """Result of mapping Core portfolio to internal types."""

    snapshot: CustomerContextSnapshot
    active_count: int
    inactive_count: int
    total_count: int


def map_core_portfolio(context_data: Any) -> MappedPortfolio:
    """Map Core context.data → MappedPortfolio.

    Accepts:
    - {primerNombre, products: [...]}
    - envelope {isSucceded, data: [...]}
    - raw list of products
    """
    raw_products, display_name = extract_core_products(context_data)

    products: list[ProductSnapshot] = []
    loans: list[LoanSnapshot] = []
    active_count = 0
    inactive_count = 0
    default_currency = "DOP"

    for item in raw_products:
        if not isinstance(item, dict):
            continue

        category = str(item.get("productCategory", "")).upper()
        product_id = str(item.get("productIdentification", ""))
        description = item.get("productDescription")
        raw_status = item.get("productStatus")
        currency_code = item.get("currencyCode")

        if not product_id or not category:
            continue

        status = _normalize_status(category, raw_status)
        currency = _map_currency(currency_code)
        product_type = _infer_product_type(category, description)

        available_balance: Decimal | None = None
        ledger_balance: Decimal | None = None
        card_mask: str | None = None
        credit_limit: Decimal | None = None
        min_payment_rd: Decimal | None = None
        min_payment_us: Decimal | None = None
        statement_balance_rd: Decimal | None = None
        statement_balance_us: Decimal | None = None
        cutoff_day: int | None = None
        available_purchases_domestic: Decimal | None = None
        available_purchases_foreign: Decimal | None = None
        interest_rate: Decimal | None = None
        interest_amount: Decimal | None = None
        maturity_date = _date_only(item.get("maturityDate"))
        multi_currency = _multi_currency(item.get("multiCurrency"))
        foreign_currency_balance = _to_decimal(item.get("foreignCurrencyBalance"))
        domestic_currency_balance = _to_decimal(item.get("domesticCurrencyBalance"))
        card_expiry: str | None = None
        party_type = item.get("partyType")
        payment_due_date: str | None = None
        if isinstance(party_type, str):
            party_type = party_type.strip() or None
        else:
            party_type = None

        if category in ("CA", "CC"):
            available_balance = _to_decimal(item.get("availableBalance"))
            ledger_balance = _to_decimal(item.get("currentBalance"))
        elif category == "TC":
            credit_limit = _to_decimal(item.get("availableBalance"))
            available_purchases_domestic = _to_decimal(item.get("availablePurchasesDomestic"))
            available_purchases_foreign = _to_decimal(item.get("availablePurchasesForeign"))
            # available_balance en snapshot TC = disponible compras DOP (no el límite)
            available_balance = available_purchases_domestic
            ledger_balance = _to_decimal(item.get("currentBalance"))  # adeudado
            card_mask = item.get("maskedCardNumber")
            min_payment_rd = _to_decimal(item.get("minimumPaymentTcRd"))
            min_payment_us = _to_decimal(item.get("minimumPaymentTcUs"))
            statement_balance_rd = _to_decimal(item.get("statementBalanceTcRd"))
            statement_balance_us = _to_decimal(item.get("statementBalanceTcUs"))
            try:
                cutoff_day = int(item.get("statementCutoffDay") or 0) or None
            except (TypeError, ValueError):
                cutoff_day = None
            card_expiry = _card_expiry(item.get("cardExpiryDate"))
            interest_rate = _nonzero_decimal(
                item.get("interestRateTc") or item.get("interestRate")
            )
            # Core a menudo envía la fecha límite de pago en maturityDate (no hay
            # paymentDueDateTc en el contrato oficial). El plástico vence en cardExpiryDate.
            payment_due_date = _date_only(
                item.get("paymentDueDateTc")
                or item.get("paymentDueDate")
                or item.get("nextPaymentDateTc")
                or item.get("maturityDate")
            )
            # Evitar que «¿cuándo vence la tarjeta?» lea la fecha de pago.
            maturity_date = None
        elif category == "PR":
            available_balance = None
            ledger_balance = _to_decimal(item.get("currentBalance"))
        elif category in ("CD", "DAP", "DP"):
            available_balance = _to_decimal(item.get("currentBalance")) or _to_decimal(
                item.get("availableBalance")
            )
            ledger_balance = _to_decimal(item.get("currentBalance"))
            interest_rate = _nonzero_decimal(item.get("interestRateCd"))
            interest_amount = _nonzero_decimal(item.get("interestAmountCd"))

        last_four = _last_four(product_id)
        if isinstance(card_mask, str) and card_mask.strip():
            last_four = "".join(ch for ch in card_mask if ch.isdigit())[-4:] or last_four

        product = ProductSnapshot(
            product_id=product_id,
            product_type=product_type,
            alias=description,
            currency=currency,
            status=status,
            available_balance=available_balance,
            ledger_balance=ledger_balance,
            card_mask=card_mask,
            last_four=last_four,
            credit_limit=credit_limit,
            min_payment_rd=min_payment_rd,
            min_payment_us=min_payment_us,
            statement_balance_rd=statement_balance_rd,
            statement_balance_us=statement_balance_us,
            cutoff_day=cutoff_day,
            available_purchases_domestic=available_purchases_domestic,
            available_purchases_foreign=available_purchases_foreign,
            interest_rate=interest_rate,
            interest_amount=interest_amount,
            maturity_date=maturity_date,
            multi_currency=multi_currency,
            foreign_currency_balance=foreign_currency_balance,
            domestic_currency_balance=domestic_currency_balance,
            card_expiry=card_expiry,
            party_type=party_type,
            payment_due_date=payment_due_date,
        )
        products.append(product)

        if status == "active":
            active_count += 1
        else:
            inactive_count += 1

        if category == "PR":
            overdue = _to_decimal(item.get("pendingBalancePr"))
            has_overdue = overdue is not None and overdue > 0
            rate = _to_decimal(item.get("interestRatePr")) or Decimal("0")
            loan = LoanSnapshot(
                product_id=product_id,
                loan_type=description or "GENERAL",
                installment_amount=_nonzero_decimal(
                    item.get("installmentAmountPr")
                    or item.get("nextInstallmentAmountPr")
                    or item.get("cuotaPr")
                )
                or Decimal("0"),
                annual_interest_rate=rate,
                outstanding_principal=_to_decimal(item.get("currentBalance")) or Decimal("0"),
                delinquency_days=1 if (status == "delinquent" or has_overdue) else 0,
                next_due_date=_date_only(
                    item.get("nextPaymentDatePr") or item.get("nextInstallmentDatePr")
                ),
                disbursed_amount=_to_decimal(item.get("availableBalance")),
                payoff_amount=_payoff_amount(
                    item.get("domesticCurrencyBalance")
                    or item.get("payoffAmount")
                    or item.get("payoffBalance")
                    or item.get("totalPayoff"),
                    item.get("currentBalance"),
                ),
                maturity_date=maturity_date,
                last_four=last_four,
                overdue_amount=overdue if has_overdue else None,
            )
            loans.append(loan)

    # Determine default currency from majority
    if products:
        currencies = [p.currency for p in products]
        default_currency = max(set(currencies), key=currencies.count)

    snapshot = CustomerContextSnapshot(
        customer_id="",  # Caller sets this
        display_name=display_name,
        default_currency=default_currency,
        products=tuple(products),
        loans=tuple(loans),
    )

    return MappedPortfolio(
        snapshot=snapshot,
        active_count=active_count,
        inactive_count=inactive_count,
        total_count=len(products),
    )
