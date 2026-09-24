"""Diagnostic T4: 3 runs AC-15 + AC-16 — check CLARIFICATION output."""
import json
import uuid
import httpx

BASE = "http://localhost:8000"

CASES = [
    ("AC-15", "¿Cuál es la tasa del préstamo hipotecario?"),
    ("AC-16", "Quiero información sobre la cuenta de ahorros"),
]

for ac_id, question in CASES:
    print(f"\n{'='*70}")
    print(f"  {ac_id}: {question!r}")
    print(f"{'='*70}")
    for run in range(1, 4):
        cid = str(uuid.uuid4())
        r = httpx.post(f"{BASE}/inspect", json={"question": question, "conversation_id": cid}, timeout=60)
        d = r.json()
        status = d.get("status")
        mode = d.get("mode")
        actions = d.get("actions", [])
        clars = d.get("clarifications", [])
        a0 = actions[0] if actions else {}
        ent = a0.get("detected_entities", {}) if a0 else {}
        acct = ent.get("account_ref")
        topic = ent.get("knowledge_topic")
        missing = a0.get("missing_requirements", []) if a0 else []
        suggested = clars[0].get("suggested_question", "") if clars else ""
        print(f"  [{run}] status={status}  mode={mode}")
        print(f"      account_ref={acct}  knowledge_topic={topic}")
        print(f"      missing_requirements={missing}")
        print(f"      suggested_question={suggested[:100]}")
        if status not in ("CLARIFICATION_REQUIRED",):
            print(f"      error_detail={d.get('error_detail','')[:200]}")
