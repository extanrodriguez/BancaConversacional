"""Corre preguntas del Excel contra la cognitiva local.

Uso:
  1) start_local.ps1   (levanta genesis en :8445)
  2) python Test_local/run_mvp.py
  3) python Test_local/run_mvp.py --escenario prestamo_unico
  4) python Test_local/run_mvp.py --smoke
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "interfaz Prueba"))

from orquestador_local import OrquestadorLocal, load_portfolio  # noqa: E402

PREGUNTAS = ROOT / "interfaz Prueba" / "mvp_preguntas.json"
ESCENARIOS = HERE / "data" / "escenarios.json"
MATRIZ_MAPPING = HERE / "data" / "matriz_mapping.json"
RESULTS = HERE / "results"

_MONTHS = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}


def compact_es_date(text: str) -> str:
    match = re.search(r"(\d{1,2})\s+de\s+([a-zA-Záéíóúñ]+)\s+de\s+(\d{4})", text.lower())
    if not match:
        return ""
    day, month, year = match.groups()
    mm = _MONTHS.get(month)
    if not mm:
        return ""
    return f"{year}-{mm}-{int(day):02d}"

SMOKE = [
    {"escenario": "cuenta_unica", "question": "¿Cuál es mi saldo?", "expect_intent": "ACCOUNT_BALANCE_READ"},
    {"escenario": "cuentas_multi", "question": "¿Cuál es mi saldo?", "expect_status": "requires_selection", "must_contain": "4587"},
    {"escenario": "cuentas_multi", "question": "¿Cuánto me queda?", "expect_status": "requires_selection", "must_contain": "7731"},
    {"escenario": "cuentas_multi", "question": "¿Cuál es mi límite?", "expect_status": "VALID_CONTRACT", "must_contain": "tarjeta"},
    {"escenario": "tarjeta_unica", "question": "¿Cuándo corta mi tarjeta?", "expect_intent": "CREDIT_CARD_DETAIL_READ", "must_contain": "corte"},
    {"escenario": "tarjeta_unica", "question": "¿Cuál es mi límite?", "expect_intent": "CREDIT_CARD_DETAIL_READ"},
    {"escenario": "cuentas_multi", "question": "Muéstrame mis últimos movimientos", "expect_status": "requires_selection"},
    {"escenario": "cuenta_unica", "question": "Necesito transferir dinero", "expect_status": "UNSUPPORTED", "must_contain": "habilit"},
    {"escenario": "prestamo_unico", "question": "¿Cuánto debo de mi préstamo?", "expect_intent": "LOAN_DETAIL_READ", "must_contain": "29255"},
    {"escenario": "prestamo_unico", "question": "¿Cuánto pago de cuota?", "expect_intent": "LOAN_DETAIL_READ", "must_contain": "32000"},
    {"escenario": "prestamo_unico", "question": "¿Qué tasa tiene mi préstamo?", "expect_intent": "LOAN_DETAIL_READ", "must_contain": "10"},
    {"escenario": "prestamo_unico", "question": "¿Cuándo vence mi próxima cuota?", "expect_intent": "LOAN_DETAIL_READ", "must_contain": "2026-04-07"},
    {"escenario": "prestamo_unico", "question": "¿Cuánto me prestaron?", "expect_intent": "LOAN_DETAIL_READ", "must_contain": "800000"},
    {"escenario": "prestamo_unico", "question": "¿Cuánto necesito para cancelar el préstamo?", "expect_intent": "LOAN_DETAIL_READ", "must_contain": "no está disponible"},
    {"escenario": "prestamos_tipos", "question": "¿Cuánto debo?", "expect_status": "requires_selection"},
    {"escenario": "prestamos_tipos", "question": "¿Cuánto debo del hipotecario?", "expect_intent": "LOAN_DETAIL_READ"},
    {"escenario": "tarjeta_unica", "question": "¿Cuánto tengo disponible en mi tarjeta?", "expect_intent": "CREDIT_CARD_DETAIL_READ"},
    {"escenario": "dap_unico", "question": "¿Cuál es la tasa de mi depósito a plazo?", "expect_intent": "TERM_DEPOSIT_DETAIL_READ"},
]


def _app_channel(resp: dict[str, Any]) -> dict[str, Any]:
    return resp.get("app_channel") or {}


def _eval_case(resp: dict[str, Any], spec: dict[str, Any]) -> tuple[bool, str]:
    app = _app_channel(resp)
    status = app.get("status")
    intent = app.get("intent_id")
    text = str(app.get("client_response") or "")
    reasons: list[str] = []
    if spec.get("expect_status") and status != spec["expect_status"]:
        reasons.append(f"status={status} esperado={spec['expect_status']}")
    if spec.get("expect_status") == "requires_selection":
        opts = app.get("options") or []
        if len(opts) < 2:
            reasons.append(f"options={len(opts)} esperado>=2")
    if spec.get("expect_intent") and intent != spec["expect_intent"]:
        reasons.append(f"intent={intent} esperado={spec['expect_intent']}")
    token = spec.get("must_contain")
    if token:
        haystack = (text + " " + compact_es_date(text)).lower()
        if token.lower() not in haystack and token.replace("-", "") not in re.sub(r"\D", "", text):
            compact = re.sub(r"[^\d.]", "", text.replace(",", ""))
            if token.replace(",", "") not in compact:
                reasons.append(f"no aparece '{token}' en: {text[:160]}")
    ok = not reasons
    return ok, "; ".join(reasons) if reasons else "ok"


def run_smoke(endpoint: str) -> int:
    catalog = json.loads(ESCENARIOS.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in catalog["escenarios"]}
    orch = OrquestadorLocal(endpoint=endpoint)
    results: list[dict[str, Any]] = []
    loaded: str | None = None
    fails = 0
    for spec in SMOKE:
        esc = by_id[spec["escenario"]]
        orch.nueva_sesion()
        envelope = load_portfolio(esc["portfolio"])
        load_resp = orch.cargar_portafolio(envelope)
        if load_resp.get("status") not in ("CONTEXT_LOADED", "CONTEXT_REFRESHED"):
            print("FAIL load", esc["portfolio"], load_resp)
            fails += 1
            continue
        loaded = esc["portfolio"]
        resp = orch.preguntar(spec["question"])
        ok, reason = _eval_case(resp, spec)
        app = _app_channel(resp)
        row = {
            "escenario": spec["escenario"],
            "question": spec["question"],
            "ok": ok,
            "reason": reason,
            "status": app.get("status"),
            "intent": app.get("intent_id"),
            "response": app.get("client_response"),
        }
        results.append(row)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"{mark} [{spec['escenario']}] {spec['question']}\n    {app.get('status')} / {app.get('intent_id')}\n    {app.get('client_response')}\n    {reason}\n")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "smoke_ultimo.json"
    out.write_text(
        json.dumps(
            {
                "when": datetime.now(tz=timezone.utc).isoformat(),
                "endpoint": endpoint,
                "fails": fails,
                "total": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Resultado: {len(results) - fails}/{len(results)} OK -> {out}")
    return 1 if fails else 0


def _load_matriz_mapping() -> dict[str, Any]:
    data = json.loads(MATRIZ_MAPPING.read_text(encoding="utf-8"))
    return {
        "case_scenario": {int(k): v for k, v in data["case_scenario"].items()},
        "prior_turn": {int(k): v for k, v in data.get("prior_turn", {}).items()},
        "requires_selection_ids": set(data.get("requires_selection_ids") or []),
        "clarify_ids": set(data.get("clarify_ids") or []),
        "unavailable_ids": set(data.get("unavailable_ids") or []),
        "no_product_ids": set(data.get("no_product_ids") or []),
    }


MATRIZ = _load_matriz_mapping()
CASE_SCENARIO = MATRIZ["case_scenario"]
PRIOR_TURN = MATRIZ["prior_turn"]
REQUIRES_SELECTION_IDS = MATRIZ["requires_selection_ids"]
CLARIFY_IDS = MATRIZ["clarify_ids"]
UNAVAILABLE_IDS = MATRIZ["unavailable_ids"]
NO_PRODUCT_IDS = MATRIZ["no_product_ids"]


def _hallucination(text: str) -> str | None:
    if re.search(r"terminad[oa] en \d{4}-\d{2}", text, re.I):
        return "mascara con fecha"
    if re.search(r"terminad[oa] en XXXX", text, re.I):
        return "mascara XXXX"
    return None


def _has_balance_leak(text: str) -> bool:
    if re.search(r"RD\$?\s*[\d.,]+", text, re.I):
        return True
    if re.search(r"US\$?\s*[\d.,]+", text, re.I):
        return True
    return bool(re.search(r"\b\d{1,3}(?:[.,]\d{3})+[.,]\d{2}\b", text))


def _eval_excel(caso: dict[str, Any], resp: dict[str, Any]) -> tuple[bool, str]:
    app = _app_channel(resp)
    status = app.get("status")
    text = str(app.get("client_response") or "")
    cid = caso["id"]
    reasons: list[str] = []
    hall = _hallucination(text)
    if hall:
        reasons.append(hall)
    amb = (caso.get("ambiguedad") or "").strip().lower()
    needs_selection = cid in REQUIRES_SELECTION_IDS or (
        cid in CLARIFY_IDS and amb == "sí"
    )
    if needs_selection:
        if status != "requires_selection":
            reasons.append(f"status={status} esperado=requires_selection")
        opts = app.get("options") or []
        if len(opts) < 2:
            reasons.append(f"options={len(opts)} esperado>=2")
        if cid in REQUIRES_SELECTION_IDS and _has_balance_leak(text):
            reasons.append("mostró montos antes de seleccionar")
    elif cid in NO_PRODUCT_IDS:
        low = text.lower()
        if "no " not in low and "sin " not in low:
            reasons.append("se esperaba indicar ausencia de producto")
    elif cid in UNAVAILABLE_IDS:
        if "no está disponible" not in text.lower() and "no estan disponibles" not in text.lower() and "no están disponibles" not in text.lower():
            reasons.append("se esperaba no alucinar el dato ausente")
    else:
        if status not in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED", "NON_OPERATIONAL"):
            reasons.append(f"status={status}")
    return not reasons, "; ".join(reasons) if reasons else "ok"


def run_excel(endpoint: str, escenario_id: str | None, producto: str | None, todas: bool, ids: set[int] | None = None) -> int:
    preguntas = json.loads(PREGUNTAS.read_text(encoding="utf-8"))["casos"]
    catalog = json.loads(ESCENARIOS.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in catalog["escenarios"]}
    orch = OrquestadorLocal(endpoint=endpoint)
    fails = 0
    total = 0
    rows = []
    for caso in preguntas:
        if ids and caso["id"] not in ids:
            continue
        if escenario_id and CASE_SCENARIO.get(caso["id"]) != escenario_id:
            continue
        if producto and producto.lower() not in (caso.get("producto") or "").lower() and producto.lower() not in (caso.get("funcionalidad") or "").lower():
            continue
        exprs = list(caso.get("expresiones") or [])
        if not exprs:
            continue
        if not todas:
            exprs = exprs[:1]
        esc_id = CASE_SCENARIO.get(caso["id"], "real_core")
        esc = by_id[esc_id]
        envelope = load_portfolio(esc["portfolio"])
        for question in exprs:
            orch.nueva_sesion()
            orch.cargar_portafolio(envelope)
            prior = PRIOR_TURN.get(caso["id"])
            if prior:
                orch.preguntar(prior)
            resp = orch.preguntar(question)
            app = _app_channel(resp)
            total += 1
            ok, reason = _eval_excel(caso, resp)
            if not ok:
                fails += 1
            text = str(app.get("client_response") or "")
            rows.append(
                {
                    "id": caso["id"],
                    "escenario": esc_id,
                    "intencion": caso.get("intencion"),
                    "question": question,
                    "ok": ok,
                    "reason": reason,
                    "status": app.get("status"),
                    "intent": app.get("intent_id"),
                    "response": text,
                }
            )
            print(
                f"{'PASS' if ok else 'FAIL'} #{caso['id']} [{esc_id}] {question[:70]} "
                f"-> {app.get('status')}/{app.get('intent_id')} {reason}"
            )
            print(f"    {text[:180]}")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "excel_ultimo.json"
    out.write_text(
        json.dumps(
            {
                "when": datetime.now(tz=timezone.utc).isoformat(),
                "endpoint": endpoint,
                "fails": fails,
                "total": total,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{total - fails}/{total} OK -> {out}")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8445")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--excel", action="store_true")
    parser.add_argument("--matriz", action="store_true", help="Alias de --excel --todas (77 filas Matriz_Cuentas)")
    parser.add_argument("--escenario", default=None)
    parser.add_argument("--producto", default=None)
    parser.add_argument("--ids", default=None, help="Lista de ids Excel separados por coma")
    args = parser.parse_args()
    ids = None
    if args.ids:
        ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
    if args.matriz:
        args.excel = True
        args.todas = True
    if args.excel or args.escenario or args.producto or ids:
        return run_excel(args.endpoint, args.escenario, args.producto, args.todas, ids)
    return run_smoke(args.endpoint)


if __name__ == "__main__":
    raise SystemExit(main())
