"""Diagnostic T6: Capture INVALID_MODEL_OUTPUT responses with full detail."""
import json
import uuid
import httpx

BASE = "http://localhost:8000"

CASES = [
    ("AC-12", "¿Cuánto tengo disponible en la corriente?"),
    ("AC-13", "¿Cuáles son los requisitos para un préstamo de vivienda?"),
]

captured = 0
TARGET = 3

for ac_id, question in CASES:
    if captured >= TARGET:
        break
    for run in range(1, 20):
        if captured >= TARGET:
            break
        cid = str(uuid.uuid4())
        r = httpx.post(f"{BASE}/inspect", json={"question": question, "conversation_id": cid}, timeout=60)
        d = r.json()
        if d.get("status") == "INVALID_MODEL_OUTPUT" or d.get("_http_status", r.status_code) == 422:
            captured += 1
            print(f"\n{'='*70}")
            print(f"  CAPTURE {captured}: {ac_id} run={run}")
            print(f"  question: {question!r}")
            print(f"  HTTP: {r.status_code}")
            print(f"  status: {d.get('status')}")
            print(f"  error_detail: {d.get('error_detail', '')}")
            ip = d.get("initial_proposal")
            vp = d.get("verified_proposal")
            if ip:
                print(f"  initial_proposal: {json.dumps(ip, indent=2, ensure_ascii=False)[:800]}")
            else:
                print(f"  initial_proposal: None")
            if vp:
                print(f"  verified_proposal: {json.dumps(vp, indent=2, ensure_ascii=False)[:800]}")
            else:
                print(f"  verified_proposal: None")
            print(f"{'='*70}")
        else:
            print(f"  [{ac_id} run={run}] OK: {d.get('status')}")

if captured < TARGET:
    print(f"\nOnly captured {captured}/{TARGET} failures.")
