"""CustomerContextSnapshot — immutable snapshot of a customer's products and loans."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _dec_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _safe_last_four(raw: str | None, product_id: str) -> str:
    text = str(raw or "")
    if "-" in text:
        text = ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 4:
        return digits
    pid_digits = "".join(ch for ch in product_id if ch.isdigit())
    return pid_digits[-4:] if len(pid_digits) >= 4 else pid_digits


@dataclass(frozen=True)
class ProductSnapshot:
    """A single product visible in the customer context."""

    product_id: str
    product_type: str  # CHECKING, SAVINGS, LOAN, CREDIT_CARD, PAYROLL, TERM_DEPOSIT
    alias: str | None
    currency: str
    status: str
    available_balance: Decimal | None = None  # CA: disponible; TC: proxy compras DOP
    ledger_balance: Decimal | None = None  # CA/CD: saldo; TC: adeudado; PR: capital
    card_mask: str | None = None  # TC only: masked card number (e.g. ****1234)
    last_four: str | None = None
    credit_limit: Decimal | None = None  # TC: availableBalance del API
    min_payment_rd: Decimal | None = None
    min_payment_us: Decimal | None = None
    statement_balance_rd: Decimal | None = None
    statement_balance_us: Decimal | None = None
    cutoff_day: int | None = None
    available_purchases_domestic: Decimal | None = None
    available_purchases_foreign: Decimal | None = None
    interest_rate: Decimal | None = None
    interest_amount: Decimal | None = None
    maturity_date: str | None = None
    multi_currency: bool | None = None
    foreign_currency_balance: Decimal | None = None  # TC: porción USD adeudada
    domestic_currency_balance: Decimal | None = None  # TC/PR: porción/total DOP
    card_expiry: str | None = None  # TC: MM/YY
    party_type: str | None = None
    payment_due_date: str | None = None  # TC: fecha límite de pago (si Core/lab la envía)

    def public_mask(self) -> str:
        if self.card_mask:
            return self.card_mask
        if self.last_four:
            return f"terminada en {self.last_four}"
        return self.product_id[-4:] if len(self.product_id) >= 4 else self.product_id


@dataclass(frozen=True)
class LoanSnapshot:
    """Loan-specific data for a LOAN product.

    Nota API Productos:
    - availableBalance → monto original (disbursed_amount)
    - currentBalance → capital pendiente (outstanding_principal)
    - domesticCurrencyBalance → total adeudado c/ intereses (payoff_amount)
    - pendingBalancePr → monto en mora / vencido (overdue_amount), NO la cuota contractual
    - La cuota contractual no viene en el API → installment_amount=0 (se omite en UI)
    """

    product_id: str
    loan_type: str
    installment_amount: Decimal
    annual_interest_rate: Decimal
    outstanding_principal: Decimal
    delinquency_days: int
    next_due_date: str | None
    disbursed_amount: Decimal | None = None
    payoff_amount: Decimal | None = None
    maturity_date: str | None = None
    last_four: str | None = None
    overdue_amount: Decimal | None = None

    def to_detail_dict(self) -> dict[str, object]:
        """Fields the final-response agent is allowed to use. None means unavailable."""
        overdue = self.overdue_amount
        has_overdue = overdue is not None and overdue > 0
        return {
            "product_id": self.product_id,
            "loan_type": self.loan_type,
            # Cuota contractual: solo si > 0 (Core normalmente no la envía)
            "installment_amount": str(self.installment_amount) if self.installment_amount > 0 else None,
            "annual_interest_rate": str(self.annual_interest_rate) if self.annual_interest_rate > 0 else None,
            "outstanding_principal": str(self.outstanding_principal),
            "delinquency_days": self.delinquency_days,
            "next_due_date": self.next_due_date,
            "disbursed_amount": _dec_str(self.disbursed_amount),
            "payoff_amount": _dec_str(self.payoff_amount),
            "overdue_amount": _dec_str(overdue) if has_overdue else None,
            "maturity_date": self.maturity_date,
            "last_four": _safe_last_four(self.last_four, self.product_id),
            "status_label": "con atraso" if (self.delinquency_days > 0 or has_overdue) else "al dia",
        }


@dataclass(frozen=True)
class CustomerContextSnapshot:
    """Full customer context loaded from the data source.

    Immutable after construction. Does not contain balances (those belong to Core).
    Loans are included so the model can count products and resolve uniqueness.
    """

    customer_id: str
    display_name: str
    default_currency: str
    products: tuple[ProductSnapshot, ...]
    loans: tuple[LoanSnapshot, ...]
