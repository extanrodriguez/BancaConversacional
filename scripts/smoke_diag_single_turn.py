"""Parte A: Single-turn paraphrase diagnostic suite."""
import httpx, uuid, time, json
BASE = "http://localhost:8000"

CASES = [
    # CUST002 (1 loan PRE002Q) — should go to LOAN or balance, NEVER query_scope
    ("CUST002", "Dime la letra de mi préstamo"),
    ("CUST002", "Cuánto pago al mes de mi crédito"),
    ("CUST002", "Cuál es la cuota de mi préstamo"),
    ("CUST002", "tasa de mi prestamo"),
    ("CUST002", "fecha de pago de mi credito"),
    ("CUST002", "saldo pendiente de mi prestamo"),
    # CUST001 (2 loans, 3+ cuentas)
    ("CUST001", "saldo de mi cuenta de ahorros"),
    ("CUST001", "saldo de mi cuenta corriente"),
    ("CUST001", "Quiero consultar mi saldo"),
    ("CUST001", "cuota de mi prestamo"),
    ("CUST001", "información sobre mi préstamo"),
    ("CUST001", "mis productos"),
    ("CUST001", "Hola"),
    # CUST009 (2 loans in snapshot.loans)
    ("CUST009", "tasa de mi prestamo"),
    # Mutation / OOD / negocio
    ("CUST001", "Mueve 20 pesos de ahorro a corriente"),
    ("CUST001", "Reserva un vuelo a Miami"),
    ("CUST001", "Qué tasas manejan para préstamos personales"),
]

print(f"{'CUST':<8} {'PREGUNTA':<45} {'STATUS':<24} {'INTENT':<22} {'ACCT_REF':<10} {'PS_ARB':<12} {'CLIENT_RESP':<80}")
print("─" * 200)

for cust, q in CASES:
    cid = str(uuid.uuid4())
    try:
        r = httpx.post(f"{BASE}/inspect", json={"question": q, "customer_id": cust, "conversation_id": cid}, timeout=90)
        d = r.json()
        a = d.get("actions", [{}])[0] if d.get("actions") else {}
        ent = a.get("detected_entities", {}) if a else {}
        ps = d.get("product_scores", {}) or {}
        cr = (d.get("client_response") or "")[:78]
        status = d.get("status", "?")
        intent = a.get("intent_id", "-") if a else "-"
        acct = ent.get("account_ref", "-") if ent else "-"
        ps_arb = ps.get("arbitration", "-") if ps else "-"
        # Detect query_scope FAIL
        is_query_scope = "consultar un dato" in cr.lower() or "realizar una" in cr.lower()
        mark = " <<<QUERY_SCOPE" if is_query_scope else ""
        print(f"{cust:<8} {q:<45} {status:<24} {intent:<22} {str(acct):<10} {ps_arb:<12} {cr}{mark}")
    except Exception as e:
        print(f"{cust:<8} {q:<45} {'ERROR':<24} {'':<22} {'':<10} {'':<12} {str(e)[:60]}")
    time.sleep(3.0)  # Avoid rate limit
