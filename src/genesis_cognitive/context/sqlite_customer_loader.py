"""SqliteCustomerContextLoader — loads CustomerContextSnapshot from demo SQLite (read-only)."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)


class SqliteCustomerContextLoader:
    """Loads customer context from the demo SQLite database.

    Read-only. Does not modify the database.
    Uses Decimal for monetary amounts.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def load(self, customer_id: str) -> CustomerContextSnapshot | None:
        """Load snapshot for a customer_id. Returns None if not found."""
        uri = f"file:{self._db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return self._load_internal(conn, customer_id)
        finally:
            conn.close()

    def _load_internal(
        self, conn: sqlite3.Connection, customer_id: str
    ) -> CustomerContextSnapshot | None:
        cur = conn.cursor()

        # Load customer
        cur.execute(
            "SELECT customer_id, display_name, default_currency "
            "FROM customers WHERE customer_id = ?",
            (customer_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        display_name: str = row["display_name"]
        default_currency: str = row["default_currency"]

        # Load products (ACTIVE only) with account balances
        cur.execute(
            "SELECT p.product_id, p.product_type, p.alias, p.currency, p.status, "
            "       a.available_balance, a.ledger_balance "
            "FROM products p "
            "LEFT JOIN accounts a ON p.product_id = a.product_id "
            "WHERE p.customer_id = ? AND p.status = 'ACTIVE'",
            (customer_id,),
        )
        products = tuple(
            ProductSnapshot(
                product_id=r["product_id"],
                product_type=r["product_type"],
                alias=r["alias"],
                currency=r["currency"],
                status=r["status"],
                available_balance=Decimal(str(r["available_balance"])) if r["available_balance"] is not None else None,
                ledger_balance=Decimal(str(r["ledger_balance"])) if r["ledger_balance"] is not None else None,
            )
            for r in cur.fetchall()
        )

        # Load loans (join with products to filter by customer)
        cur.execute(
            "SELECT l.product_id, l.loan_type, l.installment_amount, "
            "       l.annual_interest_rate, l.outstanding_principal, "
            "       l.delinquency_days, l.next_due_date "
            "FROM loans l JOIN products p ON l.product_id = p.product_id "
            "WHERE p.customer_id = ?",
            (customer_id,),
        )
        loans = tuple(
            LoanSnapshot(
                product_id=r["product_id"],
                loan_type=r["loan_type"],
                installment_amount=Decimal(str(r["installment_amount"])),
                annual_interest_rate=Decimal(str(r["annual_interest_rate"])),
                outstanding_principal=Decimal(str(r["outstanding_principal"])),
                delinquency_days=int(r["delinquency_days"]),
                next_due_date=r["next_due_date"],
            )
            for r in cur.fetchall()
        )

        return CustomerContextSnapshot(
            customer_id=customer_id,
            display_name=display_name,
            default_currency=default_currency,
            products=products,
            loans=loans,
        )
