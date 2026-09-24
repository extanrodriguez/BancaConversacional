"""Valida errores reportados (Fase1 + intent + video DAP) contra QA 8447.

Incluye casos personales (snapshot) y de conocimiento (FAQ/KB).

Uso:
  $env:GENESIS_VALIDATE_BASE="http://20.127.25.24:8447"
  $env:GENESIS_VALIDATE_CUSTOMER="726588"
  .\\.venv\\Scripts\\python.exe Test_local\\validate_reported_errors_8447.py

Opcional KB Excel (muestra FAQ):
  $env:GENESIS_KB_EXCEL_PATH="C:\\Users\\zeusa\\Downloads\\Base de Conocimiento IA VF01.xlsx"
  .\\.venv\\Scripts\\python.exe Test_local\\validate_reported_errors_8447.py --with-excel --excel-limit 25
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")
RESULTS = Path(__file__).resolve().parent / "results"
DEFAULT_EXCEL = os.getenv(
    "GENESIS_KB_EXCEL_PATH",
    r"c:\Users\zeusa\Downloads\Base de Conocimiento IA VF01.xlsx",
)


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str


def post(path: str, payload: dict, timeout: int = 120) -> dict:
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
    try:
        return post("/lab/login", {"customer_id": CUSTOMER})["conversation_id"]
    except Exception:
        return f"reported-{uuid.uuid4().hex[:10]}"


def turn(cid: str, question: str) -> tuple[dict, str]:
    data = post(
        "/turn",
        {
            "question": question,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )
    return data, reply_of(data)


def _bad(text: str) -> bool:
    low = (text or "").lower()
    return any(
        b in low
        for b in (
            "contrato válido",
            "contrato valido",
            "no se pudo generar una respuesta",
            "asesor se pondra",
            "asesor se pondrá",
            "numero de caso #",
            "número de caso #",
            "motor conversacional",
        )
    )


def _has(*parts: str, text: str) -> bool:
    low = (text or "").lower()
    return all(p.lower() in low for p in parts)


def _any(*parts: str, text: str) -> bool:
    low = (text or "").lower()
    return any(p.lower() in low for p in parts)


def check(name: str, ok: bool, detail: str) -> CaseResult:
    return CaseResult(name=name, ok=ok, detail=detail[:320])


# ---------------------------------------------------------------------------
# Casos reportados
# ---------------------------------------------------------------------------


def case_mision() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "Mision")
    ok = not _bad(txt) and _any("emprendedor", "instituc", "misión", "mision", text=txt)
    return check("KB: Mision", ok, txt)


def case_hablame_banco() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "hablame del banco")
    ok = not _bad(txt) and _any("banco", "emprendedor", "instituc", "santa cruz", text=txt)
    return check("KB: hablame del banco", ok, txt)


def case_reclamacion_canal() -> CaseResult:
    cid = login()
    d1, t1 = turn(cid, "¿cual es el proceso para una reclamacion?")
    ok1 = (
        not _bad(t1)
        and (
            _any("canal", "centro de contacto", "809", text=t1)
            or d1.get("status") == "CLARIFICATION_REQUIRED"
            or d1.get("mode") == "CLARIFICATION"
        )
        and "crédito no procesado" not in t1.lower()
    )
    _, t2 = turn(cid, "Centro de Contacto")
    ok2 = not _bad(t2) and ("809" in t2 or "contacto" in t2.lower())
    return check("KB: reclamacion→canal", ok1 and ok2, f"t1={t1[:140]} | t2={t2[:140]}")


def case_alcance() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "en que me puedes ayudar?")
    ok = not _bad(txt) and _any("saldo", "préstamo", "prestamo", "tarjeta", "producto", "ayud", text=txt)
    return check("Scope: en que me puedes ayudar", ok, txt)


def case_contratar_no_reclamacion() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "CUAL ES EL PROCESO PARA CONTRATAR UN PRODUCTO?")
    low = txt.lower()
    ok = not _bad(txt) and "reclam" not in low and _any(
        "solicitudesdigitales", "contratar", "digital", "producto", text=txt
    )
    return check("KB: contratar ≠ reclamacion", ok, txt)


def case_catalogo_tarjetas() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "¿CUALES TARJETAS OFRECE EL BANCO?")
    low = txt.lower()
    ok = (
        not _bad(txt)
        and _any("visa", "débito", "debito", "tarjeta", "crédito", "credito", text=txt)
        and "misión" not in low
        and "mision" not in low
    )
    return check("KB: catálogo tarjetas banco", ok, txt)


def case_cuenta_corriente_def() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "QUE ES UNA CUENTA CORRIENTE?")
    ok = not _bad(txt) and "corriente" in txt.lower() and "medio de pago" not in txt.lower()
    return check("KB: qué es cuenta corriente", ok, txt)


def case_cuentas_corrientes_ambigua() -> CaseResult:
    cid = login()
    data, txt = turn(cid, "CUENTAS CORRIENTES")
    low = txt.lower()
    ok = (
        not _bad(txt)
        and (
            data.get("status") == "CLARIFICATION_REQUIRED"
            or data.get("mode") == "CLARIFICATION"
            or _any("qué es", "que es", "definición", "definicion", "portafolio", "tienes", text=txt)
        )
        and "5446" not in txt
    )
    return check("Ambiguo: CUENTAS CORRIENTES", ok, f"{data.get('status')} | {txt}")


def case_fecha_pago_ambigua() -> CaseResult:
    cid = login()
    data, txt = turn(cid, "cuál es la fecha de pago")
    low = txt.lower()
    ok = (
        not _bad(txt)
        and (
            data.get("status") == "CLARIFICATION_REQUIRED"
            or data.get("mode") == "CLARIFICATION"
            or _any("préstamo", "prestamo", "tarjeta", "cuál", "cual", text=txt)
        )
        and "tarjetahabiente" not in low
        and "último día hábil" not in low
        and "ultimo dia habil" not in low
    )
    return check("Ambiguo: fecha de pago personal", ok, f"{data.get('status')} | {txt}")


def case_multicredito_condiciones() -> CaseResult:
    cid = login()
    _, txt = turn(cid, "cuáles son las condiciones de la Visa Multicrédito?")
    low = txt.lower()
    ok = not _bad(txt) and _any("multicrédito", "multicredito", "visa", "condici", text=txt)
    ok = ok and "reclam" not in low
    return check("KB: condiciones Multicrédito", ok, txt)


def case_certificados_list() -> CaseResult:
    cid = login()
    data, txt = turn(cid, "dame mis certificados")
    ok = not _bad(txt) and (
        data.get("status") == "CLARIFICATION_REQUIRED"
        or data.get("mode") == "CLARIFICATION"
        or _any("certificado", "depósito", "deposito", "plazo", "cual", "cuál", text=txt)
    )
    return check("Personal: listar certificados", ok, f"{data.get('status')} | {txt}")


def case_dap_digit_followup() -> CaseResult:
    """Video: tasa de un DAP → 'Y del 05809?' no debe ser saldo de ahorro."""
    cid = login()
    # Anclar en DAP (listado o pregunta de tasa)
    turn(cid, "dame mis certificados")
    d1, t1 = turn(cid, "cuál es la tasa de mi certificado 5511")
    # Si 5511 no existe en lab, intentar selección genérica
    if "tasa" not in t1.lower() and "5511" not in t1:
        turn(cid, "DEPOSITO_PLAZO_5511")
        d1, t1 = turn(cid, "cuál es la tasa")

    d2, t2 = turn(cid, "Y del 05809?")
    low2 = t2.lower()
    ok = (
        not _bad(t2)
        and "ahorro" not in low2
        and "12113" not in t2
        and (
            "tasa" in low2
            or "5809" in t2
            or "05809" in t2
            or d2.get("status") == "CLARIFICATION_REQUIRED"
            or _any("certificado", "depósito", "deposito", "plazo", text=t2)
        )
    )
    return check(
        "Video: Y del 05809? (DAP+tasa, no ahorro)",
        ok,
        f"prev={t1[:100]} | ans={t2[:200]}",
    )


def case_dap_correction() -> CaseResult:
    """Video: corrección 'del deposito a plazo…' reanuda DAP, no lista completa."""
    cid = login()
    turn(cid, "dame mis certificados")
    turn(cid, "DEPOSITO_PLAZO_5809")
    turn(cid, "cuál es la tasa")
    # Simular desvío a saldo (si el bot lo hace) y luego corrección
    turn(cid, "Y del 05809?")
    d, txt = turn(cid, "Del deposito a plazo fue que te pregunte")
    low = txt.lower()
    lists_all = ("5511" in txt and "8842" in txt) or ("cuál de tus" in low and "certificado" in low)
    ok = (
        not _bad(txt)
        and not lists_all
        and _any("tasa", "certificado", "depósito", "deposito", "plazo", "5809", text=txt)
    )
    return check("Video: corrección deposito a plazo", ok, f"{d.get('status')} | {txt}")


def case_dap_apk_selection() -> CaseResult:
    cid = login()
    turn(cid, "dame mis certificados")
    d, txt = turn(cid, "Depósito a plazo …5511\nDEPOSITO_PLAZO_5511")
    ok = not _bad(txt) and (
        "5511" in txt
        or _any("capital", "tasa", "vence", "vencimiento", "certificado", "depósito", "deposito", text=txt)
        or d.get("status") == "CLARIFICATION_REQUIRED"
    )
    # No debe responder saldo de ahorro
    ok = ok and "ahorro" not in txt.lower()
    return check("Personal: selección APK DAP 5511", ok, f"{d.get('status')} | {txt}")


CASES: list[Callable[[], CaseResult]] = [
    case_mision,
    case_hablame_banco,
    case_reclamacion_canal,
    case_alcance,
    case_contratar_no_reclamacion,
    case_catalogo_tarjetas,
    case_cuenta_corriente_def,
    case_cuentas_corrientes_ambigua,
    case_fecha_pago_ambigua,
    case_multicredito_condiciones,
    case_certificados_list,
    case_dap_apk_selection,
    case_dap_digit_followup,
    case_dap_correction,
]


def run_excel_sample(limit: int) -> list[CaseResult]:
    """Muestra de FAQ del Excel (intención KB)."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return [check("Excel KB", False, "openpyxl no instalado")]

    path = Path(DEFAULT_EXCEL)
    if not path.exists():
        return [check("Excel KB", False, f"No existe: {path}")]

    # Importar helpers del validador Excel existente
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate_excel_from_row79 as excel_v  # noqa: E402

    cases = excel_v.load_cases(path, from_row=79)
    faq_cases = [c for c in cases if not c.get("personal")]
    out: list[CaseResult] = []
    for row in faq_cases[:limit]:
        topic = row.get("topic") or ""
        expected = row.get("answer") or ""
        exprs = row.get("expressions") or []
        if not exprs:
            continue
        q = excel_v._expression_for_intent(exprs[0], topic)
        cid = login()
        _, txt = turn(cid, q)
        overlap = excel_v.overlap_score(expected, txt)
        ok = not _bad(txt) and (
            overlap >= 0.12
            or (topic and excel_v._norm(topic).split()[0] in excel_v._norm(txt))
        )
        out.append(
            check(
                f"Excel: {topic[:50]}",
                ok,
                f"overlap={overlap:.2f} | q={q[:60]} | {txt[:120]}",
            )
        )
    if not out:
        out.append(check("Excel KB", False, "Sin filas FAQ válidas en muestra"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-excel", action="store_true", help="Incluir muestra Excel KB")
    parser.add_argument("--excel-limit", type=int, default=20)
    args = parser.parse_args()

    print(f"BASE={BASE} CUSTOMER={CUSTOMER}")
    results: list[CaseResult] = []
    for fn in CASES:
        try:
            r = fn()
        except Exception as exc:
            r = check(fn.__name__, False, f"EXC: {exc}")
        results.append(r)
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.name}\n       {r.detail}")

    if args.with_excel:
        print("\n--- Excel KB sample ---")
        for r in run_excel_sample(args.excel_limit):
            results.append(r)
            mark = "PASS" if r.ok else "FAIL"
            print(f"[{mark}] {r.name}\n       {r.detail}")

    passed = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]
    print(f"\n=== {passed}/{len(results)} PASS ===")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / "reported_errors_8447.json"
    out_path.write_text(
        json.dumps(
            [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")
    if failed:
        print("FALLIDOS:")
        for r in failed:
            print(f" - {r.name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
