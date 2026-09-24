"""Quick AC-06 diagnostic: 3 multiturn sequences."""
import httpx
import uuid

BASE = "http://localhost:8000"

for i in range(3):
    cid = str(uuid.uuid4())
    r1 = httpx.post(f"{BASE}/inspect", json={"question": "Quiero consultar mi saldo", "conversation_id": cid}, timeout=60)
    r2 = httpx.post(f"{BASE}/inspect", json={"question": "La de ahorros", "conversation_id": cid}, timeout=60)
    d2 = r2.json()
    acct = None
    if d2.get("actions"):
        acct = d2["actions"][0].get("detected_entities", {}).get("account_ref")
    ip = d2.get("initial_proposal", {})
    ip_acct = None
    if ip.get("actions"):
        ip_acct = ip["actions"][0].get("detected_entities", {}).get("account_ref")
    vp = d2.get("verified_proposal", {})
    vp_rt = vp.get("result_type")
    vp_acct = None
    if vp.get("actions"):
        vp_acct = vp["actions"][0].get("detected_entities", {}).get("account_ref")
    print(f"[{i+1}] T2: HTTP={r2.status_code} status={d2.get('status')} mode={d2.get('mode')} acct={acct}")
    print(f"     proposer: acct={ip_acct}  verifier: rt={vp_rt} acct={vp_acct}")
