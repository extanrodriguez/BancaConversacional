"""Valida tasa del préstamo + reanudación tras otro tema (no FAQ definición)."""

from __future__ import annotations

import json
import os
import re
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


def turn(cid: str, q: str, selected_option_ref: str | None = None) -> dict:
    payload = {
        "question": q,
        "customer_id": CUSTOMER,
        "conversation_id": cid,
        "allow_lab_fallback": True,
    }
    if selected_option_ref:
        payload["selected_option_ref"] = selected_option_ref
    return post(
        "/turn",
        payload,
    )


def is_faq_definition(text: str) -> bool:
    t = (text or "").lower()
    return "tarifario" in t or "www.bsc.com.do" in t or "porcentaje anualizado establecido" in t


def is_personal_rate(text: str) -> bool:
    t = (text or "").lower()
    if is_faq_definition(t):
        return False
    return bool(re.search(r"tasa.+\d", t)) or ("%" in t and "tasa" in t)


def pick_loan_label(opts: list) -> str:
    for o in opts:
        label = str(o.get("label") or o.get("text") or o.get("value") or "")
        if "27615" in label or "7615" in label:
            return label
    if opts:
        return str(opts[0].get("label") or opts[0].get("text") or opts[0].get("value") or "")
    return "Préstamo ...27615"


def pick_loan_ref(opts: list) -> str | None:
    for option in opts:
        selection = option.get("selection") or {}
        ref = selection.get("selected_option_ref") or option.get("selected_option_ref")
        if ref:
            return str(ref)
    return None


def main() -> int:
    cases: list[tuple[str, bool]] = []

    # --- A: deíxis inmediata ---
    cid = login()
    r1 = turn(cid, "cuanto debo de mi prestamo")
    pick = pick_loan_label(options(r1))
    turn(cid, pick, pick_loan_ref(options(r1)))
    r3 = turn(cid, "que tasa de interes tiene")
    print(f"A deictic: {reply(r3)[:160]}")
    cases.append(("A_deictic_tasa", is_personal_rate(reply(r3))))

    # --- B: préstamo → misión → reanudar tasa ---
    cid = login()
    r1 = turn(cid, "cuanto debo de mi prestamo")
    pick = pick_loan_label(options(r1))
    turn(cid, pick, pick_loan_ref(options(r1)))
    r_m = turn(cid, "cual es la mision del banco")
    print(f"B mision: {reply(r_m)[:120]}")
    cases.append(("B_mision_ok", "misión" in reply(r_m).lower() or "mision" in reply(r_m).lower() or len(reply(r_m)) > 40))
    r_t = turn(cid, "que tasa de interes tiene")
    print(f"B resume tasa: {reply(r_t)[:160]}")
    cases.append(("B_resume_after_mision", is_personal_rate(reply(r_t))))

    # --- C: préstamo → saldo → reanudar tasa ---
    cid = login()
    r1 = turn(cid, "cuanto debo de mi prestamo")
    pick = pick_loan_label(options(r1))
    turn(cid, pick, pick_loan_ref(options(r1)))
    r_s = turn(cid, "cual es el saldo de mi cuenta de ahorros")
    print(f"C saldo: {reply(r_s)[:120]}")
    cases.append(("C_saldo_ok", "saldo" in reply(r_s).lower() or "ahorro" in reply(r_s).lower() or "dop" in reply(r_s).lower()))
    r_t = turn(cid, "que tasa de interes tiene")
    print(f"C resume tasa: {reply(r_t)[:160]}")
    cases.append(("C_resume_after_saldo", is_personal_rate(reply(r_t))))

    # --- D: definición FAQ intacta ---
    cid = login()
    r_d = turn(cid, "qué es tasa de interés")
    print(f"D definition: {reply(r_d)[:160]}")
    cases.append(("D_definition_faq", "tasa" in reply(r_d).lower() and not re.search(r"12\.5", reply(r_d))))

    # --- E: explícito con dígitos ---
    cid = login()
    r_e = turn(cid, "que tasa de interes tiene el prestamo 27615")
    print(f"E explicit: {reply(r_e)[:160]}")
    cases.append(("E_explicit", is_personal_rate(reply(r_e))))

    # --- F: secuencia reportada (certificado → préstamo singular → préstamos plural) ---
    cid = login()
    turn(cid, "dime la tasa de mis certificados")
    r_singular = turn(cid, "la tasa de mi prestamo")
    print(f"F singular: {reply(r_singular)[:200]}")
    cases.append(("F_singular_options", len(options(r_singular)) >= 2))
    r_plural = turn(cid, "si la tasa de mis prestamos")
    print(f"F plural: {reply(r_plural)[:240]}")
    plural_options = options(r_plural)
    cases.append((
        "F_plural_rate_cards",
        len(plural_options) >= 2
        and all((o.get("context") or {}).get("field") == "rate" for o in plural_options)
        and all("Moneda:" in (o.get("subtitle") or "") for o in plural_options),
    ))
    chosen = plural_options[0]
    selection = chosen.get("selection") or {}
    r_selected = turn(
        cid,
        selection.get("message") or chosen["label"],
        selection.get("selected_option_ref"),
    )
    print(f"F selected rate: {reply(r_selected)[:160]}")
    cases.append((
        "F_selected_rate",
        is_personal_rate(reply(r_selected)),
    ))

    passed = sum(1 for _, ok in cases if ok)
    total = len(cases)
    print(f"\nRESULT: {passed}/{total}")
    for name, ok in cases:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
