"""Runner local: matriz AX + muestra evaluable de Casos_Guia_BSC_236 vía intérprete/ejecutor.

No llama Azure ni Core. No inventa montos. Emite RESULTADOS parciales a stdout/JSON.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from genesis_cognitive.brain.plan_executor import execute_turn_plan
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "data" / "lab_portfolios" / "qa_726588_contract_demo.json"
CASOS = ROOT / "works" / "Casos_Guia_BSC_236.json"
OUT = ROOT / "works" / "RESULTADOS_CONTEXTUALES.json"


def _snap():
    return map_core_portfolio(json.loads(LAB.read_text(encoding="utf-8"))).snapshot


def _eval_question(snap, q: str) -> dict:
    t0 = time.perf_counter()
    try:
        plan = interpret_turn_plan(q, None, snapshot=snap)
        pex = execute_turn_plan(plan, snap, q)
        text = (pex.text or "")[:400]
        status = pex.status
        route = plan.source
        tasks = [
            {
                "id": t.id,
                "domain": t.domain,
                "object": t.object,
                "fields": list(t.fields or []),
                "entity": t.entity_ref,
                "status": t.status,
            }
            for t in (plan.tasks or [])
        ]
        return {
            "result": "PASS" if status in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED", "PARTIAL") else "FAIL",
            "status": status,
            "route": route,
            "tasks": tasks,
            "reply_sanitized": text,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "result": "FAIL",
            "status": "ERROR",
            "error_class": type(exc).__name__,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }


def main() -> int:
    snap = _snap()
    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    ax = [
        ("AX-TJ-01", "¿Cuál es el saldo de mi tarjeta joven?"),
        ("AX-TJ-02", "¿Cuál es la tasa de mi tarjeta joven?"),
        ("AX-PAY-01", "¿Cuál es mi fecha límite de pago?"),
        ("AX-REC-01", "¿Cómo realizo una reclamación?"),
        ("AX-FAL-01", "¿Cuál es el proceso de clientes fallecidos?"),
        (
            "AX-P01",
            "¿Cuánto debo en mi tarjeta de crédito, cuánto tengo disponible y cuándo es mi fecha límite de pago?",
        ),
        ("AX-LIST", "listame mis productos"),
    ]
    results = []
    for cid, q in ax:
        ev = _eval_question(snap, q)
        results.append({
            "case_id": cid,
            "precondition": "lab qa_726588_contract_demo",
            "question": q,
            "historical_label": None,
            "new_result": ev["result"],
            "evidence": ev,
            "version": "contextual-local",
        })

    # Inventario 236: ejecutar solo casos con pregunta simple (no multi-turno)
    executed = 0
    not_executed = 0
    for c in casos.get("cases", []):
        cid = c["case_id"]
        if c.get("turns"):
            results.append({
                "case_id": cid,
                "precondition": "multi-turn",
                "question": c.get("question"),
                "historical_label": c.get("historical_label"),
                "known_contradiction": c.get("known_contradiction"),
                "new_result": "NOT_EXECUTED",
                "reason": "multi-turn requiere sesión; runner local single-turn",
                "version": "contextual-local",
            })
            not_executed += 1
            continue
        q = c.get("question") or ""
        if not q or len(q) < 8:
            results.append({
                "case_id": cid,
                "new_result": "NOT_EXECUTED",
                "reason": "sin pregunta usable",
                "historical_label": c.get("historical_label"),
            })
            not_executed += 1
            continue
        ev = _eval_question(snap, q)
        # No usar etiqueta histórica como oráculo
        results.append({
            "case_id": cid,
            "precondition": "lab qa_726588_contract_demo",
            "question": q[:180],
            "historical_label": c.get("historical_label"),
            "known_contradiction": c.get("known_contradiction"),
            "visual_review": None,
            "new_result": ev["result"],
            "evidence": {
                "status": ev.get("status"),
                "route": ev.get("route"),
                "task_count": len(ev.get("tasks") or []),
                "reply_head": (ev.get("reply_sanitized") or "")[:160],
                "ms": ev.get("ms"),
            },
            "version": "contextual-local",
        })
        executed += 1

    summary = {
        "ax_pass": sum(1 for r in results if str(r["case_id"]).startswith("AX-") and r.get("new_result") == "PASS"),
        "ax_total": sum(1 for r in results if str(r["case_id"]).startswith("AX-")),
        "guia_executed": executed,
        "guia_not_executed": not_executed,
        "guia_pass": sum(
            1 for r in results
            if not str(r["case_id"]).startswith("AX-") and r.get("new_result") == "PASS"
        ),
        "guia_fail": sum(
            1 for r in results
            if not str(r["case_id"]).startswith("AX-") and r.get("new_result") == "FAIL"
        ),
    }
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "portfolio": "qa_726588_contract_demo.json",
        "note": "Etiquetas históricas no son oráculo. new_result es ejecución local intérprete/ejecutor.",
        "summary": summary,
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
