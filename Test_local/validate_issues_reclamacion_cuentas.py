"""Valida issues reportados: loop reclamación + cuentas contratar + proceso KB."""

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


def login() -> str:
    return post("/lab/login", {"customer_id": CUSTOMER})["conversation_id"]


def turn(cid: str, q: str) -> tuple[str, str, str]:
    data = post(
        "/turn",
        {
            "question": q,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )
    return data.get("status") or "", data.get("mode") or "", reply(data)


def main() -> int:
    fails = 0
    print(f"BASE={BASE} customer={CUSTOMER}")
    print("=" * 72)

    # Issue 1: no loop
    cid = login()
    st, mode, t1 = turn(cid, "dame el proceso de reclamaciones")
    ok1 = "809" in t1 or "reclam" in t1.lower()
    print(f"[{'PASS' if ok1 else 'FAIL'}] 1a proceso reclamaciones | {st} | {t1[:140]}")
    fails += not ok1

    st, mode, t2 = turn(cid, "dime cuales productos de cuentas puedo contratar en el banco")
    ok2 = (
        "cuenta" in t2.lower()
        and "no identifiqué el canal" not in t2.lower()
        and "no identifique el canal" not in t2.lower()
        and "reclamación por varios canales" not in t2.lower()
    )
    print(f"[{'PASS' if ok2 else 'FAIL'}] 1b cambio a cuentas (sin loop) | {st} | {t2[:160]}")
    fails += not ok2

    st, mode, t3 = turn(cid, "dame el listado de mis productos")
    ok3 = "no identifiqué el canal" not in t3.lower() and "no identifique el canal" not in t3.lower()
    print(f"[{'PASS' if ok3 else 'FAIL'}] 1c listado productos (sin loop) | {st} | {t3[:160]}")
    fails += not ok3

    # Issue 2: ambas formulaciones de cuentas
    cid = login()
    st, mode, a = turn(cid, "dime cuales productos de cuentas puedo contratar en el banco")
    ok_a = "ahorro" in a.lower() or "corriente" in a.lower()
    print(f"[{'PASS' if ok_a else 'FAIL'}] 2a cuentas en el banco | {st} | {a[:160]}")
    fails += not ok_a

    cid = login()
    st, mode, b = turn(cid, "dime cuales productos de cuentas puedo contratar con el banco santa cruz")
    ok_b = "ahorro" in b.lower() or "corriente" in b.lower()
    print(f"[{'PASS' if ok_b else 'FAIL'}] 2b cuentas banco santa cruz | {st} | {b[:160]}")
    fails += not ok_b

    # Issue 3: proceso reclamaciones desde KB
    cid = login()
    st, mode, c = turn(cid, "dame el proceso de reclamaciones")
    ok_c = ("809.726.1000" in c or "centro de contacto" in c.lower()) and "motor conversacional" not in c.lower()
    print(f"[{'PASS' if ok_c else 'FAIL'}] 3 proceso reclamaciones KB | {st} | {c[:180]}")
    fails += not ok_c

    # Follow-up canal tras overview
    st, mode, d = turn(cid, "Centro de Contacto")
    ok_d = "809.726.1000" in d
    print(f"[{'PASS' if ok_d else 'FAIL'}] 3b detalle canal contacto | {st} | {d[:140]}")
    fails += not ok_d

    print("=" * 72)
    total = 7
    print(f"TOTAL: {total - fails}/{total} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
