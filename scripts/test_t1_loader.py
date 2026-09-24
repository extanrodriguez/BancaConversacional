"""Quick verification that T1 models + loader + store work."""
import sys
from pathlib import Path

sys.path.insert(0, "src")

from genesis_cognitive.context.sqlite_customer_loader import SqliteCustomerContextLoader
from genesis_cognitive.context.customer_context_store import CustomerContextStore

loader = SqliteCustomerContextLoader(Path("data/demo/modelo_bancario_genesis_v2.sqlite"))

# CUST001
snap = loader.load("CUST001")
assert snap is not None
print(f"CUST001: {snap.display_name}, currency={snap.default_currency}")
print(f"  products: {len(snap.products)}")
for p in snap.products:
    print(f"    {p.product_id} {p.product_type} alias={p.alias} {p.currency}")
print(f"  loans: {len(snap.loans)}")
for ln in snap.loans:
    print(f"    {ln.product_id} {ln.loan_type} cuota={ln.installment_amount}")

# CUST002
snap2 = loader.load("CUST002")
assert snap2 is not None
print(f"\nCUST002: {snap2.display_name}, currency={snap2.default_currency}")
print(f"  products: {len(snap2.products)}, loans: {len(snap2.loans)}")
for ln in snap2.loans:
    print(f"    {ln.product_id} {ln.loan_type} cuota={ln.installment_amount}")

# NONEXISTENT
snap_none = loader.load("NONEXISTENT")
assert snap_none is None
print("\nNONEXISTENT: None (correct)")

# Store
store = CustomerContextStore()
store.put("conv-1", snap)
assert store.get("conv-1") is snap
assert store.get("conv-2") is None
print("\nStore: get/put OK")

print("\n✓ T1 verification PASS")
