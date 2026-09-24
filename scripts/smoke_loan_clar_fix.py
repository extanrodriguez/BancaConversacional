"""Smoke: loan clarification context fix."""
import httpx, uuid
BASE = "http://localhost:8000"

cases = [
    ("CUST009", "tasa de mi prestamo?", "Should list 2 LOANS"),
    ("CUST001", "Saldo de mi cuenta?", "Should list ACCOUNTS"),
    ("CUST002", "tasa de mi pr\u00e9stamo?", "Should resolve PRE002Q (1 loan)"),
]

for cust, q, label in cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=90)
    d = r.json()
    clars = d.get("clarifications", [])
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    ent = a.get("detected_entities", {}) if a else {}
    print(f"\n{label}")
    print(f"  Q: {q!r}  customer={cust}")
    print(f"  status={d.get('status')}  mode={d.get('mode')}  intent={a.get('intent_id')}  acct={ent.get('account_ref')}")
    if clars:
        print(f"  suggested_question: {clars[0].get('suggested_question','')}")
    else:
        print(f"  (no clarifications)")
