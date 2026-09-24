"""Prueba usuario 726588 en 8447: Excel (mvp_preguntas) + casos Fase 1."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")
ROOT = Path(__file__).resolve().parents[1]
PREGUNTAS = ROOT / "interfaz Prueba" / "mvp_preguntas.json"

# Subconjunto representativo del Excel (saldo, aclaración, tarjeta, préstamo, portafolio)
EXCEL_IDS = {1, 4, 5, 7, 14, 21, 30, 40, 50}

FASE1 = [
    "Mision",
    "Hablame del banco santa cruz",
    "¿en que me puedes ayudar?",
    "proceso para una reclamacion",
    "dame mis productos",
    "dame informacion de mi prestamo",
    "¿Cuál es mi saldo?",
    "COÑO",
]


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
        or data.get("reply")
        or ""
    ).strip()


def login() -> tuple[str, dict]:
    st, data = post("/lab/login", {"customer_id": CUSTOMER})
    if st != 200 or not data.get("conversation_id"):
        raise RuntimeError(f"login falló: {st} {data}")
    return data["conversation_id"], data


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


def is_bad(txt: str) -> bool:
    low = txt.lower()
    return (
        not txt
        or "asesor se pondra" in low
        or "numero de caso" in low
        or "contrato válido" in low
        or "contrato valido" in low
        or "no se pudo generar" in low
    )


def main() -> int:
    print("=" * 72)
    print(f"PRUEBA EXCEL + FASE1 — user={CUSTOMER} base={BASE}")
    print("=" * 72)

    cid, login_data = login()
    print(
        f"login OK name={login_data.get('display_name')} "
        f"products={login_data.get('products_count')} "
        f"portfolio={login_data.get('portfolio')} cid={cid[:8]}..."
    )
    print()

    results: list[tuple[str, bool, str]] = []

    # --- Fase 1 / humo ---
    for q in FASE1:
        # sesión fresca por pregunta (evita pending de aclaración)
        cid, _ = login()
        st, data, txt = turn(cid, q)
        status = data.get("status") or (data.get("app_channel") or {}).get("status")
        ok = st == 200 and not is_bad(txt)
        # reclamación: aclaración de canal es OK
        if "reclamacion" in q.lower() or "reclamación" in q.lower():
            ok = st == 200 and (
                "canal" in txt.lower()
                or "809" in txt
                or status in ("CLARIFICATION_REQUIRED", "requires_selection")
            )
        if q.upper() == "COÑO":
            ok = st == 200 and "consultas bancarias" in txt.lower()
        results.append((f"F1 {q}", ok, f"{status} | {txt[:160].replace(chr(10), ' ')}"))

    # --- Excel subset ---
    casos = json.loads(PREGUNTAS.read_text(encoding="utf-8")).get("casos") or []
    for caso in casos:
        if caso.get("id") not in EXCEL_IDS:
            continue
        exprs = list(caso.get("expresiones") or [])
        if not exprs:
            continue
        q = exprs[0]
        cid, _ = login()
        st, data, txt = turn(cid, q)
        status = data.get("status") or (data.get("app_channel") or {}).get("status")
        ok = st == 200 and not is_bad(txt)
        # ambigüedad esperada: requires_selection también OK
        if (caso.get("ambiguedad") or "").lower() in ("sí", "si", "posible"):
            ok = st == 200 and (
                not is_bad(txt)
                or status in ("CLARIFICATION_REQUIRED", "requires_selection")
            )
            if status in ("CLARIFICATION_REQUIRED", "requires_selection") and txt:
                ok = True
        label = f"EX #{caso['id']} {q}"
        results.append((label, ok, f"{status} | {txt[:160].replace(chr(10), ' ')}"))

    fails = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{mark}] {name}")
        print(f"       {detail}")
        print()

    print(f"TOTAL: {len(results) - fails}/{len(results)} PASS (user={CUSTOMER})")
    out = Path(__file__).resolve().parent / "results" / "excel_726588_8447.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "base": BASE,
                "customer_id": CUSTOMER,
                "pass": len(results) - fails,
                "total": len(results),
                "rows": [{"name": n, "ok": o, "detail": d} for n, o, d in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Resultados: {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
