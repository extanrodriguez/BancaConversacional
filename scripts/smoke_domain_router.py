"""Smoke T4/T5: domain router integration."""
import httpx
import uuid
import json

BASE = "http://localhost:8000"


def test(label, question, customer_id=None):
    print(f"\n{'='*60}")
    print(f"  {label}")
    payload = {"question": question, "conversation_id": str(uuid.uuid4())}
    if customer_id:
        payload["customer_id"] = customer_id
    r = httpx.post(f"{BASE}/inspect", json=payload, timeout=60)
    d = r.json()
    print(f"  HTTP: {r.status_code}  status: {d.get('status')}  mode: {d.get('mode')}")
    a = d.get("actions", [{}])[0] if d.get("actions") else {}
    ent = a.get("detected_entities", {}) if a else {}
    print(f"  intent: {a.get('intent_id')}  account_ref: {ent.get('account_ref')}")
    print(f"  domain_scores: {d.get('domain_scores')}")
    ld = d.get("loan_detail")
    if ld:
        print(f"  loan_detail: {json.dumps(ld, ensure_ascii=False)}")
    return d


# 1. OOD → UNSUPPORTED + domain_scores
test("OOD: vuelo", "Reserva un vuelo a Miami para el viernes")

# 2. CUST002 loan paraphrase
test("CUST002: letra prestamo", "Dime la letra de mi prestamo", "CUST002")

# 3. Saldo ahorros → no forzar loan
test("Saldo ahorros (no loan)", "Cual es el saldo de mi cuenta de ahorros?")
