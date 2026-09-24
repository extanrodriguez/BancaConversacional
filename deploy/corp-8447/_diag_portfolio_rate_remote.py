import json
from pathlib import Path

from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
from genesis_cognitive.brain.plan_interpreter import (
    interpret_turn_plan,
    _product_bears_rate,
    _active_products,
    _match_portfolio_by_text,
)

raw = json.loads(Path("data/lab_portfolios/qa_726588_contract_demo.json").read_text())
print("file_products", len(raw.get("products", [])))
for x in raw.get("products", []):
    print("FILE", x.get("productCategory"), x.get("productIdentification"), (x.get("productDescription") or "")[:48])

mapped = map_core_portfolio(raw)
# CustomerContextSnapshot construction path used in lab loaders
products = list(getattr(mapped, "products", None) or [])
print("mapped_n", len(products), "type", type(mapped))
if not products and hasattr(mapped, "accounts"):
    print("mapped_attrs", [a for a in dir(mapped) if not a.startswith("_")])

# Prefer snapshot builder used by runtime
try:
    from genesis_cognitive.context.lab_context import build_lab_customer_snapshot
    snap = build_lab_customer_snapshot("726588")
except Exception as e:
    print("lab_builder_err", type(e).__name__, e)
    from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
    # fallback: inspect map_core_portfolio return
    snap = None
    if hasattr(mapped, "products"):
        snap = CustomerContextSnapshot(customer_id="726588", products=list(mapped.products))

if snap is None:
    raise SystemExit("no snap")

print("snap_n", len(snap.products))
for p in snap.products:
    loan = getattr(p, "loan", None)
    print(
        "SNAP",
        p.product_type,
        p.product_id,
        p.alias,
        "rate",
        p.interest_rate,
        "loan_rate",
        getattr(loan, "annual_interest_rate", None) if loan else None,
        "mat",
        p.maturity_date,
        "status",
        p.status,
    )

active = _active_products(snap)
print("active", len(active), "rate_bearers", [(p.product_type, p.product_id) for p in active if _product_bears_rate(p)])
print("match_joven", [(p.product_id, p.alias) for p in _match_portfolio_by_text("tarjeta joven", snap)])

for q in (
    "cual es mi tasa de interes",
    "cual es el saldo de mi tarjeta joven",
    "cual es la tasa de mi tarjeta joven",
):
    plan = interpret_turn_plan(q, None, snapshot=snap)
    print("Q", q)
    for t in plan.tasks:
        print(" ", t.object, t.fields, t.status, t.entity_ref, (t.filters or {}).get("candidate_ids"))
