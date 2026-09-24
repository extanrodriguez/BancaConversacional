"""READ PATH: trusted session-scoped product context from Redis (via session store)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import SessionState


class ProductContextToolType(StrEnum):
    ALL = "ALL"
    ACCOUNT = "ACCOUNT"
    LOAN = "LOAN"
    CREDIT_CARD = "CREDIT_CARD"
    DEPOSIT = "DEPOSIT"


_ACCOUNT_TYPES = frozenset({"CHECKING", "SAVINGS", "PAYROLL"})


class SessionStoreReadProtocol(Protocol):
    def get_session(self, conversation_id: str) -> SessionState | None: ...


@dataclass(frozen=True)
class TrustedSessionIdentity:
    conversation_id: str
    customer_id: str


@dataclass(frozen=True)
class GetCustomerProductsQuery:
    product_type: ProductContextToolType = ProductContextToolType.ALL
    status: str | None = None
    currency: str | None = None
    fields: tuple[str, ...] = ()


class ProductContextService:
    """Read normalized product rows for Foundry tools — never trust LLM-supplied customer id."""

    def __init__(self, store: SessionStoreReadProtocol) -> None:
        self._store = store

    def resolve_trusted_identity(
        self,
        conversation_id: str,
        *,
        customer_id_hint: str | None = None,
    ) -> TrustedSessionIdentity | None:
        cid = (conversation_id or "").strip()
        if not cid:
            return None
        sess = self._store.get_session(cid)
        if sess is None:
            return None
        trusted_customer = (sess.customer_id or "").strip()
        if not trusted_customer:
            return None
        hint = (customer_id_hint or "").strip()
        if hint and hint != trusted_customer:
            return None
        return TrustedSessionIdentity(conversation_id=cid, customer_id=trusted_customer)

    def get_customer_products(
        self,
        identity: TrustedSessionIdentity,
        query: GetCustomerProductsQuery | None = None,
    ) -> dict[str, Any]:
        q = query or GetCustomerProductsQuery()
        sess = self._store.get_session(identity.conversation_id)
        if sess is None or sess.snapshot is None:
            return {
                "status": "NO_CONTEXT",
                "source": "REDIS",
                "product_type": q.product_type.value,
                "count": 0,
                "products": [],
                "message": "No hay contexto de cliente en sesión.",
            }
        snap = sess.snapshot
        if snap.customer_id != identity.customer_id:
            return {
                "status": "FORBIDDEN",
                "source": "REDIS",
                "product_type": q.product_type.value,
                "count": 0,
                "products": [],
                "message": "Identidad de sesión no coincide con el contexto almacenado.",
            }

        rows = self._collect_rows(snap, q.product_type)
        if q.status:
            st = q.status.strip().lower()
            rows = [r for r in rows if str(r.get("status", "")).lower() == st]
        if q.currency:
            cur = q.currency.strip().upper()
            rows = [r for r in rows if str(r.get("currency", "")).upper() == cur]

        if q.fields:
            allow = set(q.fields)
            rows = [{k: v for k, v in row.items() if k in allow or k in ("product_ref", "product_type")} for row in rows]

        return {
            "status": "OK",
            "source": "REDIS",
            "product_type": q.product_type.value,
            "count": len(rows),
            "products": rows,
        }

    def _collect_rows(
        self,
        snap: CustomerContextSnapshot,
        product_type: ProductContextToolType,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for p in snap.products:
            if self._matches_type(p.product_type, product_type):
                row = self._product_row(p)
                out.append(row)
                seen_refs.add(str(row["product_ref"]))
        if product_type in (ProductContextToolType.ALL, ProductContextToolType.LOAN):
            for loan in snap.loans:
                if loan.product_id in seen_refs:
                    continue
                out.append(self._loan_row(loan))
        return out

    @staticmethod
    def _matches_type(internal_type: str, tool_type: ProductContextToolType) -> bool:
        if tool_type == ProductContextToolType.ALL:
            return True
        if tool_type == ProductContextToolType.ACCOUNT:
            return internal_type in _ACCOUNT_TYPES
        if tool_type == ProductContextToolType.CREDIT_CARD:
            return internal_type == "CREDIT_CARD"
        if tool_type == ProductContextToolType.DEPOSIT:
            return internal_type == "TERM_DEPOSIT"
        if tool_type == ProductContextToolType.LOAN:
            return internal_type == "LOAN"
        return False

    @staticmethod
    def _dec(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)

    def _product_row(self, p: ProductSnapshot) -> dict[str, Any]:
        ref = p.product_id
        row: dict[str, Any] = {
            "product_ref": ref,
            "product_type": p.product_type,
            "currency": p.currency,
            "status": p.status,
            "alias": p.alias,
        }
        if p.product_type in _ACCOUNT_TYPES:
            row["available_balance"] = self._dec(p.available_balance)
            row["ledger_balance"] = self._dec(p.ledger_balance)
        elif p.product_type == "CREDIT_CARD":
            # Semántica API: credit_limit=availableBalance; ledger=currentBalance (adeudado);
            # available_balance/available_purchases_*=disponible compras.
            row["credit_limit"] = self._dec(p.credit_limit)
            row["ledger_balance"] = self._dec(p.ledger_balance)  # balance actual / adeudado
            row["current_balance"] = self._dec(p.ledger_balance)
            row["available_balance"] = self._dec(
                p.available_purchases_domestic
                if p.available_purchases_domestic is not None
                else p.available_balance
            )
            row["available_purchases_domestic"] = self._dec(p.available_purchases_domestic)
            row["available_purchases_foreign"] = self._dec(p.available_purchases_foreign)
            row["cutoff_day"] = p.cutoff_day
            row["statement_cutoff_day"] = p.cutoff_day
            row["payment_due_date"] = p.payment_due_date
            row["card_expiry"] = p.card_expiry
            row["min_payment_rd"] = self._dec(p.min_payment_rd)
            row["min_payment_us"] = self._dec(p.min_payment_us)
            row["statement_balance_rd"] = self._dec(p.statement_balance_rd)
            row["statement_balance_us"] = self._dec(p.statement_balance_us)
            row["multi_currency"] = p.multi_currency
            row["card_mask"] = p.card_mask
            row["foreign_currency_balance"] = self._dec(p.foreign_currency_balance)
            row["domestic_currency_balance"] = self._dec(p.domestic_currency_balance)
        elif p.product_type == "TERM_DEPOSIT":
            row["ledger_balance"] = self._dec(p.ledger_balance)
            row["available_balance"] = self._dec(p.available_balance)
            row["interest_rate"] = self._dec(p.interest_rate)
            row["interest_amount"] = self._dec(p.interest_amount)
            row["maturity_date"] = p.maturity_date
        elif p.product_type == "LOAN":
            row["ledger_balance"] = self._dec(p.ledger_balance)
            row["interest_rate"] = self._dec(p.interest_rate)
        return row

    def _loan_row(self, loan: LoanSnapshot) -> dict[str, Any]:
        return {
            "product_ref": loan.product_id,
            "product_type": "LOAN",
            "currency": "DOP",
            "status": "active" if loan.delinquency_days == 0 else "delinquent",
            "outstanding_balance": self._dec(loan.outstanding_principal),
            "interest_rate": self._dec(loan.annual_interest_rate),
            "next_due_date": loan.next_due_date,
            "loan_type": loan.loan_type,
        }
