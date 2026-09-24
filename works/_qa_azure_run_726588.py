#!/usr/bin/env python3
"""QA Azure real 726588 — captura audit/intent/rag; sanitiza salida."""
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
OUT = Path(__file__).resolve().parent / "_qa_azure_run_726588_raw.json"


def sanitize(text: object) -> str:
    s = "" if text is None else str(text)
    s = re.sub(r'(?i)((?:api[_-]?key|token|password|secret|authorization)"\s*:\s*")[^"]*', r"\1***", s)
    s = re.sub(r'(?i)((?:display_)?name"\s*:\s*")[^"]*', r"\1***", s)
    s = re.sub(r"\b\d{4,}\b", "####", s)
    s = re.sub(r"(?i)(RD\$|US\$|\$)\s*[\d,.]+", r"\1[AMT]", s)
    s = re.sub(r"(?i)\b\d[\d,.]*\s*%", "[RATE]%", s)
    s = re.sub(r"(?i)\b\d[\d,.]*\s*(DOP|USD)\b", r"[AMT] \1", s)
    return s


def qhash(q: str) -> str:
    return hashlib.sha256(q.encode("utf-8")).hexdigest()[:12]


def post_json(path: str, payload: dict, timeout: float = 120.0):
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
            headers = {k: v for k, v in resp.headers.items()}
            status = resp.status
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        headers = {k: v for k, v in (exc.headers.items() if exc.headers else [])}
        status = exc.code
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": type(exc).__name__, "detail": str(exc)[:200]}, {}, int((time.perf_counter() - t0) * 1000)
    elapsed = int((time.perf_counter() - t0) * 1000)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": sanitize(body[:2000])}
    return status, data, headers, elapsed


def classify_route(audit: dict | None, intent: str | None, rag: object, client_ms: int) -> dict:
    audit = audit or {}
    step_count = audit.get("step_count")
    slowest = audit.get("slowest_step")
    total_ms = audit.get("total_ms")
    rag_s = str(rag or audit.get("rag_status") or "")
    route = "unknown"
    azure_evidence = False
    faq_evidence = False
    fastpath_evidence = False
    if rag_s.upper() == "FAQ" or (intent or "") == "BUSINESS_KNOWLEDGE_QUERY" and rag_s.upper() == "FAQ":
        route = "faq"
        faq_evidence = True
    if slowest in {"proposer", "verifier", "final_response", "capa0_domain", "capa1_product"} or (
        isinstance(step_count, int) and step_count >= 5
    ):
        route = "modelo_azure_probable"
        azure_evidence = True
    if (
        isinstance(step_count, int)
        and step_count <= 2
        and slowest in (None, "context", "t2_shortcut", "field_fastpath", "faq")
        and rag_s.upper() in {"NOT_REQUIRED", "FAQ", "NONE", ""}
        and (total_ms is not None and total_ms < 500 or client_ms < 800)
    ):
        if faq_evidence:
            route = "faq"
        else:
            route = "fastpath_heuristico"
            fastpath_evidence = True
            azure_evidence = False
    return {
        "route": route,
        "azure_evidence": azure_evidence,
        "faq_evidence": faq_evidence,
        "fastpath_evidence": fastpath_evidence,
        "audit": {
            "total_ms": total_ms,
            "slowest_step": slowest,
            "slowest_step_ms": audit.get("slowest_step_ms"),
            "step_count": step_count,
            "rag_status": audit.get("rag_status"),
        },
    }


