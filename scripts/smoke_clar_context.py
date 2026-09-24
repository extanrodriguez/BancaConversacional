"""Smoke: clarification context-aware (accounts vs loans)."""
import httpx, uuid, json
BASE = "http://localhost:8000"

cases = [
    ("CUST001", "Saldo de mi cuenta?"),
    ("CUST001", "\u00bfCu\u00e1nto es la cuota de mi pr\u00e9stamo?"),
    ("CUST002", "Dime la letra de mi pr\u00e9stamo"),
]

for cust, q in cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=60)
    d = r.json()
    clars = d.get("clarifications", [])
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    ent = a.get("detected_entities", {}) if a else {}
    print(f"\nQ: {q!r}  customer={cust}")
    print(f"  status={d.get('status')}  mode={d.get('mode')}  intent={a.get('intent_id')}  acct={ent.get('account_ref')}")
    if clars:
        print(f"  suggested_question: {clars[0].get('suggested_question','')}")
    else:
        print(f"  clarifications: (empty)")
    print()
