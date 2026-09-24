"""Diagnostic T1: 3 runs per AC-11..AC-16 against /inspect."""
import json
import uuid
import httpx

BASE = "http://localhost:8000"

CASES = [
    ("AC-11", "¿Cuál es el saldo de mi cuenta de ahorros?"),
    ("AC-12", "¿Cuánto tengo disponible en la corriente?"),
    ("AC-13", "¿Cuáles son los requisitos para un préstamo de vivienda?"),
    ("AC-14", "¿Qué tasas de interés manejan para préstamos personales?"),
    ("AC-15", "¿Cuál es la tasa del préstamo hipotecario?"),
    ("AC-16", "Quiero información sobre la cuenta de ahorros"),
]

print(f"{'AC':<6} {'run':<4} {'status':<24} {'intent':<28} {'route':<24} {'account_ref':<12} {'knowledge_topic':<20} {'rag_status'}")
print("─" * 140)

for ac_id, question in CASES:
    for run in range(1, 4):
        cid = str(uuid.uuid4())
        r = httpx.post(f"{BASE}/inspect", json={"question": question, "conversation_id": cid}, timeout=60)
        d = r.json()
        actions = d.get("actions", [])
        a0 = actions[0] if actions else {}
        ent = a0.get("detected_entities", {}) if a0 else {}
        intent = a0.get("intent_id", "") if a0 else ""
        route = a0.get("selected_route", "") if a0 else ""
        acct = ent.get("account_ref")
        topic = ent.get("knowledge_topic")
        rag = d.get("rag_status")
        status = d.get("status", "")
        print(f"{ac_id:<6} {run:<4} {status:<24} {intent:<28} {route:<24} {str(acct):<12} {str(topic):<20} {rag}")
