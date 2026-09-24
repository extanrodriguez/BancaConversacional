"""Smoke T4: Final Response UI."""
import httpx, uuid, time
BASE = "http://localhost:8000"

cases = [
    ("CUST002", "Dime la letra de mi pr\u00e9stamo", "AC-FR-01: loan detail"),
    ("CUST001", "Saldo de mi cuenta?", "AC-FR-02: clarification"),
    ("CUST001", "Mueve 20 pesos de mi cuenta de ahorro a la corriente", "AC-FR-03: unsupported"),
    ("CUST001", "Hola", "AC-FR-04: saludo"),
]

for cust, q, label in cases:
    cid = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=90)
    d = r.json()
    cr = d.get("client_response")
    print(f"\n{label}")
    print(f"  Q: {q!r}  customer={cust}")
    print(f"  status={d.get('status')}")
    print(f"  client_response: {cr}")
    time.sleep(2.0)
