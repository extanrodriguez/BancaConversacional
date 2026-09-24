"""Smoke AC-UI-01..04: customer selector verification."""
import httpx
import uuid
import json

BASE = "http://localhost:8000"

# AC-UI-01: GET /customers returns ≥3
print("=== AC-UI-01: GET /customers ===")
r = httpx.get(f"{BASE}/customers", timeout=10)
customers = r.json()
print(f"  HTTP: {r.status_code}")
print(f"  Count: {len(customers)}")
for c in customers[:5]:
    print(f"    {c['customer_id']} — {c['display_name']}")
assert len(customers) >= 3, f"FAIL: only {len(customers)} customers"
print("  ✓ PASS (≥3 customers)\n")

# AC-UI-02: CUST002 "Dime la letra" → LOAN_DETAIL_READ
print("=== AC-UI-02: CUST002 loan read ===")
r2 = httpx.post(f"{BASE}/inspect", json={"question": "Dime la letra de mi pr\u00e9stamo", "customer_id": "CUST002", "conversation_id": str(uuid.uuid4())}, timeout=60)
d2 = r2.json()
a2 = d2.get("actions", [{}])[0] if d2.get("actions") else {}
print(f"  status={d2.get('status')} intent={a2.get('intent_id')} acct={a2.get('detected_entities',{}).get('account_ref')}")
assert d2.get("status") == "VALID_CONTRACT" and a2.get("intent_id") == "LOAN_DETAIL_READ", f"FAIL: {d2.get('status')}"
print("  ✓ PASS\n")

# AC-UI-03: CUST001 same phrase → CLARIFICATION + suggested_question
print("=== AC-UI-03: CUST001 loan clarification ===")
r3 = httpx.post(f"{BASE}/inspect", json={"question": "Dime la letra de mi pr\u00e9stamo", "customer_id": "CUST001", "conversation_id": str(uuid.uuid4())}, timeout=60)
d3 = r3.json()
clars = d3.get("clarifications", [])
print(f"  status={d3.get('status')} mode={d3.get('mode')}")
print(f"  clarifications count: {len(clars)}")
if clars:
    print(f"  suggested_question: {clars[0].get('suggested_question','')[:100]}")
assert d3.get("status") == "CLARIFICATION_REQUIRED", f"FAIL: {d3.get('status')}"
assert len(clars) > 0 and clars[0].get("suggested_question"), "FAIL: no suggested_question"
print("  ✓ PASS\n")

# AC-UI-04: 3 different customer_ids → customer_context matches
print("=== AC-UI-04: 3 customers context match ===")
for cust in ["CUST001", "CUST002", "CUST003"]:
    r4 = httpx.post(f"{BASE}/inspect", json={"question": "Hola", "customer_id": cust, "conversation_id": str(uuid.uuid4())}, timeout=60)
    d4 = r4.json()
    ctx = d4.get("customer_context")
    ctx_id = ctx.get("customer_id") if ctx else None
    match = "✓" if ctx_id == cust else "✗"
    print(f"  {match} sent={cust} → ctx.customer_id={ctx_id}")
    assert ctx_id == cust, f"FAIL: {cust} != {ctx_id}"
print("  ✓ PASS\n")

# Verify HTML has NO hardcoded CUST00x
print("=== Anti-hardcode check ===")
with open("src/genesis_cognitive/demo/static/index.html") as f:
    html = f.read()
hardcoded = any(x in html for x in ["CUST001", "CUST002", "CUST003", "Ana Gomez", "Luis Pena"])
if hardcoded:
    print("  ✗ FAIL: HTML contains hardcoded customer references!")
else:
    print("  ✓ PASS: No hardcoded customer IDs in HTML")

print("\n=== ALL SMOKE PASSED ===")
