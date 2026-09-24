"""Smoke T2: 5 runs with exact AC phrasing (accented)."""
import httpx
import uuid

BASE = "http://localhost:8000"
QUESTION = "\u00bfCu\u00e1nto es la cuota de mi pr\u00e9stamo?"

print(f"Question: {QUESTION!r}")
print()

for i in range(5):
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={
        "question": QUESTION,
        "customer_id": "CUST002",
        "conversation_id": cid,
    }, timeout=60)
    d = r.json()
    actions = d.get("actions", [])
    a0 = actions[0] if actions else {}
    ent = a0.get("detected_entities", {}) if a0 else {}
    intent = a0.get("intent_id", "") if a0 else ""
    acct = ent.get("account_ref")
    status = d.get("status", "")
    print(f"  [{i+1}] status={status:<24} intent={intent:<20} account_ref={acct}")
