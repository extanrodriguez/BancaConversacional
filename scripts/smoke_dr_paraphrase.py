"""Smoke: paraphrases for domain router loan."""
import httpx, uuid, json
BASE = "http://localhost:8000"

cases = [
    ("CUST002", "Dime la letra de mi pr\u00e9stamo"),
    ("CUST002", "\u00bfCu\u00e1nto pago al mes de mi cr\u00e9dito?"),
]

for cust, q in cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=60)
    d = r.json()
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    ent = a.get("detected_entities", {}) if a else {}
    ld = d.get("loan_detail")
    print(f"Q: {q!r}  customer={cust}")
    print(f"  status={d.get('status')} intent={a.get('intent_id')} acct={ent.get('account_ref')}")
    print(f"  domain_scores={d.get('domain_scores')}")
    if ld:
        print(f"  loan_detail.installment={ld.get('installment_amount')}")
    print()
