"""Valida los 6 casos Fase 1 contra /turn.

Uso:
  python Test_local/validate_fase1_cases.py
  set GENESIS_VALIDATE_BASE=http://20.127.25.24:8447
  python Test_local/validate_fase1_cases.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://127.0.0.1:8445").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "TEST-QA-001")


def post(path: str, payload: dict, timeout: int = 120) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception as exc:
        if hasattr(exc, "read"):
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return getattr(exc, "code", 500), json.loads(body)
            except Exception:
                return getattr(exc, "code", 500), {"error": body}
        return 500, {"error": str(exc)}


def reply_of(data: dict) -> str:
    app = data.get("app_channel") or {}
    return (
        app.get("client_response")
        or data.get("client_response")
        or ""
    ).strip()


def new_session() -> str:
    st, login = post("/lab/login", {"customer_id": CUSTOMER})
    if st == 200 and login.get("conversation_id"):
        return login["conversation_id"]
    # fallback: conversation_id propio + primer turn con contexto lab
    return f"fase1-{uuid.uuid4().hex[:10]}"


def turn(cid: str, question: str) -> tuple[int, dict, str]:
    st, data = post(
        "/turn",
        {
            "question": question,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )
    return st, data, reply_of(data)


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    # 1 Mision
    cid = new_session()
    st, data, txt = turn(cid, "Mision")
    ok = st == 200 and ("emprendedor" in txt.lower() or "instituc" in txt.lower()) and "asesor se pondra" not in txt.lower()
    results.append(("1 Mision", ok, f"HTTP {st} status={data.get('status')} | {txt[:180]}"))

    # 2 hablame del banco
    cid = new_session()
    st, data, txt = turn(cid, "hablame del banco")
    ok = (
        st == 200
        and ("banco" in txt.lower() or "emprendedor" in txt.lower() or "instituc" in txt.lower())
        and "asesor se pondra" not in txt.lower()
        and "numero de caso" not in txt.lower()
    )
    results.append(("2 hablame del banco", ok, f"HTTP {st} status={data.get('status')} | {txt[:180]}"))

    # 3 reclamacion → pide canal; luego Centro de Contacto
    cid = new_session()
    st1, data1, txt1 = turn(cid, "¿cual es el proceso para una reclamacion?")
    ok1 = st1 == 200 and (
        "canal" in txt1.lower()
        or "809.726.1000" in txt1
        or "centro de contacto" in txt1.lower()
        or data1.get("status") == "CLARIFICATION_REQUIRED"
        or data1.get("mode") == "CLARIFICATION"
    )
    # No debe ser el dump completo del proceso documental en el primer turno
    dumpish = "crédito no procesado" in txt1.lower() or "credito no procesado" in txt1.lower()
    st2, data2, txt2 = turn(cid, "Centro de Contacto")
    ok2 = st2 == 200 and "809.726.1000" in txt2 and "asesor se pondra" not in txt2.lower()
    results.append(
        (
            "3a reclamacion pide canal",
            ok1 and not dumpish,
            f"HTTP {st1} status={data1.get('status')} | {txt1[:220]}",
        )
    )
    results.append(
        (
            "3b canal Centro de Contacto",
            ok2,
            f"HTTP {st2} status={data2.get('status')} | {txt2[:220]}",
        )
    )

    # 4 en que me puedes ayudar
    cid = new_session()
    st, data, txt = turn(cid, "¿en que me puedes ayudar?")
    low = txt.lower()
    ok = (
        st == 200
        and ("puedo ayudarte" in low or "hoy puedo" in low or "•" in txt or "-" in txt)
        and not (low.startswith("hola") and "en qué puedo ayudarte" in low and "saldo" not in low)
    )
    # Debe listar capacidades, no eco de saludo puro
    ok = ok and ("saldo" in low or "cuenta" in low or "producto" in low or "tarjeta" in low)
    results.append(("4 en que me puedes ayudar", ok, f"HTTP {st} status={data.get('status')} | {txt[:220]}"))

    # 5 QUE ES BANCO SANTA CRUZ
    cid = new_session()
    st, data, txt = turn(cid, "QUE ES BANCO SANTA CRUZ")
    ok = (
        st == 200
        and ("santa cruz" in txt.lower() or "emprendedor" in txt.lower() or "instituc" in txt.lower())
        and "asesor se pondra" not in txt.lower()
        and "numero de caso" not in txt.lower()
    )
    results.append(("5 QUE ES BANCO SANTA CRUZ", ok, f"HTTP {st} status={data.get('status')} | {txt[:180]}"))

    # 6 COÑO
    cid = new_session()
    st, data, txt = turn(cid, "COÑO")
    low = txt.lower()
    ok = (
        st == 200
        and ("consultas bancarias" in low or "qué necesitas" in low or "que necesitas" in low)
        and not low.startswith("¡hola")
        and "hola," not in low[:40]
    )
    results.append(("6 COÑO", ok, f"HTTP {st} status={data.get('status')} | {txt[:180]}"))

    fails = 0
    print("=" * 72)
    print(f"VALIDACION FASE 1 — {BASE}")
    print("=" * 72)
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{mark}] {name}")
        print(f"       {detail}")
        print()
    print(f"TOTAL: {len(results) - fails}/{len(results)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
