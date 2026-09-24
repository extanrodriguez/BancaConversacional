"""Smoke: multiturn account clarification → resolution."""
import httpx, uuid, json
BASE = "http://localhost:8000"

print("=== Multiturn: CUST001 'saldo de mi cuenta' → 'Ahorros de emergencia' ===")
cid = str(uuid.uuid4())

# Turn 1
r1 = httpx.post(f"{BASE}/inspect", json={"question": "Saldo de mi cuenta?", "customer_id": "CUST001", "conversation_id": cid}, timeout=60)
d1 = r1.json()
print(f"\nTurn 1:")
print(f"  status={d1.get('status')}  mode={d1.get('mode')}")
clars = d1.get("clarifications", [])
if clars:
    print(f"  suggested_question: {clars[0].get('suggested_question','')[:120]}")
print(f"  conv_id: {d1.get('conversation_id','')[:8]}...")

# Turn 2
r2 = httpx.post(f"{BASE}/inspect", json={"question": "Ahorros de emergencia", "customer_id": "CUST001", "conversation_id": cid}, timeout=60)
d2 = r2.json()
a2 = d2.get("actions", [{}])[0] if d2.get("actions") else {}
ent2 = a2.get("detected_entities", {}) if a2 else {}
print(f"\nTurn 2 ('Ahorros de emergencia'):")
print(f"  status={d2.get('status')}  mode={d2.get('mode')}")
print(f"  intent={a2.get('intent_id')}  account_ref={ent2.get('account_ref')}")

# Turn 2b: with product_id directly
print("\n\n=== Multiturn: CUST001 'saldo de mi cuenta' → 'AHO001' ===")
cid2 = str(uuid.uuid4())
r1b = httpx.post(f"{BASE}/inspect", json={"question": "Saldo de mi cuenta?", "customer_id": "CUST001", "conversation_id": cid2}, timeout=60)
r2b = httpx.post(f"{BASE}/inspect", json={"question": "AHO001", "customer_id": "CUST001", "conversation_id": cid2}, timeout=60)
d2b = r2b.json()
a2b = d2b.get("actions", [{}])[0] if d2b.get("actions") else {}
ent2b = a2b.get("detected_entities", {}) if a2b else {}
print(f"\nTurn 2 ('AHO001'):")
print(f"  status={d2b.get('status')}  mode={d2b.get('mode')}")
print(f"  intent={a2b.get('intent_id')}  account_ref={ent2b.get('account_ref')}")

# Verify CUST002 loan still works
print("\n\n=== Non-regression: CUST002 'Dime la letra de mi prestamo' ===")
r3 = httpx.post(f"{BASE}/inspect", json={"question": "Dime la letra de mi pr\u00e9stamo", "customer_id": "CUST002", "conversation_id": str(uuid.uuid4())}, timeout=60)
d3 = r3.json()
a3 = d3.get("actions", [{}])[0] if d3.get("actions") else {}
ent3 = a3.get("detected_entities", {}) if a3 else {}
print(f"  status={d3.get('status')}  intent={a3.get('intent_id')}  acct={ent3.get('account_ref')}")
