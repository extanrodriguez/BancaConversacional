"""Parte B+C: Re-test failed cases + multiturn."""
import httpx, uuid, time, json
BASE = "http://localhost:8000"

print("=== Parte B: Previously failed single-turn ===\n")

b_cases = [
    ("CUST001", "información sobre mi préstamo", "Should NOT be ambiguous → CLARIFICATION loans"),
    ("CUST001", "mis productos", "Should NOT be ambiguous → PORTFOLIO or CLARIFICATION"),
    ("CUST001", "saldo de mi cuenta de ahorros", "client_response should NOT mention préstamo"),
    ("CUST001", "saldo de mi cuenta corriente", "client_response should NOT mention préstamo"),
]

for cust, q, expect in b_cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=90)
    d = r.json()
    ps = d.get("product_scores", {}) or {}
    cr = (d.get("client_response") or "")[:100]
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    print(f"  {q:<40} status={d.get('status'):<24} ps_arb={ps.get('arbitration','-'):<10} cr={cr}")
    time.sleep(3.0)

print("\n\n=== Parte C: Multiturn ===\n")

# C1: saldo → "Cuenta corriente principal"
print("--- C1: saldo → 'Cuenta corriente principal' ---")
cid = str(uuid.uuid4())
r1 = httpx.post(f"{BASE}/inspect", json={"question": "saldo de mi cuenta?", "customer_id": "CUST001", "conversation_id": cid}, timeout=90)
d1 = r1.json()
print(f"  T1: status={d1.get('status')}")
time.sleep(3.0)
r2 = httpx.post(f"{BASE}/inspect", json={"question": "Cuenta corriente principal", "customer_id": "CUST001", "conversation_id": cid}, timeout=90)
d2 = r2.json()
a2 = d2.get("actions", [{}])[0] if d2.get("actions") else {}
ent2 = a2.get("detected_entities", {}) if a2 else {}
print(f"  T2: status={d2.get('status')} intent={a2.get('intent_id')} acct={ent2.get('account_ref')}")
time.sleep(3.0)

# C2: cuota → "Credito Vehiculo"
print("\n--- C2: cuota → 'Credito Vehiculo' ---")
cid2 = str(uuid.uuid4())
r3 = httpx.post(f"{BASE}/inspect", json={"question": "cuota de mi prestamo?", "customer_id": "CUST001", "conversation_id": cid2}, timeout=90)
d3 = r3.json()
print(f"  T1: status={d3.get('status')}")
time.sleep(3.0)
r4 = httpx.post(f"{BASE}/inspect", json={"question": "Credito Vehiculo", "customer_id": "CUST001", "conversation_id": cid2}, timeout=90)
d4 = r4.json()
a4 = d4.get("actions", [{}])[0] if d4.get("actions") else {}
ent4 = a4.get("detected_entities", {}) if a4 else {}
print(f"  T2: status={d4.get('status')} intent={a4.get('intent_id')} acct={ent4.get('account_ref')}")
ld = d4.get("loan_detail")
if ld:
    print(f"  loan_detail: {json.dumps(ld, ensure_ascii=False)[:80]}")
