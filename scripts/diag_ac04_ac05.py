"""Diagnostic: 3 runs AC-04, 2 runs AC-05 — show initial_proposal + verified_proposal."""
import json
import uuid
import httpx

BASE = "http://localhost:8000"

def run(question: str, label: str) -> None:
    conv_id = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/inspect", json={"question": question, "conversation_id": conv_id}, timeout=60)
    data = r.json()
    ip = data.get("initial_proposal") or {}
    vp = data.get("verified_proposal") or {}
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  question: {question!r}")
    print(f"  HTTP: {r.status_code}  status: {data.get('status')}  mode: {data.get('mode')}")
    print(f"  --- initial_proposal ---")
    print(f"    result_type: {ip.get('result_type')}")
    for a in ip.get("actions", []):
        ent = a.get("detected_entities", {})
        print(f"    action: cap={a.get('capability_id')} intent={a.get('intent_id')} account_ref={ent.get('account_ref')} conf={a.get('confidence')}")
    print(f"    non_op_msg: {ip.get('non_operational_message')}")
    print(f"    unsupported: {ip.get('unsupported_segments')}")
    print(f"  --- verified_proposal ---")
    print(f"    result_type: {vp.get('result_type')}")
    for a in vp.get("actions", []):
        ent = a.get("detected_entities", {})
        print(f"    action: cap={a.get('capability_id')} intent={a.get('intent_id')} account_ref={ent.get('account_ref')} conf={a.get('confidence')}")
    print(f"    clarification_question: {vp.get('clarification_question')}")
    print(f"    non_op_msg: {vp.get('non_operational_message')}")
    print(f"    unsupported: {vp.get('unsupported_segments')}")
    print(f"    verification_notes: {vp.get('verification_notes')}")

print("AC-04 DIAGNOSTIC (3 runs)")
for i in range(3):
    run("Quiero consultar mi saldo", f"AC-04 run {i+1}")

print("\n\nAC-05 DIAGNOSTIC (2 runs)")
for i in range(2):
    run("Reserva un vuelo a Miami para el viernes", f"AC-05 run {i+1}")
