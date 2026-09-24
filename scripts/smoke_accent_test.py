"""Test accented vs non-accented question for loan-read."""
import httpx
import uuid

BASE = "http://localhost:8000"

questions = [
    "Cuanto es la cuota de mi prestamo?",
    "\u00bfCu\u00e1nto es la cuota de mi pr\u00e9stamo?",
]

for q in questions:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={
        "question": q,
        "customer_id": "CUST002",
        "conversation_id": cid,
    }, timeout=60)
    d = r.json()
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    ent = a.get("detected_entities", {}) if a else {}
    print(f"Q: {q!r}")
    print(f"  status={d.get('status')} intent={a.get('intent_id')} acct={ent.get('account_ref')}")
    print(f"  error={d.get('error_detail','')[:200]}")
    print()
