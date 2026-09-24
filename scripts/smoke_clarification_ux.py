"""Smoke: CLARIFICATION UX fix — always show suggested_question."""
import httpx, uuid, json
BASE = "http://localhost:8000"

cases = [
    ("CUST001", "¿Cuál es la cuota de mi préstamo?"),
    ("CUST001", "¿Cuál es mi tasa de préstamo?"),
    ("CUST001", "¿Cuáles son mis préstamos?"),
]

for cust, q in cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=60)
    d = r.json()
    print(f"\nQ: {q!r}  customer={cust}")
    print(f"  status={d.get('status')}  mode={d.get('mode')}")
    clars = d.get("clarifications", [])
    print(f"  clarifications count: {len(clars)}")
    if clars:
        c0 = clars[0]
        print(f"  suggested_question: {c0.get('suggested_question','')[:120]}")
        print(f"  missing_requirements: {c0.get('missing_requirements')}")
    else:
        print(f"  *** NO CLARIFICATIONS (BUG) ***")
    print()
