# -*- coding: utf-8 -*-
"""Reconciliación probe ×2 con body completo + trazas (sin truncar reply a 500)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

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
os.environ.setdefault(
    "GENESIS_KB_PACKAGE_ROOT",
    str(ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes"),
)
# Preferir Search real en conocimiento cuando esté cableado
os.environ.setdefault("GENESIS_SEARCH_RETRIEVE", "1")

OUT = ROOT / "works" / "azure_mejora" / "probe_reconcile_20260921"
OUT.mkdir(parents=True, exist_ok=True)
BASELINE = ROOT / "works" / "azure_mejora" / "probe_turn_real" / "turn_real_result.json"
CUSTOMER = "726588"
PORTFOLIO = ROOT / "data" / "lab_portfolios" / "qa_726588_contract_demo.json"

QUESTIONS = [
    "Oye, se me vence algo pronto? Dime si tengo que pagar algún préstamo o tarjeta en estos días y cuánto.",
    "Qué significa el saldo disponible en una cuenta de ahorros?",
]


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    if not isinstance(obj, str):
        return obj
    s = re.sub(
        r'(?i)((?:api[_-]?key|token|password|secret|authorization)"\s*:\s*")[^"]*',
        r"\1***",
        obj,
    )
    return s


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    # Conservar baseline intacto
    if BASELINE.is_file():
        (OUT / "baseline_turn_real_result.json").write_text(
            BASELINE.read_text(encoding="utf-8"), encoding="utf-8"
        )

    sys.path.insert(0, str(ROOT / "works" / "azure_mejora" / "scripts"))
    from run_local_turn_real_azure import _build_app

    from fastapi.testclient import TestClient

    app, deployment, endpoint = _build_app()
    envelope = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    conv = f"reconcile-{uuid.uuid4().hex[:10]}"

    # Instrumentar resolve_full para capturar proposal/status
    capture: dict = {"resolve_calls": []}
    from genesis_cognitive.agents import agent_framework_turn_resolver as afr

    # El resolver vive en create_app; instrumentamos execute path via azure_plan
    import genesis_cognitive.brain.azure_plan_turn as apt

    _orig_run = apt.run_azure_plan_path

    async def _wrap_run(**kwargs):
        out = await _orig_run(**kwargs)
        # snapshot de interés
        capture["last_v4"] = {
            "status": out.get("status"),
            "intent_id": out.get("intent_id"),
            "brain_trace": (out.get("decision_trace") or [{}])[0],
            "client_response_len": len(out.get("client_response") or ""),
            "client_response_full": out.get("client_response"),
            "inference_count": out.get("inference_count"),
            "rag_status": out.get("rag_status"),
            "evidence_sources": out.get("evidence_sources"),
            "initial_proposal": None,
            "verified_status": None,
        }
        pex = out.get("_pex")
        plan = out.get("_plan")
        if plan is not None:
            capture["last_v4"]["executed_plan"] = {
                "source": getattr(plan, "source", None),
                "transition": getattr(plan, "transition", None),
                "tasks": [
                    {
                        "id": t.id,
                        "domain": t.domain,
                        "action": t.action,
                        "object": t.object,
                        "fields": list(t.fields or []),
                        "status": t.status,
                        "entity_ref": t.entity_ref,
                    }
                    for t in (plan.tasks or [])
                ],
            }
        if pex is not None:
            capture["last_v4"]["pex"] = {
                "status": pex.status,
                "route": pex.route,
                "text_len": len(pex.text or ""),
                "evidences": [
                    {
                        "task_id": e.task_id,
                        "domain": e.domain,
                        "status": e.status,
                        "source": e.source,
                        "field": e.field_name,
                        "text_preview": (e.text or "")[:240],
                    }
                    for e in (pex.evidences or [])
                ],
            }
        return out

    apt.run_azure_plan_path = _wrap_run  # type: ignore

    report = {
        "run_id": f"reconcile_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "build": {
            "git": "NO_GIT",
            "cognitive_py_sha256_prefix": None,
            "code_version": "potenciacion-strict-v2.2",
            "knowledge_version": "bsc-kb-2026-09-19-candidate-1",
            "deployment": deployment,
            "endpoint_host": endpoint.split("//")[-1],
            "GENESIS_SEMANTIC_MODE": os.environ.get("GENESIS_SEMANTIC_MODE"),
            "GENESIS_SESSION_BACKEND": "memory",
            "GENESIS_SEARCH_RETRIEVE": os.environ.get("GENESIS_SEARCH_RETRIEVE"),
            "context": "lab_synthetic",
            "customer_id": CUSTOMER,
            "portfolio": PORTFOLIO.name,
            "labels": {
                "interpretation": "MODELO_REAL_when_inference",
                "session": "MEMORIA_SIMULADA",
                "context": "CONTEXTO_SINTETICO",
                "redis": "PENDIENTE",
            },
        },
        "baseline_note": "baseline_turn_real_result.json conservado; reply[:500] era recorte del runner extract, no del servicio",
        "turns": [],
    }

    # hash código
    h = hashlib.sha256()
    files = sorted((ROOT / "src" / "genesis_cognitive").rglob("*.py"))
    for p in files:
        h.update(p.read_bytes())
    report["build"]["cognitive_py_sha256_prefix"] = h.hexdigest()[:16]
    report["build"]["cognitive_py_file_count"] = len(files)

    with TestClient(app, raise_server_exceptions=True) as client:
        r0 = client.post(
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
        report["context_load"] = {"http": r0.status_code, "status": r0.json().get("status")}

        for i, q in enumerate(QUESTIONS):
            capture.clear()
            capture["resolve_calls"] = []
            t0 = time.perf_counter()
            resp = client.post(
                "/turn",
                json={
                    "question": q,
                    "customer_id": CUSTOMER,
                    "conversation_id": conv,
                    "context_info": False,
                },
                timeout=180.0,
            )
            ms = int((time.perf_counter() - t0) * 1000)
            body = resp.json()
            app_ch = body.get("app_channel") or {}
            audit = body.get("audit") or {}
            reply_full = (
                body.get("reply")
                or app_ch.get("client_response")
                or body.get("client_response")
                or ""
            )
            entry = {
                "turn_index": i + 1,
                "question": q,
                "http": resp.status_code,
                "client_ms": ms,
                "reply_full": reply_full,
                "reply_len": len(reply_full),
                "reply_view_500": reply_full[:500],
                "reply_truncated_by": "report_view_only" if len(reply_full) > 500 else "none",
                "status": app_ch.get("status") or body.get("status"),
                "intent_id": app_ch.get("intent_id") or body.get("intent_id"),
                "audit": {
                    "brain_source": audit.get("brain_source"),
                    "inference_count": audit.get("inference_count"),
                    "rag_status": audit.get("rag_status"),
                    "semantic_mode": audit.get("semantic_mode"),
                    "decision_trace": audit.get("decision_trace"),
                    "total_ms": audit.get("total_ms"),
                },
                "instrumentation": deepcopy(capture.get("last_v4")),
                "labels": {
                    "context": "CONTEXTO_SINTETICO",
                    "session": "MEMORIA_SIMULADA",
                    "model_invoked": bool(audit.get("inference_count")),
                    "search_used": None,
                },
            }
            # marcar search en evidencias
            srcs = (capture.get("last_v4") or {}).get("pex", {}).get("evidences") or []
            entry["labels"]["search_used"] = any(
                (e.get("source") or "").startswith("azure_search") for e in srcs
            )
            report["turns"].append(entry)
            print(
                f"T{i+1} http={resp.status_code} ms={ms} len={len(reply_full)} "
                f"brain={audit.get('brain_source')} inf={audit.get('inference_count')}"
            )
            print("  reply_head:", reply_full[:160].replace("\n", " | "))

    out_path = OUT / "probe_reconcile_full.json"
    out_path.write_text(
        json.dumps(_sanitize(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # vistas abreviadas rotuladas
    brief = {
        "run_id": report["run_id"],
        "turns": [
            {
                "question": t["question"][:80],
                "reply_view_500": t["reply_view_500"],
                "reply_len": t["reply_len"],
                "truncated_note": t["reply_truncated_by"],
                "brain_source": t["audit"]["brain_source"],
                "inference_count": t["audit"]["inference_count"],
                "route": ((t["audit"].get("decision_trace") or [{}])[0].get("output") or {}).get(
                    "route_source"
                ),
                "plan": (t.get("instrumentation") or {}).get("executed_plan"),
            }
            for t in report["turns"]
        ],
    }
    (OUT / "probe_reconcile_brief.json").write_text(
        json.dumps(_sanitize(brief), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
