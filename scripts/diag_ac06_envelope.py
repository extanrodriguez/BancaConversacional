"""Diagnostic: check what ModelInputEnvelope looks like on Turn 2."""
import httpx
import uuid
import json

BASE = "http://localhost:8000"

# We need to intercept what the model sees. Let's just check if pending_action is in the response.
# Actually, let's look at the full response for turn 2 including all proposals.

cid = str(uuid.uuid4())
r1 = httpx.post(f"{BASE}/inspect", json={"question": "Quiero consultar mi saldo", "conversation_id": cid}, timeout=60)
d1 = r1.json()
print("T1 status:", d1.get("status"), "conv_history:", d1.get("conversation_history"))

r2 = httpx.post(f"{BASE}/inspect", json={"question": "La de ahorros", "conversation_id": cid}, timeout=60)
d2 = r2.json()
print("\nT2 HTTP:", r2.status_code)
print("T2 status:", d2.get("status"))
print("T2 error_detail:", d2.get("error_detail", "")[:500])
print("T2 initial_proposal:", json.dumps(d2.get("initial_proposal"), indent=2, ensure_ascii=False)[:600] if d2.get("initial_proposal") else "None")
print("T2 verified_proposal:", json.dumps(d2.get("verified_proposal"), indent=2, ensure_ascii=False)[:600] if d2.get("verified_proposal") else "None")
print("T2 conversation_history:", d2.get("conversation_history"))
