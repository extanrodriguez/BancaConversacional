"""Smoke T5: Product Specialists integration."""
import httpx, uuid, json
BASE = "http://localhost:8000"

cases = [
    ("CUST001", "Saldo de mi cuenta?", "AC-PS-01: CLARIFICATION cuentas"),
    ("CUST001", "Mueve 20 pesos de mi cuenta de ahorro a la corriente", "AC-PS-05: NO movements+amount"),
    ("CUST002", "Dime la letra de mi pr\u00e9stamo", "AC-PS-04: LOAN_DETAIL_READ"),
]

for cust, q, label in cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=90)
    d = r.json()
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    ent = a.get("detected_entities", {}) if a else {}
    clars = d.get("clarifications", [])
    unsup = d.get("unsupported_segments", [])
    print(f"\n{label}")
    print(f"  Q: {q!r}  customer={cust}")
    print(f"  status={d.get('status')}  mode={d.get('mode')}")
    print(f"  intent={a.get('intent_id')}  account_ref={ent.get('account_ref')}")
    print(f"  domain_scores={d.get('domain_scores')}")
    print(f"  product_scores={d.get('product_scores')}")
    if clars:
        print(f"  clarification: {clars[0].get('suggested_question','')[:100]}")
    if unsup:
        print(f"  unsupported: {unsup[0].get('segment_description','')[:80]}")
