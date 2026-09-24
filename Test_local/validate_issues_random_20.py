"""Control aleatorio x20 de preguntas reportadas en issues (APK / pantallas).

Uso:
  $env:GENESIS_VALIDATE_BASE=\"http://20.127.25.24:8447\"
  $env:GENESIS_VALIDATE_CUSTOMER=\"726588\"
  .\\.venv\\Scripts\\python.exe Test_local\\validate_issues_random_20.py
  .\\.venv\\Scripts\\python.exe Test_local\\validate_issues_random_20.py --rounds 20
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")
RESULTS = Path(__file__).resolve().parent / "results"


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


def reply_of(data: dict) -> str:
    app = data.get("app_channel") or {}
    return (
        app.get("client_response")
        or data.get("client_response")
        or data.get("reply")
        or ""
    ).strip()


def login() -> str:
    return post("/lab/login", {"customer_id": CUSTOMER})["conversation_id"]


def turn(cid: str, question: str) -> dict:
    return post(
        "/turn",
        {
            "question": question,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )


def _bad_generic(text: str) -> bool:
    low = (text or "").lower()
    bad = (
        "contrato válido",
        "contrato valido",
        "no se pudo generar una respuesta",
        "no pude completar",
        "motor conversacional",
        "asesor se pondra",
        "asesor se pondrá",
        "numero de caso #",
        "número de caso #",
    )
    return any(b in low for b in bad)


def ok_banco(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    return any(k in low for k in ("santa cruz", "instituc", "emprendedor", "visión", "vision", "misión", "mision", "banco"))


def ok_portfolio(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    if "contrato" in low and "válid" in low.replace("i", "í"):
        return False
    return any(k in low for k in ("producto", "cuenta", "préstamo", "prestamo", "tarjeta", "ahorro", "activo"))


def ok_mi_prestamo(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    # clarificación multi-préstamo o detalle
    if "sobre cuál" in low or "sobre cual" in low:
        return "préstamo" in low or "prestamo" in low
    return any(
        k in low
        for k in (
            "capital", "adeud", "mora", "tasa", "cuota", "préstamo", "prestamo",
            "vencimiento", "pendiente", "7615", "0123", "27615", "90123",
        )
    )


def ok_catalogo_prestamos(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    if "productos activos" in low or "tus productos" in low:
        return False
    # No aceptar catálogo de cuentas cuando preguntaron préstamos
    if "cuenta de ahorro" in low and "préstamo" not in low and "prestamo" not in low:
        return False
    return any(
        k in low
        for k in ("préstamo", "prestamo", "personal", "hipotec", "vehícul", "vehiculo", "garant")
    )


def ok_productos_solicitar(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    # No es el listado de "mis" productos del portafolio
    if "tus productos activos" in low or "estos son tus productos" in low:
        return False
    return any(
        k in low
        for k in (
            "cuenta", "ahorro", "corriente", "préstamo", "prestamo", "tarjeta",
            "solicitar", "contratar", "ofrece", "puedes solicitar",
        )
    )


def ok_reclamacion(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    return any(
        k in low
        for k in ("reclam", "809.726", "809 726", "centro de contacto", "bsc en línea", "bsc en linea", "canal")
    )


def ok_saldo(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    return any(k in low for k in ("saldo", "disponible", "rd$", "dop", "pesos", "cuenta", "balance"))


def ok_moderation(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    # no saludo genérico puro tipo ¡Hola!
    if low.startswith("¡hola") or low.startswith("hola,"):
        if "consultas bancarias" not in low and "qué necesitas" not in low and "que necesitas" not in low:
            return False
    return any(
        k in low
        for k in ("consultas bancarias", "qué necesitas", "que necesitas", "puedo ayudarte", "respetuoso")
    ) or len(text) > 20


def ok_cuentas_contratar(text: str, data: dict) -> bool:
    low = text.lower()
    if _bad_generic(text):
        return False
    return any(k in low for k in ("ahorro", "corriente", "cuenta"))


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    check: Callable[[str, dict], bool]
    fresh_session: bool = True


CASES: list[Case] = [
    Case("banco_santa_cruz", "Hablame del banco santa cruz", ok_banco),
    Case("listado_productos", "dame el listado de mis productos", ok_portfolio),
    Case("listado_typo", "dame el listaddo de mis productos", ok_portfolio),
    Case("listame_productos", "listame mis productos", ok_portfolio),
    Case("mi_prestamo", "dame informacion de mi prestamo", ok_mi_prestamo),
    Case("mi_prestamos", "dame informacion de mi prestamos", ok_mi_prestamo),
    Case("catalogo_prestamos", "Dame informacion de los prestamos que puedo contratar en el banco", ok_catalogo_prestamos),
    Case("productos_solicitar", "Que productos puedo solicitar", ok_productos_solicitar),
    Case("cuentas_banco", "dime cuales productos de cuentas puedo contratar en el banco", ok_cuentas_contratar),
    Case("reclamaciones", "dame el proceso de reclamaciones", ok_reclamacion),
    Case("saldo", "cual es mi saldo", ok_saldo),
    Case("moderation", "COÑO", ok_moderation),
]


def run_once(case: Case) -> dict:
    try:
        cid = login() if case.fresh_session else login()
        data = turn(cid, case.question)
        text = reply_of(data)
        ok = bool(text) and case.check(text, data) and not _bad_generic(text)
        return {
            "id": case.id,
            "question": case.question,
            "ok": ok,
            "status": data.get("status"),
            "mode": data.get("mode"),
            "intent": ((data.get("actions") or [{}])[0].get("intent_id") if data.get("actions") else None),
            "reply": text[:350],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": case.id,
            "question": case.question,
            "ok": False,
            "status": "ERROR",
            "mode": None,
            "intent": None,
            "reply": str(exc)[:350],
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=20, help="Repeticiones aleatorias del set completo")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    rows: list[dict] = []
    passes = fails = 0

    print("=" * 78)
    print(f"CONTROL ISSUES x{args.rounds} — {BASE} — customer={CUSTOMER}")
    print(f"Casos por ronda: {len(CASES)} | Total turnos: {args.rounds * len(CASES)}")
    print("=" * 78)

    for r in range(1, args.rounds + 1):
        order = CASES[:]
        rng.shuffle(order)
        round_fail = 0
        for case in order:
            row = run_once(case)
            row["round"] = r
            rows.append(row)
            if row["ok"]:
                passes += 1
                mark = "PASS"
            else:
                fails += 1
                round_fail += 1
                mark = "FAIL"
            q_ascii = case.question.encode("ascii", "replace").decode("ascii")
            print(f"[{mark}] r{r} {case.id} | {q_ascii[:50]!r} | {row.get('status')} | {(row.get('reply') or '')[:90].encode('ascii','replace').decode('ascii')}")
        print(f"--- ronda {r}/{args.rounds} fallos={round_fail} ---")

    total = passes + fails
    rate = (passes / total) if total else 0.0
    by_id: dict[str, dict[str, int]] = {}
    for row in rows:
        d = by_id.setdefault(row["id"], {"pass": 0, "fail": 0})
        if row["ok"]:
            d["pass"] += 1
        else:
            d["fail"] += 1

    summary = {
        "base": BASE,
        "customer_id": CUSTOMER,
        "rounds": args.rounds,
        "seed": args.seed,
        "pass": passes,
        "fail": fails,
        "total": total,
        "pass_rate": rate,
        "by_case": by_id,
        "failures": [r for r in rows if not r["ok"]],
        "rows": rows,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"issues_random20_{CUSTOMER}_8447.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"TOTAL {passes}/{total} PASS ({rate * 100:.1f}%)")
    print("Por caso:")
    for cid, d in sorted(by_id.items()):
        t = d["pass"] + d["fail"]
        print(f"  {cid}: {d['pass']}/{t}")
    if summary["failures"]:
        print(f"\nFallos ({len(summary['failures'])}):")
        for f in summary["failures"][:30]:
            print(f"  - r{f['round']} {f['id']}: {(f.get('reply') or '')[:120]}")
    print(f"Detalle: {out}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
