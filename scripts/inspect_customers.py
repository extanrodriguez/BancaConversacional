"""Inspect CUST001 and CUST002 products and loans."""
import sqlite3

conn = sqlite3.connect(r"data/demo/modelo_bancario_genesis_v2.sqlite")
cur = conn.cursor()

for cust in ("CUST001", "CUST002"):
    print(f"=== {cust} products ===")
    cur.execute("SELECT product_id, product_type, alias, currency, status FROM products WHERE customer_id=?", (cust,))
    for r in cur.fetchall():
        print(f"  {r}")

    print(f"=== {cust} loans ===")
    cur.execute("""
        SELECT l.product_id, l.loan_type, l.installment_amount, l.annual_interest_rate,
               l.outstanding_principal, l.delinquency_days, l.next_due_date
        FROM loans l JOIN products p ON l.product_id = p.product_id
        WHERE p.customer_id = ?
    """, (cust,))
    for r in cur.fetchall():
        print(f"  {r}")
    print()

conn.close()
