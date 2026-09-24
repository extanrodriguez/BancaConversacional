"""Smoke test T2: CUST002 loan-read routing."""
import httpx
import uuid

BASE = "http://localhost:8000"

for i in range(3):
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={
        "question": "¿Cuánto es la cuota de mi préstamo?",
        "customer_id": "CUST002",
        "conversation_id": cid,
    }, timeout=60)
    d = r.json()
    actions = d.get("actions", [])
    a0 = actions[0] if actions else {}
    ent = a0.get("detected_entities", {}) if a0 else {}
    print(f"[{i+1}] status={d.get('status')}  intent={a0.get('intent_id')}  account_ref={ent.get('account_ref')}  prompt={d.get('prompt_version')}")
