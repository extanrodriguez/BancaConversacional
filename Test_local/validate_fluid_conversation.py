"""Conversación fluida: orden aleatorio multi-tema en la misma sesión."""

from __future__ import annotations

import json
import os
import random
import sys
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")

CASES = [
    ("banco", "hablame del banco", ("santa cruz", "instituc", "emprendedor")),
    ("reclam", "dame el proceso de reclamaciones", ("reclam", "809")),
    ("cuentas_cat", "dime cuales productos de cuentas puedo contratar con el banco", ("cuenta", "ahorro")),
    ("listado", "dame el listado de mis productos", ("producto", "cuenta", "préstamo", "prestamo")),
    ("mis_prestamos", "dame informacion de mis prestamos", ("préstamo", "prestamo", "27615", "90123")),
    ("catalogo_pr", "Dame informacion de los prestamos que puedo contratar en el banco", ("préstamo", "prestamo", "personal", "hipotec", "vehícul", "garant")),
    ("saldo", "cual es mi saldo", ("saldo", "disponible", "50000", "dop")),
    ("mod", "COÑO", ("consultas bancarias", "indícame", "indicame", "ayudarte")),
]


def post(path: str, payload: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reply(data: dict) -> str:
    app = data.get("app_channel") or {}
    return (app.get("client_response") or data.get("client_response") or "").strip()


def main() -> int:
    rounds = int(os.getenv("GENESIS_FLUID_ROUNDS", "5"))
    seed = int(os.getenv("GENESIS_FLUID_SEED", "7"))
    rng = random.Random(seed)
    cid = post("/lab/login", {"customer_id": CUSTOMER})["conversation_id"]
    fails = 0
    total = 0
    print(f"BASE={BASE} customer={CUSTOMER} rounds={rounds} cid={cid[:8]}...")
    for r in range(1, rounds + 1):
        order = CASES[:]
        rng.shuffle(order)
        for cid_case, q, keys in order:
            total += 1
            d = post(
                "/turn",
                {
                    "question": q,
                    "customer_id": CUSTOMER,
                    "conversation_id": cid,
                    "allow_lab_fallback": True,
                },
            )
            text = reply(d)
            low = text.lower()
            bad = any(
                b in low
                for b in (
                    "no pude armar",
                    "contrato válid",
                    "contrato valid",
                    "no se pudo generar",
                    "asesor se pondra",
                    "numero de caso #",
                )
            )
            ok = (not bad) and any(k in low for k in keys)
            if not ok:
                fails += 1
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] r{r} {cid_case} | {q[:48]!r} | {(text[:90]).encode('ascii','replace').decode('ascii')}")
        print(f"--- ronda {r} ---")
    # logout invalida sesión
    post("/lab/logout", {"customer_id": CUSTOMER, "conversation_id": cid})
    print(f"TOTAL {total - fails}/{total} PASS | logout SESSION_CLOSED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
