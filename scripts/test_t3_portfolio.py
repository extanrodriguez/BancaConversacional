"""Test T3: Portfolio projection from SQLite snapshot."""
import httpx
import json

BASE = "http://localhost:8000"


def test_case(label, question, customer_id=None):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  question: {question!r}  customer_id: {customer_id or '(default)'}")
    print(f"{'='*60}")
    payload = {"question": question}
    if customer_id:
        payload["customer_id"] = customer_id
    r = httpx.post(f"{BASE}/inspect", json=payload, timeout=60)
    d = r.json()
    print(f"  HTTP: {r.status_code}")
    print(f"  status: {d.get('status')}")
    print(f"  mode: {d.get('mode')}")
    ctx = d.get("customer_context")
    print(f"  customer_context: {ctx}")

    # Show what products the model saw via effective_capability_ids
    # and portfolio product_refs from the raw_interpretation or initial_proposal
    ip = d.get("initial_proposal")
    if ip and ip.get("actions"):
        a0 = ip["actions"][0]
        ent = a0.get("detected_entities", {})
        print(f"  proposer → cap={a0.get('capability_id')} intent={a0.get('intent_id')} acct={ent.get('account_ref')}")

    # Actions from final
    actions = d.get("actions", [])
    if actions:
        a = actions[0]
        ent = a.get("detected_entities", {})
        print(f"  final → intent={a.get('intent_id')} acct={ent.get('account_ref')}")

    # Clarifications
    clars = d.get("clarifications", [])
    if clars:
        print(f"  clarification: {clars[0].get('suggested_question', '')[:80]}")

    return d


# Test 1: CUST001 "Hola" — verify portfolio loaded
d1 = test_case("CUST001 Hola (portfolio check)", "Hola")

# Test 2: CUST001 "cuota de mi préstamo" — should see 2 LOANs, expect CLARIFICATION
d2 = test_case("CUST001 cuota préstamo (2 loans)", "¿Cuánto es la cuota de mi préstamo?", "CUST001")

# Test 3: CUST002 "cuota de mi préstamo" — should see 1 LOAN, no ambiguity
d3 = test_case("CUST002 cuota préstamo (1 loan)", "¿Cuánto es la cuota de mi préstamo?", "CUST002")

# Test 4: CUST001 "saldo de mi cuenta de ahorros" — regression check
d4 = test_case("CUST001 saldo ahorros (regression)", "¿Cuál es el saldo de mi cuenta de ahorros?")

print("\n\n=== SUMMARY ===")
print(f"  CUST001 products_count: {d1.get('customer_context', {}).get('products_count')}")
print(f"  CUST001 loans_count:    {d1.get('customer_context', {}).get('loans_count')}")
print(f"  CUST001 cuota status:   {d2.get('status')}")
print(f"  CUST002 cuota status:   {d3.get('status')}")
print(f"  CUST001 saldo status:   {d4.get('status')}")
