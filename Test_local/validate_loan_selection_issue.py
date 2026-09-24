"""Valida selección de préstamos tras clarificación (issue cards ...7615)."""

from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")


def post(path: str, payload: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reply(data: dict) -> str:
    app = data.get("app_channel") or {}
    return (app.get("client_response") or data.get("client_response") or "").strip()


def options(data: dict) -> list:
    app = data.get("app_channel") or {}
    return app.get("options") or data.get("options") or []


def login() -> str:
    return post("/lab/login", {"customer_id": CUSTOMER})["conversation_id"]


def turn(cid: str, q: str) -> dict:
    return post(
        "/turn",
        {
            "question": q,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )


def main() -> int:
    fails = 0
    print(f"BASE={BASE} customer={CUSTOMER}")
    cid = login()

    d1 = turn(cid, "cuanto debo en prestamos")
    t1 = reply(d1)
    opts = options(d1)
    ok1 = "27615" in t1 and "90123" in t1 and d1.get("status") in (
        "CLARIFICATION_REQUIRED",
        "requires_selection",
    )
    # labels alineados a 5 dígitos
    labels = [o.get("label", "") for o in opts]
    ok_labels = any("27615" in lb for lb in labels) and any("90123" in lb for lb in labels)
    print(f"[{'PASS' if ok1 else 'FAIL'}] clarificación | {d1.get('status')} | {t1[:120]}")
    print(f"[{'PASS' if ok_labels else 'FAIL'}] cards labels | {labels}")
    fails += (not ok1) + (not ok_labels)

    # seleccionar primera opción (label nuevo o legado)
    pick = next((lb for lb in labels if "27615" in lb), "Préstamo ...27615")
    d2 = turn(cid, pick)
    t2 = reply(d2)
    ok2 = (
        d2.get("status") == "VALID_CONTRACT"
        and "no existe" not in t2.lower()
        and ("185" in t2 or "capital" in t2.lower() or "adeud" in t2.lower() or "préstamo" in t2.lower())
    )
    print(f"[{'PASS' if ok2 else 'FAIL'}] selección {pick!r} | {d2.get('status')} | {t2[:160]}")
    fails += not ok2

    # legado 4 dígitos aún debe resolver
    cid2 = login()
    turn(cid2, "cuanto debo en prestamos")
    d3 = turn(cid2, "Préstamo ...7615")
    t3 = reply(d3)
    ok3 = d3.get("status") == "VALID_CONTRACT" and "no existe" not in t3.lower()
    print(f"[{'PASS' if ok3 else 'FAIL'}] legado ...7615 | {d3.get('status')} | {t3[:160]}")
    fails += not ok3

    print(f"TOTAL: {3 - fails}/3 PASS" if fails <= 3 else f"FAILS={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
