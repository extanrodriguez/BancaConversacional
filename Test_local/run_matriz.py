"""Ejecuta los 77 casos de Matriz_Cuentas (Excel) contra la cognitiva local.

Uso:
  .\\Test_local\\start_local.ps1
  .\\.venv\\Scripts\\python.exe scripts\\generate_matriz_casos.py
  .\\.venv\\Scripts\\python.exe Test_local\\run_matriz.py
  .\\.venv\\Scripts\\python.exe Test_local\\run_matriz.py --ids 4,6,21
  .\\.venv\\Scripts\\python.exe Test_local\\run_matriz.py --todas
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

MATRIZ = HERE / "data" / "matriz_casos.json"
ESCENARIOS = HERE / "data" / "escenarios.json"
RESULTS = HERE / "results"


def _app_channel(resp: dict[str, Any]) -> dict[str, Any]:
    return resp.get("app_channel") or {}


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


def eval_caso(caso: dict[str, Any], resp: dict[str, Any], question: str = "") -> tuple[bool, str]:
    app = _app_channel(resp)
    status = app.get("status")
    text = str(app.get("client_response") or "")
    cid = caso["id"]
    q = (question or "").lower()
    reasons: list[str] = []

    hall = _hallucination(text)
    if hall:
        reasons.append(hall)

    expect = caso.get("expect_status")
    if cid == 9:
        if "4587" in q and "7731" in q:
            expect = "VALID_CONTRACT"
            if status != "VALID_CONTRACT":
                reasons.append(f"status={status} esperado=VALID_CONTRACT (multi-cuenta)")
            if "4587" not in text or "7731" not in text:
                reasons.append("faltan ambas cuentas 4587 y 7731")
        elif "dos cuentas" in q:
            expect = "requires_selection"
    if cid == 22 and any(x in q for x in ("6582", "9147", "terminada en")):
        expect = "VALID_CONTRACT"
        digit = next((d for d in ("6582", "9147") if d in q), None)
        if digit and digit not in text:
            reasons.append(f"falta tarjeta {digit} en respuesta")
    if cid in (24, 34) and re.search(r"\d{4}", q):
        digits = re.findall(r"\d{4,}", q)
        for d in digits:
            if d not in text and status == "VALID_CONTRACT":
                reasons.append(f"falta referencia {d}")

    if expect == "requires_selection":
        if status != "requires_selection":
            reasons.append(f"status={status} esperado=requires_selection")
        opts = app.get("options") or []
        min_opts = caso.get("expect_options_min") or 2
        if len(opts) < min_opts:
            reasons.append(f"options={len(opts)} esperado>={min_opts}")
        if caso.get("must_not_show_balance") and _has_balance_leak(text):
            reasons.append("mostró montos antes de seleccionar")
    elif expect == "VALID_CONTRACT":
        if status not in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED", "NON_OPERATIONAL", "requires_selection"):
            reasons.append(f"status={status}")

    for token in caso.get("must_contain_any") or []:
        if token.lower() not in text.lower():
            reasons.append(f"falta token esperado '{token}'")

    return not reasons, "; ".join(reasons) if reasons else "ok"


def run(endpoint: str, todas: bool, ids: set[int] | None) -> int:
    if not MATRIZ.exists():
        print(f"Falta {MATRIZ}. Ejecuta: python scripts/generate_matriz_casos.py")
        return 2

    data = json.loads(MATRIZ.read_text(encoding="utf-8"))
    catalog = json.loads(ESCENARIOS.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in catalog["escenarios"]}
    orch = OrquestadorLocal(endpoint=endpoint)
    fails = 0
    total = 0
    rows: list[dict[str, Any]] = []

    for caso in data["casos"]:
        if ids and caso["id"] not in ids:
            continue
        exprs = list(caso.get("expresiones") or [])
        if not exprs:
            continue
        if not todas:
            exprs = exprs[:1]

        esc = by_id.get(caso["escenario"])
        if not esc:
            print(f"SKIP #{caso['id']} escenario desconocido {caso['escenario']}")
            continue

        envelope = load_portfolio(esc["portfolio"])
        for question in exprs:
            orch.nueva_sesion()
            orch.cargar_portafolio(envelope)
            prior = caso.get("prior_turn")
            if prior:
                orch.preguntar(prior)
            resp = orch.preguntar(question)
            app = _app_channel(resp)
            total += 1
            ok, reason = eval_caso(caso, resp, question)
            if not ok:
                fails += 1
            text = str(app.get("client_response") or "")
            rows.append({
                "id": caso["id"],
                "escenario": caso["escenario"],
                "question": question,
                "ok": ok,
                "reason": reason,
                "status": app.get("status"),
                "intent": app.get("intent_id"),
                "options": len(app.get("options") or []),
                "response": text,
            })
            mark = "PASS" if ok else "FAIL"
            print(
                f"{mark} #{caso['id']} [{caso['escenario']}] {question[:72]} "
                f"-> {app.get('status')}/{app.get('intent_id')} ({reason})"
            )
            if not ok:
                print(f"    {text[:200]}")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "matriz_ultimo.json"
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
    print(f"\n{total - fails}/{total} OK -> {out}")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8445")
    parser.add_argument("--todas", action="store_true", help="Todas las expresiones por fila Excel")
    parser.add_argument("--ids", default=None, help="Ids separados por coma, ej. 4,6,21")
    args = parser.parse_args()
    ids = None
    if args.ids:
        ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
    return run(args.endpoint, args.todas, ids)


if __name__ == "__main__":
    raise SystemExit(main())