def turn(conv: str, question: str | None = None, selected_option_ref: str | None = None) -> dict:
    payload: dict = {"conversation_id": conv, "customer_id": CUSTOMER}
    if question is not None:
        payload["question"] = question
    if selected_option_ref is not None:
        payload["selected_option_ref"] = selected_option_ref
    status, data, headers, client_ms = post_json("/turn", payload)
    app = data.get("app_channel") if isinstance(data, dict) else {}
    app = app or {}
    audit = data.get("audit") if isinstance(data, dict) else None
    options = []
    for o in app.get("options") or []:
        if isinstance(o, dict):
            options.append(
                {
                    "label": sanitize(o.get("label") or o.get("title") or ""),
                    "ref_hash": qhash(str(o.get("ref") or "")),
                    "ref": str(o.get("ref") or ""),  # kept briefly for follow-up selection; stripped in report write
                    "intent": o.get("intent"),
                }
            )
    route_info = classify_route(audit if isinstance(audit, dict) else None, app.get("intent_id"), data.get("rag_status"), client_ms)
    return {
        "q": question,
        "selected_option_ref_hash": qhash(selected_option_ref) if selected_option_ref else None,
        "q_hash": qhash(question or selected_option_ref or ""),
        "http": status,
        "hdr_ms": headers.get("X-Request-Duration-Ms") or headers.get("x-request-duration-ms"),
        "client_ms": client_ms,
        "status": app.get("status") or (data.get("status") if isinstance(data, dict) else None),
        "intent": app.get("intent_id"),
        "turn_number": app.get("turn_number"),
        "account_ref_masked": sanitize(app.get("account_ref")),
        "rag_status": data.get("rag_status") if isinstance(data, dict) else None,
        "reply": sanitize(app.get("client_response") or data.get("reply") or ""),
        "options_masked": [{"label": o["label"], "ref_hash": o["ref_hash"], "intent": o["intent"]} for o in options],
        "_options_raw_refs": [o["ref"] for o in options],
        "clarifications": [sanitize(c) for c in (app.get("clarifications") or [])],
        **route_info,
        "raw_keys": sorted(data.keys()) if isinstance(data, dict) else [],
    }


