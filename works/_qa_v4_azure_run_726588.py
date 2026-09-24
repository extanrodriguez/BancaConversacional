#!/usr/bin/env python3
"""Recorridos V4 Azure QA — cliente 726588 (solo lectura). Salida saneada."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib import error, request

BASE = "http://20.127.25.24:8447"
CUSTOMER = "726588"
OUT = Path(__file__).resolve().parent / "_qa_cierre_v4_726588_raw.json"


def sanitize(text: object) -> str:
    s = "" if text is None else str(text)
    s = re.sub(r'(?i)((?:api[_-]?key|token|password|secret|authorization)"\s*:\s*")[^"]*', r"\1***", s)
    s = re.sub(r'(?i)((?:display_)?name"\s*:\s*")[^"]*', r"\1***", s)
    s = re.sub(r"\b\d{4,}\b", "####", s)
    s = re.sub(r"(?i)(RD\$|US\$|\$)\s*[\d,.]+", r"\1[AMT]", s)
    s = re.sub(r"(?i)\b\d[\d,.]*\s*%", "[RATE]%", s)
    s = re.sub(r"(?i)\b\d[\d,.]*\s*(DOP|USD)\b", r"[AMT] \1", s)
    return s


def post_json(path: str, payload: dict, timeout: float = 180.0):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        BASE + path,
        data=raw,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            headers = {k: v for k, v in resp.headers.items()}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
        headers = {k: v for k, v in (exc.headers.items() if exc.headers else [])}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": type(exc).__name__, "detail": str(exc)[:240]}, {}, int((time.perf_counter() - t0) * 1000)
    elapsed = int((time.perf_counter() - t0) * 1000)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": sanitize(body[:2000])}
    return status, data, headers, elapsed


def extract_turn(status: int, data: dict, client_ms: int, question: str | None) -> dict:
    app = (data.get("app_channel") if isinstance(data, dict) else None) or {}
    audit = (data.get("audit") if isinstance(data, dict) else None) or {}
    options = []
    for o in app.get("options") or data.get("app_channel_options") or data.get("options") or []:
        if isinstance(o, dict):
            options.append({
                "label": sanitize(o.get("label") or o.get("title") or ""),
                "ref": str(o.get("ref") or ""),
                "intent": o.get("intent"),
            })
    trace = audit.get("decision_trace") or data.get("decision_trace") or []
    t0 = trace[0] if isinstance(trace, list) and trace and isinstance(trace[0], dict) else {}
    tout = t0.get("output") if isinstance(t0.get("output"), dict) else {}
    inf = audit.get("inference_count")
    if inf is None:
        inf = data.get("inference_count")
    return {
        "q": question,
        "http": status,
        "client_ms": client_ms,
        "status": app.get("status") or data.get("status"),
        "intent": app.get("intent_id") or data.get("intent_id"),
        "reply": sanitize(
            app.get("client_response") or data.get("client_response") or data.get("reply") or ""
        ),
        "options": [
            {"label": o["label"], "intent": o["intent"],
             "ref_hash": hashlib.sha256(o["ref"].encode()).hexdigest()[:10]}
            for o in options
        ],
        "_refs": [o["ref"] for o in options],
        "audit": {
            "semantic_mode": audit.get("semantic_mode") or tout.get("semantic_mode"),
            "inference_count": inf,
            "decision_trace": sanitize(str(trace))[:500],
            "total_ms": audit.get("total_ms") or data.get("total_request_ms"),
            "slowest_step": audit.get("slowest_step"),
            "step_count": audit.get("step_count") or (len(trace) if isinstance(trace, list) else None),
            "rag_status": audit.get("rag_status") or data.get("rag_status"),
            "stage_timings_ms": tout.get("stage_timings_ms") or data.get("stage_timings_ms"),
            "failed_model_attempts": tout.get("failed_model_attempts"),
            "route_source": tout.get("route_source"),
            "task_statuses": tout.get("task_statuses"),
            "task_count": tout.get("task_count"),
        },
        "model_called": bool((inf or 0) >= 1),
        "error": sanitize(str(data.get("error") or data.get("detail") or ""))[:200],
    }


def turn(conv: str, question: str | None = None, selected_option_ref: str | None = None) -> dict:
    payload: dict = {"conversation_id": conv, "customer_id": CUSTOMER}
    if question is not None:
        payload["question"] = question
    if selected_option_ref is not None:
        payload["selected_option_ref"] = selected_option_ref
    status, data, _, client_ms = post_json("/turn", payload)
    return extract_turn(status, data if isinstance(data, dict) else {}, client_ms, question)


def strip_refs(row: dict) -> dict:
    out = dict(row)
    out.pop("_refs", None)
    return out


def main() -> None:
    report: dict = {"customer": CUSTOMER, "base": BASE, "journeys": {}, "skipped": [], "probes": {}}

    # probes
    try:
        with request.urlopen(BASE + "/health", timeout=15) as resp:
            report["probes"]["health"] = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        report["probes"]["health"] = {"error": str(exc)[:120]}
    try:
        with request.urlopen(BASE + "/ready/redis", timeout=15) as resp:
            report["probes"]["ready_redis"] = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        report["probes"]["ready_redis"] = {"error": str(exc)[:120]}

    # context load (authorized lab path)
    conv_base = str(uuid.uuid4())
    st, ctx, _, ms = post_json(
        "/orch/context",
        {"customer_id": CUSTOMER, "conversation_id": conv_base, "allow_lab_fallback": True},
    )
    report["probes"]["context"] = {
        "http": st,
        "client_ms": ms,
        "status": ctx.get("status") if isinstance(ctx, dict) else None,
        "source": ctx.get("context_source") if isinstance(ctx, dict) else None,
        "products_count": ctx.get("products_count") if isinstance(ctx, dict) else None,
        "active_count": ctx.get("active_count") if isinstance(ctx, dict) else None,
        "has_core_error": bool(isinstance(ctx, dict) and ctx.get("core_error")),
    }

    # --- Journey A: disponible → USD (puede NO APLICA si no hay USD en 726588) ---
    conv = str(uuid.uuid4())
    post_json("/orch/context", {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True})
    a1 = turn(conv, "¿Con cuánto puedo contar?")
    a2 = turn(conv, "la de dólares")
    report["journeys"]["A_disponible_usd"] = {
        "note": "USD puede no aplicar en portafolio 726588",
        "steps": [strip_refs(a1), strip_refs(a2)],
        "model_calls": sum(1 for s in (a1, a2) if s.get("model_called")),
    }

    # --- Journey B: saldo contable ---
    conv = str(uuid.uuid4())
    post_json("/orch/context", {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True})
    b1 = turn(conv, "¿Cuál es el saldo de mi cuenta?")
    b2 = turn(conv, "¿Y el saldo contable?")
    report["journeys"]["B_saldo_contable"] = {
        "steps": [strip_refs(b1), strip_refs(b2)],
        "model_calls": sum(1 for s in (b1, b2) if s.get("model_called")),
    }

    # --- Journey C: visión → retomar cuenta ---
    conv = str(uuid.uuid4())
    post_json("/orch/context", {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True})
    c0 = turn(conv, "¿Cuál es el saldo disponible de mi cuenta?")
    c1 = turn(conv, "Dime la visión del banco")
    c2 = turn(conv, "volvamos a esa cuenta")
    report["journeys"]["C_vision_retomar"] = {
        "steps": [strip_refs(c0), strip_refs(c1), strip_refs(c2)],
        "model_calls": sum(1 for s in (c0, c1, c2) if s.get("model_called")),
    }

    # --- Journey D: tasa + definición (+ selección si hace falta) ---
    conv = str(uuid.uuid4())
    post_json("/orch/context", {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True})
    d1 = turn(conv, "La tasa de mi préstamo y qué significa")
    d2 = None
    if d1.get("_refs"):
        d2 = turn(conv, selected_option_ref=d1["_refs"][0])
    elif d1.get("status") in {"NEED_CLARIFICATION", "need_clarification"} or d1.get("options"):
        d2 = turn(conv, "el primero")
    report["journeys"]["D_tasa_definicion"] = {
        "steps": [strip_refs(d1)] + ([strip_refs(d2)] if d2 else []),
        "model_calls": sum(1 for s in ([d1] + ([d2] if d2 else [])) if s.get("model_called")),
    }

    # --- Journey E: corrección + misión ---
    conv = str(uuid.uuid4())
    post_json("/orch/context", {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True})
    e1 = turn(conv, "¿Cuál es el saldo de mi cuenta de ahorro?")
    e2 = turn(conv, "No, la corriente; además dime la misión")
    report["journeys"]["E_correccion_mision"] = {
        "steps": [strip_refs(e1), strip_refs(e2)],
        "model_calls": sum(1 for s in (e1, e2) if s.get("model_called")),
    }

    # --- Journey F: dos pendientes distintas ---
    conv = str(uuid.uuid4())
    post_json("/orch/context", {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True})
    f1 = turn(conv, "Quiero la tasa de mi préstamo y también el saldo de mi cuenta")
    f2 = None
    if f1.get("_refs"):
        f2 = turn(conv, selected_option_ref=f1["_refs"][0])
    else:
        f2 = turn(conv, "primero el préstamo")
    report["journeys"]["F_dos_pendientes"] = {
        "steps": [strip_refs(f1), strip_refs(f2)],
        "model_calls": sum(1 for s in (f1, f2) if s.get("model_called")),
    }

    # Explicitly not executed
    report["skipped"] = [
        "Transacciones bancarias (fuera de alcance)",
        "Otros clientes distintos de 726588",
        "Cambio de orquestador externo / Foundry index",
        "USD real si portafolio 726588 no tiene cuenta USD (marcar NO APLICA en interpretación)",
        "Tarjetas / DAP / certificados no presentes en 726588",
        "Renovación sostenida de token Entra (>TTL largo)",
        "PROD",
    ]

    # summary counts
    all_steps = []
    for j in report["journeys"].values():
        all_steps.extend(j.get("steps") or [])
    report["summary"] = {
        "turns": len(all_steps),
        "http_200": sum(1 for s in all_steps if s.get("http") == 200),
        "azure_plan_mode": sum(1 for s in all_steps if (s.get("audit") or {}).get("semantic_mode") == "azure_plan"),
        "model_called_turns": sum(1 for s in all_steps if s.get("model_called")),
        "inference_total": sum(int((s.get("audit") or {}).get("inference_count") or 0) for s in all_steps),
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "summary": report["summary"], "context": report["probes"].get("context"), "ready_redis_ok": (report["probes"].get("ready_redis") or {}).get("ok")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
