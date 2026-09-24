# -*- coding: utf-8 -*-
"""Grupo representativo guía — POST /turn local (TestClient), Search real + AOAI real."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "works" / "azure_mejora" / "scripts"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

os.environ["GENESIS_SESSION_BACKEND"] = "memory"
os.environ.pop("GENESIS_REDIS_URL", None)
os.environ["GENESIS_REDIS_REQUIRED"] = "0"
os.environ["GENESIS_SEMANTIC_MODE"] = "azure_plan"
os.environ["GENESIS_AZURE_BRAIN"] = "1"
os.environ["GENESIS_SEARCH_RETRIEVE"] = "1"
os.environ.setdefault(
    "GENESIS_KB_PACKAGE_ROOT",
    str(ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes"),
)

OUT = ROOT / "works" / "azure_mejora" / "suite_representativa_20260921"
OUT.mkdir(parents=True, exist_ok=True)
CUSTOMER = "726588"
PORTFOLIO = ROOT / "data" / "lab_portfolios" / "qa_726588_contract_demo.json"

# Objetivos del prompt (IDs sintéticos locales + pregunta)
CASES = [
    {"id": "REP_DEF_DISP", "q": "Qué significa el saldo disponible?", "assert": "glossary_no_fixture"},
    {"id": "REP_PERS_DISP", "q": "Cuánto tengo disponible en mi cuenta de ahorros?", "assert": "personal_available"},
    {"id": "REP_MIX_DEF_SALDO", "q": "Qué significa saldo disponible y cuánto tengo en ahorros?", "assert": "mixed_or_pending"},
    {"id": "REP_VENCIMIENTOS", "q": "Se me vence algo pronto? préstamos o tarjetas en estos días y cuánto", "assert": "upcoming_window"},
    {"id": "REP_MISION", "q": "Cuál es la misión del banco?", "assert": "knowledge_search_or_faq"},
    {"id": "REP_RECLAM", "q": "Cómo hago una reclamación?", "assert": "knowledge_search_or_faq"},
    {"id": "REP_FALLEC", "q": "Qué pasa con los fondos de un cliente fallecido?", "assert": "knowledge_search_or_faq"},
    {"id": "REP_JOVEN", "q": "Qué características tiene la tarjeta joven?", "assert": "knowledge_search_or_faq"},
]


def _sanitize(s: str) -> str:
    return re.sub(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S+", r"\1=***", s)


def _check(case: dict, reply: str, audit: dict, fixture_amounts: list[str]) -> dict:
    kind = case["assert"]
    r = reply or ""
    rl = r.lower()
    out = {"assert": kind, "pass": False, "notes": []}
    if kind == "glossary_no_fixture":
        has_def = "saldo disponible" in rl and any(
            s in rl for s in ("monto", "retirar", "usar", "contable", "disponible es")
        )
        leaked = any(a in r.replace(",", "") for a in fixture_amounts)
        out["pass"] = bool(has_def and not leaked)
        if leaked:
            out["notes"].append("fixture_amount_leaked")
        if not has_def:
            out["notes"].append("missing_definition")
    elif kind == "personal_available":
        out["pass"] = "disponible" in rl and ("rd$" in rl or "dop" in rl or "50" in r)
        if "significa" in rl and "50,000" not in r and "50000" not in r.replace(",", ""):
            out["notes"].append("maybe_definition_only")
    elif kind == "mixed_or_pending":
        has_def = "significa" in rl or "monto que puedes" in rl or "saldo disponible es" in rl
        has_pers = "rd$" in rl or "50" in r
        pending = "pendiente" in rl or "también" in rl
        out["pass"] = (has_def and has_pers) or pending
        out["notes"].append(f"def={has_def},pers={has_pers}")
    elif kind == "upcoming_window":
        out["pass"] = "ventana" in rl or "próximos 30" in rl or "proximos 30" in rl or "america/santo_domingo" in rl
        if "pago mínimo **rd$0.00**" in rl or "pago minimo **rd$0.00**" in rl:
            out["notes"].append("zero_min_payment_shown")
    elif kind == "knowledge_search_or_faq":
        src = ((audit.get("decision_trace") or [{}])[0].get("output") or {})
        evid = src.get("evidence_sources") or []
        out["pass"] = len(r) > 40 and "no encontré" not in rl
        out["notes"].append(f"evidence={evid}, brain={audit.get('brain_source')}")
        if "azure_search" in evid:
            out["notes"].append("SEARCH_REAL_PASS")
        elif out["pass"]:
            out["notes"].append("LOCAL_OR_FAQ_FALLBACK")
    return out


def main() -> int:
    from run_local_turn_real_azure import _build_app
    from fastapi.testclient import TestClient

    app, deployment, endpoint = _build_app()
    envelope = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    # importes del fixture ahorros/tarjeta para aserción negativa
    fixture_amounts = ["50000", "50,000", "28500", "5052", "5,052", "34569", "34,569"]

    results = {
        "run_id": f"rep_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "labels": {
            "context": "CONTEXTO_SINTETICO",
            "session": "MEMORIA_SIMULADA",
            "search": "GENESIS_SEARCH_RETRIEVE=1",
            "deployment": deployment,
        },
        "cases": [],
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        for case in CASES:
            conv = f"rep-{case['id']}-{uuid.uuid4().hex[:6]}"
            client.post(
                "/turn",
                json={
                    "question": None,
                    "customer_id": CUSTOMER,
                    "conversation_id": conv,
                    "context_info": True,
                    "context_op": "load",
                    "context": {"data": envelope},
                },
            )
            t0 = time.perf_counter()
            resp = client.post(
                "/turn",
                json={
                    "question": case["q"],
                    "customer_id": CUSTOMER,
                    "conversation_id": conv,
                },
                timeout=180.0,
            )
            ms = int((time.perf_counter() - t0) * 1000)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            app_ch = body.get("app_channel") or {}
            audit = body.get("audit") or {}
            reply = body.get("reply") or app_ch.get("client_response") or ""
            checks = _check(case, reply, audit, fixture_amounts)
            entry = {
                "case_id": case["id"],
                "question": case["q"],
                "http": resp.status_code,
                "ms": ms,
                "reply_full": reply,
                "brain_source": audit.get("brain_source"),
                "inference_count": audit.get("inference_count"),
                "decision_trace": audit.get("decision_trace"),
                "checks": checks,
            }
            results["cases"].append(entry)
            print(case["id"], "PASS" if checks["pass"] else "FAIL", ms, "ms", checks["notes"][:2])
            print(" ", reply[:120].replace("\n", " | "))

    passed = sum(1 for c in results["cases"] if c["checks"]["pass"])
    results["summary"] = {"pass": passed, "total": len(results["cases"])}
    path = OUT / "resultados_representativos.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # jsonl
    with (OUT / "resultados_representativos.jsonl").open("w", encoding="utf-8") as f:
        for c in results["cases"]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print("summary", results["summary"], "->", path)
    return 0 if passed >= 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
