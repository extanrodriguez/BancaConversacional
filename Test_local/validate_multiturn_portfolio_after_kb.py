"""Reproduce: FAQ/reclamaciones → luego portafolio/préstamos (con y sin snapshot)."""

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


def turn(cid: str, q: str) -> tuple[str, str]:
    d = post(
        "/turn",
        {
            "question": q,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )
    return d.get("status") or "", reply(d)


def main() -> int:
    cid = post("/lab/login", {"customer_id": CUSTOMER})["conversation_id"]
    seq = [
        ("hablame del banco", ("santa cruz", "instituc", "emprendedor")),
        ("dame el proceso de reclamaciones", ("reclam", "809")),
        ("dime cuales productos de cuentas puedo contratar con el banco", ("cuenta", "ahorro", "corriente")),
        ("dime el listado de mis productos", ("producto", "cuenta", "préstamo", "prestamo", "ahorro")),
        ("dame informacion de mis prestamos", ("préstamo", "prestamo", "27615", "90123", "capital")),
        ("dame informacion de mis productos", ("producto", "cuenta", "préstamo", "prestamo")),
        ("dame el listado de mis productos", ("producto", "cuenta", "ahorro")),
    ]
    fails = 0
    print(f"BASE={BASE} customer={CUSTOMER} cid={cid[:8]}...")
    for q, keys in seq:
        st, text = turn(cid, q)
        low = text.lower()
        bad = "no pude armar" in low or "contrato válid" in low or "no se pudo generar" in low
        ok = (not bad) and any(k in low for k in keys)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{mark}] {st} | {q[:55]!r}")
        print(f"       {text[:140].replace(chr(10), ' ')}")
    print(f"TOTAL: {len(seq) - fails}/{len(seq)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