def main() -> None:
    # probes
    with request.urlopen(BASE + "/health", timeout=15) as resp:
        health = json.loads(resp.read().decode())
    try:
        with request.urlopen(BASE + "/orch/health", timeout=25) as resp:
            orch_health = {"http": resp.status, "body": sanitize(resp.read().decode()[:300])}
    except error.HTTPError as exc:
        orch_health = {"http": exc.code, "body": sanitize(exc.read().decode()[:300])}
    except Exception as exc:  # noqa: BLE001
        orch_health = {"http": 0, "error": str(exc)[:200]}

    html = request.urlopen(BASE + "/pruebas/", timeout=20).read().decode("utf-8", "replace")
    js = request.urlopen(BASE + "/pruebas/app.js?v=14", timeout=20).read().decode("utf-8", "replace")
    iface = {
        "pruebas_http": 200,
        "js_uses_orch_context": "/orch/context" in js,
        "js_uses_orch_chat_front": "/orch/chat/front" in js,
        "js_comments_turn": "/turn" in js,
        "html_title_ok": "pruebas" in html.lower() or "banca" in html.lower(),
    }

    st, orch_chat, _, _ = post_json(
        "/orch/chat/front",
        {"customer_id": CUSTOMER, "conversation_id": str(uuid.uuid4()), "message": "hola", "channel": "web"},
        timeout=35,
    )
    orch_chat_probe = {
        "http": st,
        "status": (orch_chat.get("app_channel") or {}).get("status") if isinstance(orch_chat, dict) else None,
        "body_head": sanitize(json.dumps(orch_chat, ensure_ascii=False)[:350])
        if isinstance(orch_chat, dict)
        else sanitize(str(orch_chat)[:350]),
    }

    conv = str(uuid.uuid4())
    st, ctx, _, _ = post_json(
        "/orch/context",
        {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True},
    )
    ctx_meta = {
        "http": st,
        "status": ctx.get("status") if isinstance(ctx, dict) else None,
        "source": ctx.get("context_source") if isinstance(ctx, dict) else None,
        "products_count": ctx.get("products_count") if isinstance(ctx, dict) else None,
        "active_count": ctx.get("active_count") if isinstance(ctx, dict) else None,
        "context_stamp": ctx.get("context_stamp") if isinstance(ctx, dict) else None,
        "conversation_id_anon": "conv-" + conv[:8],
        "has_core_error": bool(isinstance(ctx, dict) and ctx.get("core_error")),
        "core_error_keys": sorted((ctx.get("core_error") or {}).keys())
        if isinstance(ctx, dict) and isinstance(ctx.get("core_error"), dict)
        else [],
    }

    scenarios: list[dict] = []
    last_refs: list[str] = []

    def run(tid: str, expected: str, question: str | None = None, selected_option_ref: str | None = None) -> dict:
        nonlocal last_refs
        r = turn(conv, question=question, selected_option_ref=selected_option_ref)
        last_refs = r.pop("_options_raw_refs", [])
        row = {"id": tid, "expected": expected, **r}
        scenarios.append(row)
        print(
            f"{tid} status={row['status']} route={row['route']} intent={row['intent']} "
            f"rag={row['rag_status']} ms={row['client_ms']} azure={row['azure_evidence']}"
        )
        print(f"  reply={row['reply'][:160]!r}")
        return row

    # A
    a1 = run("A1", "Lista productos activos", question="¿Qué productos tengo?")
    run("A2", "Disponible de cuenta; no préstamos salvo ambigüedad real de cuentas", question="¿Cuánto tengo disponible?")
    run("A3", "Saldo actual/current distinto de disponible", question="¿Y cuál es el saldo actual?")

    reply_l = a1["reply"].lower()
    inventory = {
        "has_usd_account": any(x in reply_l for x in ("dólar", "dolar", "usd", "us$")),
        "has_dop_account": any(x in reply_l for x in ("peso", "dop", "rd$")),
        "has_multi_loan": (reply_l.count("préstamo") + reply_l.count("prestamo")) >= 2,
        "has_account": any(x in reply_l for x in ("cuenta", "ahorros")),
        "has_loan": any(x in reply_l for x in ("préstamo", "prestamo")),
        "has_card": "tarjeta" in reply_l,
    }

    # B — loans ambiguity
    if inventory["has_multi_loan"]:
        b1 = run("B1", "Aclaración entre préstamos", question="¿Cuánto debo de mi préstamo?")
        if last_refs:
            run("B2", "Selección estructurada del primer candidato", selected_option_ref=last_refs[0])
        else:
            run("B2", "Respuesta ordinal/textual a aclaración", question="el primero")
        run("B3", "¿y esa cuenta? no debe tratar préstamo como cuenta", question="¿y esa cuenta?")
    else:
        scenarios.append({"id": "B1-B3", "verdict_hint": "NO APLICA", "reply": "Sin multi-préstamo"})

    if inventory["has_usd_account"] and inventory["has_dop_account"]:
        run("B4", "Aclaración multi-moneda", question="¿Cuánto tengo disponible?")
        run("B5", "la de dólares", question="la de dólares")
        run("B6", "continúa foco USD", question="¿y esa cuenta?")
    else:
        scenarios.append(
            {
                "id": "B4-B6",
                "verdict": "NO APLICA",
                "expected": "Continuidad multi-moneda DOP/USD",
                "reply": "Sin cuenta USD activa en portafolio lab 726588",
                "inventory": inventory,
            }
        )

    # C
    if inventory["has_multi_loan"]:
        run("C1", "Cambio a otro préstamo", question="Ahora el otro préstamo")
        run("C2", "Corrección a cuenta de ahorros", question="No, me refería a la cuenta de ahorros")
    else:
        scenarios.append({"id": "C1-C2", "verdict": "NO APLICA", "reply": "Sin pares"})

    # D
    run("D1", "Saldo cuenta", question="¿Cuál es el saldo de mi cuenta?")
    run("D2", "Definición saldo disponible (FAQ/Foundry/modelo)", question="¿qué significa saldo disponible?")
    run("D3", "Retoma foco cuenta", question="¿y cuánto tengo en esa cuenta?")

    # E
    run("E1", "Tasa personal con aclaración o contexto", question="¿Cuál es mi tasa?")
    run("E2", "Definición tasa = conocimiento", question="¿Qué significa tasa?")
    run("E3", "Mixta tasa préstamo + significado", question="¿Cuál es la tasa de mi préstamo y qué significa?")
    if last_refs:
        run("E3b", "Tras aclaración E3, seleccionar préstamo", selected_option_ref=last_refs[0])

    # F
    run("F1", "Typo/reformulación disponible", question="dime el dispoonible de mi cuenta plis")
    run("F2", "Corto dependiente: y el actual?", question="y el actual?")
    run("F3", "Natural sin tilde", question="cuanto debo del prestamo")

    # G
    if not inventory["has_card"]:
        run("G1", "Ausencia tarjeta: no inventar", question="¿Cuál es la fecha de corte de mi tarjeta?")
    else:
        run("G1", "Campo posiblemente ausente", question="¿Cuál es el límite de sobregiro de mi cuenta?")

    # strip any residual refs
    for s in scenarios:
        s.pop("_options_raw_refs", None)

    report = {
        "env": health,
        "iface": iface,
        "orch_health": orch_health,
        "orch_chat_front_probe": orch_chat_probe,
        "context": ctx_meta,
        "inventory": inventory,
        "api_path_used": "POST /turn (API autorizada). UI /pruebas usa /orch/chat/front → orch → /turn.",
        "local_vs_qa_note": "QA health version=0.8.0 env=dev; respuesta /turn sin decision_trace (shape canal). Cambios locales 1C (CAS/gate/rate) no verificables como desplegados solo por este shape.",
        "scenarios": scenarios,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
