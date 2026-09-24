#!/usr/bin/env python3
"""Ejecuta casos guía P01–P15 + multi-turno C/R contra QA :8447 (lab 726588).

Evalúa criterios de la guía (no solo status HTTP). Sanitiza montos/ids en salida.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request

BASE = "http://20.127.25.24:8447"
CUSTOMER = "726588"
CASOS = Path(__file__).resolve().parents[1] / "works" / "Casos_Guia_BSC_236.json"
OUT = Path(__file__).resolve().parents[1] / "works" / "RESULTADOS_GUIA_QA_LIVE.json"


def _san(s: str) -> str:
    s = s or ""
    s = re.sub(r"\b\d{4,}\b", "####", s)
    s = re.sub(r"(?i)(RD\$|US\$|\$)\s*[\d,.]+", r"\1[AMT]", s)
    s = re.sub(r"(?i)\b\d[\d,.]*\s*%", "[RATE]%", s)
    return s[:500]


def post(path: str, payload: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            code = resp.status
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:400]}
        code = exc.code
    return {"http": code, "ms": int((time.perf_counter() - t0) * 1000), "body": body}


def reply_of(body: dict[str, Any]) -> str:
    app = body.get("app_channel") or {}
    return str(
        body.get("reply")
        or body.get("message")
        or app.get("client_response")
        or body.get("error")
        or ""
    )


def options_of(body: dict[str, Any]) -> list[Any]:
    app = body.get("app_channel") or {}
    opts = app.get("options") or body.get("options") or []
    return opts if isinstance(opts, list) else []


def load_session() -> tuple[str, dict[str, Any]]:
    cid = str(uuid.uuid4())
    r = post(
        "/orch/context",
        {
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
            "portfolio": "qa_726588_contract_demo.json",
        },
    )
    body = r["body"]
    return str(body.get("conversation_id") or cid), body


def turn(conv: str, question: str, selected: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question,
        "customer_id": CUSTOMER,
        "conversation_id": conv,
        "context_info": False,
        "channel": {"type": "web", "entrypoint": "guia_qa_live"},
    }
    if selected:
        payload["selected_option_ref"] = selected
    return post("/turn", payload)


def eval_p_compound(text: str, question: str) -> tuple[str, str]:
    """Heurística: Cumple / Parcial / No cumple según cobertura de subtemas."""
    t = text.lower()
    q = question.lower()
    checks: list[tuple[str, bool]] = []
    if "debo" in q or "saldo" in q or "adeud" in q or "falta" in q or "pendiente" in q or "tengo en" in q:
        checks.append(("deuda/saldo", any(k in t for k in (
            "debo", "adeud", "saldo", "pendiente", "deuda", "capital", "total adeud", "tengo", "disponible", "no tienes",
        ))))
    if "disponible" in q or "límite" in q or "limite" in q:
        checks.append(("disponible", any(k in t for k in ("disponible", "límite", "limite", "no tienes"))))
    if "fecha" in q or "cuándo" in q or "cuando" in q or "vence" in q or "pagarla" in q:
        checks.append(("fecha", any(k in t for k in ("fecha", "día", "dia", "vence", "vencimiento", "pago", "cuota"))))
    if "tasa" in q:
        checks.append(("tasa", "tasa" in t or "%" in text))
    if "cuota" in q:
        checks.append(("cuota", "cuota" in t))
    if "movimiento" in q:
        checks.append(("movimientos", any(k in t for k in (
            "movimiento", "no dispongo", "no tengo", "no está disponible", "no estan disponibles",
            "no están disponibles", "capacidades actuales",
        ))))
    if "cancel" in q:
        checks.append(("cancelacion", any(k in t for k in ("cancel", "total adeud", "adeudado"))))
    # Multi-producto: exigir señales de ambas categorías
    if ("ahorros" in q or "ahorro" in q) and "tarjeta" in q:
        checks.append(("ahorros", any(k in t for k in ("ahorro", "ahorros"))))
        checks.append(("tarjeta", any(k in t for k in ("tarjeta", "visa", "multicredit", "crédito", "credito"))))
    if "corriente" in q and ("tarjeta" in q or "préstamo" in q or "prestamo" in q):
        checks.append(("corriente", any(k in t for k in ("corriente", "no tienes"))))
    if ("préstamo" in q or "prestamo" in q) and "tarjeta" in q and ("cuentas" in q or "cuenta" in q):
        checks.append(("prestamo", any(k in t for k in ("préstamo", "prestamo", "cuota", "capital"))))
    if "tarjetas" in q and any(s in q for s in ("más", "mas", "cuál", "cual")):
        checks.append(("comparacion", any(k in t for k in ("más", "mas", "mayor", "tiene más", "tiene mas"))))
    if not checks:
        if len(text) > 40 and "error" not in t and "provider" not in t:
            return "Cumple", "respuesta no vacía"
        return "No cumple", "sin criterios"
    ok = sum(1 for _, v in checks if v)
    detail = ", ".join(f"{n}:{'Y' if v else 'N'}" for n, v in checks)
    if ok == len(checks):
        return "Cumple", detail
    if ok > 0:
        return "Cumple parcialmente", detail
    # clarificación de producto cuenta como parcial útil
    if "quieres consultar" in t or "cuál" in t or options_hint(text):
        return "Cumple parcialmente", "desambiguación pendiente; " + detail
    return "No cumple", detail


def options_hint(text: str) -> bool:
    return "****" in text or "opción" in text.lower() or "opcion" in text.lower()


def main() -> int:
    summary = {
        "base": BASE,
        "customer_id": CUSTOMER,
        "cases": [],
    }
    casos = json.loads(CASOS.read_text(encoding="utf-8"))["cases"]
    targets = [c for c in casos if c["case_id"].startswith("P") and c["case_id"][1:].isdigit() and int(c["case_id"][1:]) <= 15]

    for c in targets:
        # Sesión fresca por caso compuesto (evita foco/pending de P previo)
        conv, ctx = load_session()
        if not summary.get("context_source"):
            summary["conversation_id"] = conv
            summary["context_source"] = ctx.get("context_source")
            summary["products_count"] = ctx.get("products_count")
        cid = c["case_id"]
        q = c["question"]
        r = turn(conv, q)
        body = r["body"]
        text = reply_of(body)
        opts = options_of(body)
        label, detail = eval_p_compound(text, q)
        # Si pide selección y hay options, seleccionar la primera y re-evaluar
        follow = None
        if opts and ("quieres consultar" in text.lower() or "cuál" in text.lower() or "sobre cuál" in text.lower() or label != "Cumple"):
            ref = None
            first = opts[0]
            if isinstance(first, dict):
                ref = first.get("ref") or first.get("id") or first.get("option_ref")
                # rich content shape
                if not ref and first.get("product_id"):
                    ref = str(first.get("product_id"))
            # Preferir multicredito en P01 (escenario imágenes)
            if cid == "P01":
                for o in opts:
                    if isinstance(o, dict):
                        lab = str(o.get("label") or o.get("title") or o.get("text") or "").lower()
                        if "multicredit" in lab:
                            ref = o.get("ref") or o.get("id") or o.get("option_ref") or o.get("product_id") or ref
                            break
            if ref:
                r2 = turn(conv, q, selected=str(ref))
                text2 = reply_of(r2["body"])
                # Conservar evidencia del primer turno (p. ej. P07 ahorros + aclaración TC)
                combined = (text + "\n" + text2).strip()
                label2, detail2 = eval_p_compound(combined, q)
                follow = {
                    "selected": str(ref)[:40],
                    "label": label2,
                    "detail": detail2,
                    "reply": _san(text2),
                    "ms": r2["ms"],
                }
                label, detail = label2, detail2
                text = combined

        # Escenario imagen P01: tras clarificación, "dame el multicredito" no debe ir a FAQ
        p01_extra = None
        if cid == "P01":
            r3 = turn(conv, "dame el multicredito")
            t3 = reply_of(r3["body"])
            t3l = t3.lower()
            faq_trap = ("qué es" in t3l or "que es" in t3l) and ("condiciones" in t3l or "cargos" in t3l)
            personal_ok = any(k in t3l for k in ("adeud", "disponible", "límite", "limite", "fecha", "pago", "tarjeta"))
            if faq_trap and not personal_ok:
                p01_extra = {"label": "No cumple", "reason": "FAQ vs producto personal (img_0003/0004)", "reply": _san(t3)}
                if label == "Cumple":
                    label = "Cumple parcialmente"
            elif personal_ok:
                p01_extra = {"label": "Cumple", "reason": "resolvió tarjeta multicredito pendiente", "reply": _san(t3)}
            else:
                p01_extra = {"label": "Cumple parcialmente", "reason": "respuesta ambigua", "reply": _san(t3)}

        row = {
            "case_id": cid,
            "historical_label": c.get("historical_label"),
            "validates": c.get("validates"),
            "new_label": label,
            "detail": detail,
            "reply": _san(text),
            "http": r["http"],
            "ms": r["ms"],
            "options_count": len(opts),
            "follow_select": follow,
            "p01_multicredito": p01_extra,
            "conversation_id": conv,
        }
        summary["cases"].append(row)
        print(f"{cid}\t{label}\t{_san(detail)}")

    # Conteos
    counts = {"Cumple": 0, "Cumple parcialmente": 0, "No cumple": 0}
    for row in summary["cases"]:
        counts[row["new_label"]] = counts.get(row["new_label"], 0) + 1
    summary["counts"] = counts
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))
    print("wrote", OUT)
    return 0 if counts.get("No cumple", 0) == 0 and counts.get("Cumple parcialmente", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
