#!/usr/bin/env python3
"""Batería remota estilo SDK/orquestador (Guía de Pruebas Conversacionales BSC).

Camino: ClientId → /orch/webhook/session|chat → orquestador → /turn

También diagnostica vía /inspect (rag_status / Foundry) en paralelo.

Uso:
  .venv/Scripts/python.exe scripts/orch_sdk_guide_suite.py
  .venv/Scripts/python.exe scripts/orch_sdk_guide_suite.py --client CUST001 --limit 30
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_DEFAULT = "http://20.127.25.24:8447"


def _norm(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    stop = {
        "de", "del", "la", "el", "los", "las", "un", "una", "y", "o", "en", "a", "al",
        "que", "es", "por", "con", "para", "se", "su", "sus", "mi", "mis", "me", "te",
    }
    return {t for t in _norm(s).split() if len(t) > 2 and t not in stop}


def overlap(expected: str, got: str) -> float:
    e, g = _tokens(expected), _tokens(got)
    if not e or not g:
        return 0.0
    return len(e & g) / max(len(e), 1)


def http_json(
    base: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    timeout: int = 120,
) -> tuple[int, dict[str, Any], float]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=body,
        headers=hdrs,
        method=method,
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw = (exc.read() or b"{}").decode("utf-8", errors="replace")
        code = exc.code
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}, time.time() - t0
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {"raw": raw[:2000]}
    if not isinstance(data, dict):
        data = {"raw": data}
    return code, data, time.time() - t0


def extract_reply(data: dict[str, Any]) -> str:
    app = data.get("app_channel") if isinstance(data.get("app_channel"), dict) else {}
    for key in ("reply", "message", "content", "client_response"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    cr = app.get("client_response")
    return str(cr).strip() if cr else ""


# --- Escenarios de la Guía (contexto KB + mixtos + muestra personal) ---

GUIDE_CTX: list[dict[str, Any]] = [
    {
        "id": "CTX01",
        "kind": "kb_context",
        "turns": [
            "¿Qué es Crédito Diferido?",
            "¿Y qué requisitos tiene?",
            "¿Cómo lo solicito?",
            "¿Tiene cargos?",
            "¿Y cómo lo cancelo?",
        ],
        "must_keep": ["diferido", "multicredit", "cuotas"],
        "expect_any": [
            ["credito diferido", "multicredit", "cuotas bsc", "modalidad"],
            ["requisito", "document", "cedula", "solicitud"],
            ["solicitar", "solicitud", "canal", "centro", "digital", "bsc"],
            ["cargo", "comision", "costo", "tarifa"],
            ["cancel", "bloquear", "solicitud"],
        ],
    },
    {
        "id": "CTX02",
        "kind": "kb_context",
        "turns": [
            "Háblame de Multicrédito",
            "¿Cuál es el consumo mínimo?",
            "¿Puedo sacar efectivo?",
            "¿Tiene algún cargo por eso?",
            "¿Y si pierdo la tarjeta?",
        ],
        "must_keep": ["multicredit"],
        "expect_any": [
            ["multicredit", "credito diferido", "linea"],
            ["consumo minimo", "minimo", "rd"],
            ["efectivo", "avance"],
            ["cargo", "comision", "comisión", "consumo", "minimo", "mínimo", "rd"],
            ["pierd", "robo", "bloque", "report", "seguridad"],
        ],
    },
    {
        "id": "CTX03",
        "kind": "kb_context",
        "turns": [
            "¿Qué es una Visa Platinum?",
            "¿Qué beneficios tiene?",
            "Ahora háblame de la Infinite",
            "¿Y qué la diferencia de la anterior?",
        ],
        "must_keep": ["visa", "platinum", "infinite"],
        "expect_any": [
            ["platinum", "visa"],
            ["beneficio", "ventaja", "puntos", "cashback", "servicio"],
            ["infinite", "visa"],
            ["diferenc", "platinum", "infinite", "beneficio"],
        ],
    },
    {
        "id": "CTX06",
        "kind": "kb_context",
        "turns": [
            "¿Qué es la fecha de corte?",
            "¿Y la fecha límite?",
            "¿Cuál ocurre primero?",
            "¿Qué pasa si pago después?",
        ],
        "must_keep": ["corte", "limite", "pago"],
        "expect_any": [
            ["fecha de corte", "corte", "facturacion", "cierre"],
            ["fecha limite", "limite de pago", "ultimo dia", "pago"],
            ["primero", "corte", "antes", "despues", "limite"],
            ["atraso", "mora", "cargo", "interes", "despues"],
        ],
    },
    {
        "id": "CTX07",
        "kind": "kb_context",
        "turns": [
            "¿Cómo presento una reclamación?",
            "¿Qué información debo entregar?",
            "¿Y cuáles son mis derechos durante ese proceso?",
        ],
        "must_keep": ["reclam"],
        "expect_any": [
            ["reclam", "809", "centro", "bsc"],
            ["document", "factura", "constancia", "soporte", "informacion", "información", "canal", "reclam"],
            ["derecho", "obligacion", "cliente", "reclam"],
        ],
    },
    {
        "id": "CC01",
        "kind": "kb_compare",
        "turns": [
            "Compárame Multicrédito BSC con Cuotas BSC",
            "¿Cuál es la principal diferencia?",
            "¿Y en cuanto a los pagos?",
            "¿Cuál de los dos tiene consumo mínimo?",
            "¿Cómo cancelo el primero?",
            "¿Y el segundo?",
        ],
        "must_keep": ["multicredit", "cuotas"],
        "expect_any": [
            ["multicredit", "cuotas"],
            ["diferenc", "multicredit", "cuotas"],
            ["pago", "cuota", "domicil"],
            ["consumo minimo", "minimo", "multicredit"],
            ["cancel", "multicredit"],
            ["cancel", "cuotas"],
        ],
    },
    {
        "id": "CC05",
        "kind": "kb_compare",
        "turns": [
            "Compárame una tarjeta de crédito y una de débito",
            "¿Cuál usa directamente el dinero de mi cuenta?",
            "¿Y cómo funciona la otra?",
            "¿Qué cargos puede tener esa?",
            "No, me refería a la primera",
        ],
        "must_keep": ["credito", "debito"],
        "expect_any": [
            ["credito", "debito"],
            ["debito", "cuenta", "fondos", "disponible"],
            ["credito", "limite", "prestamo", "linea"],
            ["cargo", "comision"],
            ["debito", "cuenta", "cargo", "comision"],
        ],
    },
]

GUIDE_KB_SINGLE: list[dict[str, Any]] = [
    {"id": "IG01", "q": "¿Cuál es la misión y la visión de Banco Santa Cruz y qué diferencia hay entre ambas?", "expect": ["mision", "vision"]},
    {"id": "IG06", "q": "Explícame qué es una fecha de corte, qué es la fecha límite de pago y en qué se diferencian", "expect": ["corte", "limite"]},
    {"id": "CD01", "q": "¿Qué es Crédito Diferido y cuáles modalidades tiene disponibles?", "expect": ["diferido", "multicredit", "cuotas"]},
    {"id": "CD02", "q": "¿Cuál es la diferencia entre Multicrédito BSC y Cuotas BSC?", "expect": ["multicredit", "cuotas"]},
    {"id": "CD20", "q": "Cuáles son mis responsabilidades al utilizar Crédito Diferido y cuáles son las del banco?", "expect": ["responsab", "cliente", "banco"]},
    {"id": "TC01", "q": "¿Qué tarjetas de crédito ofrece Banco Santa Cruz?", "expect": ["visa", "tarjeta"]},
    {"id": "TC03", "q": "¿Qué características tiene la Visa Joven y a quién está dirigida?", "expect": ["joven"]},
    {"id": "TD05", "q": "¿Cómo funcionan las compras internacionales con tarjeta de débito y la conversión de moneda?", "expect": ["conversion", "visa", "internacional", "moneda"]},
    {"id": "PR01", "q": "¿Qué tipos de préstamos personales ofrece Banco Santa Cruz?", "expect": ["prestamo"]},
    {"id": "PR02", "q": "¿Cuál es la diferencia entre un préstamo personal con garantía y uno sin garantía?", "expect": ["garantia"]},
    {"id": "CU01", "q": "¿Qué tipos de cuentas ofrece Banco Santa Cruz?", "expect": ["ahorro", "corriente", "nomina", "cuenta", "deposit"]},
    {"id": "REC01", "q": "¿Cómo hago una reclamación en Banco Santa Cruz?", "expect": ["reclam", "809"]},
]

GUIDE_PERSONAL_CTX: list[dict[str, Any]] = [
    {
        "id": "C01",
        "kind": "personal_context",
        "turns": [
            "Dime el saldo de mi cuenta de ahorros",
            "¿Y cuánto puedo usar?",
            "¿Y los últimos movimientos?",
        ],
        "forbid": ["cognitive_turn_failed", "no entendi tu solicitud"],
    },
    {
        "id": "C04",
        "kind": "personal_context",
        "turns": [
            "¿Cuánto debo del préstamo personal?",
            "¿Y la próxima cuota?",
            "¿Cuándo debo pagarla?",
        ],
        "forbid": ["cognitive_turn_failed"],
    },
    {
        "id": "MIX01",
        "kind": "mixed",
        "turns": [
            "¿Qué es el pago mínimo de una tarjeta de crédito?",
            "Y el mío, ¿cuánto es?",
        ],
        "forbid": ["cognitive_turn_failed"],
    },
]


def start_session(base: str, client_id: str) -> dict[str, Any]:
    code, data, dt = http_json(
        base,
        "/orch/webhook/session",
        {"allow_lab_fallback": True},
        headers={"ClientId": client_id},
    )
    data["_http"] = code
    data["_latency"] = round(dt, 3)
    return data


def chat(base: str, client_id: str, conversation_id: str, question: str) -> dict[str, Any]:
    code, data, dt = http_json(
        base,
        "/orch/webhook/chat",
        {"question": question, "conversation_id": conversation_id, "allow_lab_fallback": True},
        headers={"ClientId": client_id, "X-Conversation-Id": conversation_id},
    )
    data["_http"] = code
    data["_latency"] = round(dt, 3)
    data["_reply"] = extract_reply(data)
    return data


def inspect_diag(base: str, customer_id: str, question: str, conversation_id: str) -> dict[str, Any]:
    code, data, dt = http_json(
        base,
        "/inspect",
        {
            "question": question,
            "customer_id": customer_id,
            "conversation_id": f"{conversation_id}-insp-{uuid.uuid4().hex[:6]}",
        },
    )
    return {
        "http": code,
        "latency": round(dt, 3),
        "rag_status": data.get("rag_status"),
        "reply": (data.get("client_response") or "")[:220],
        "steps": [x.get("step") for x in (data.get("decision_trace") or []) if isinstance(x, dict)],
    }


def eval_expect(reply: str, expect_groups: list[list[str]] | None, must_keep: list[str] | None, forbid: list[str] | None) -> tuple[bool, str]:
    rn = _norm(reply)
    if not reply or len(reply) < 12:
        return False, "empty_reply"
    if forbid:
        for f in forbid:
            if _norm(f) in rn:
                return False, f"forbidden:{f}"
    if "cognitive_turn_failed" in rn:
        return False, "cognitive_turn_failed"
    if expect_groups:
        # al menos un token de cada grupo? No: expect_any = alguno del grupo
        hit = any(any(tok in rn for tok in group) for group in [expect_groups] if False)
        # expect_any is a list of groups for THIS turn only (one group list)
        # callers pass a single group list for the turn
    return True, "ok"


def eval_turn(reply: str, expect_any: list[str] | None, must_keep: list[str] | None, forbid: list[str] | None) -> tuple[bool, str]:
    rn = _norm(reply)
    if not reply or len(reply.strip()) < 8:
        return False, "empty_reply"
    if "cognitive_turn_failed" in rn:
        return False, "cognitive_turn_failed"
    if forbid and any(_norm(f) in rn for f in forbid):
        return False, "forbidden"
    if expect_any and not any(tok in rn for tok in expect_any):
        return False, "missing_expected_tokens"
    # must_keep: soft — al menos uno del conjunto en la conversación se valida aparte
    return True, "ok"


def run_multiturn(
    base: str,
    client_id: str,
    scenario: dict[str, Any],
    *,
    diag: bool,
) -> dict[str, Any]:
    sess = start_session(base, client_id)
    cid = str(sess.get("conversation_id") or uuid.uuid4())
    turns_out = []
    ok_all = True
    keep_hits = 0
    must_keep = scenario.get("must_keep") or []
    for i, q in enumerate(scenario["turns"]):
        data = chat(base, client_id, cid, q)
        reply = data.get("_reply") or ""
        expect = None
        if scenario.get("expect_any") and i < len(scenario["expect_any"]):
            expect = scenario["expect_any"][i]
        ok, reason = eval_turn(reply, expect, must_keep, scenario.get("forbid"))
        if must_keep and any(k in _norm(reply) for k in must_keep):
            keep_hits += 1
        row: dict[str, Any] = {
            "i": i + 1,
            "q": q,
            "ok": ok,
            "reason": reason,
            "latency": data.get("_latency"),
            "http": data.get("_http"),
            "reply": reply[:220].replace("\n", " "),
            "status": data.get("status") or (data.get("app_channel") or {}).get("status"),
        }
        if diag and i == 0:
            row["inspect"] = inspect_diag(base, client_id, q, cid)
        if not ok:
            ok_all = False
        turns_out.append(row)
        time.sleep(0.08)

    # Contexto: en turnos 2+ debe aparecer al menos 1 señal del tema en >=50% de turnos
    ctx_ok = True
    if must_keep and len(turns_out) >= 2:
        ctx_ok = keep_hits >= max(1, len(turns_out) // 2)
        if not ctx_ok:
            ok_all = False

    return {
        "id": scenario["id"],
        "kind": scenario.get("kind"),
        "ok": ok_all and ctx_ok,
        "context_ok": ctx_ok,
        "keep_hits": keep_hits,
        "conversation_id": cid,
        "turns": turns_out,
    }


def run_singles(base: str, client_id: str, cases: list[dict[str, Any]], *, diag: bool) -> list[dict[str, Any]]:
    out = []
    for case in cases:
        sess = start_session(base, client_id)
        cid = str(sess.get("conversation_id") or uuid.uuid4())
        data = chat(base, client_id, cid, case["q"])
        reply = data.get("_reply") or ""
        ok, reason = eval_turn(reply, case.get("expect"), None, None)
        row = {
            "id": case["id"],
            "kind": "kb_single",
            "ok": ok,
            "reason": reason,
            "q": case["q"],
            "reply": reply[:220].replace("\n", " "),
            "latency": data.get("_latency"),
            "http": data.get("_http"),
            "conversation_id": cid,
        }
        if diag:
            row["inspect"] = inspect_diag(base, client_id, case["q"], cid)
        out.append(row)
        time.sleep(0.05)
    return out


def summarize_foundry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    steps: dict[str, int] = {}
    for r in rows:
        insp = r.get("inspect")
        if not insp and r.get("turns"):
            insp = (r["turns"][0] or {}).get("inspect")
        if not insp:
            continue
        st = str(insp.get("rag_status") or "NONE")
        statuses[st] = statuses.get(st, 0) + 1
        for s in insp.get("steps") or []:
            steps[str(s)] = steps.get(str(s), 0) + 1
    return {"rag_status_counts": statuses, "trace_step_counts": steps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--client", default="CUST001", help="ClientId / customer lab")
    ap.add_argument("--limit", type=int, default=0, help="Limitar escenarios multi-turno")
    ap.add_argument("--no-diag", action="store_true")
    ap.add_argument("--skip-personal", action="store_true")
    args = ap.parse_args()

    diag = not args.no_diag
    multi = list(GUIDE_CTX)
    if not args.skip_personal:
        multi.extend(GUIDE_PERSONAL_CTX)
    if args.limit and args.limit > 0:
        multi = multi[: args.limit]

    print(f"Base={args.base} client={args.client} multiturn={len(multi)} singles={len(GUIDE_KB_SINGLE)}")
    results_multi = []
    for sc in multi:
        print(f"  >> {sc['id']} ({len(sc['turns'])} turns)...")
        res = run_multiturn(args.base, args.client, sc, diag=diag)
        results_multi.append(res)
        mark = "OK" if res["ok"] else "FAIL"
        print(f"     {mark} context={res.get('context_ok')} keep={res.get('keep_hits')}")
        if not res["ok"]:
            for t in res["turns"]:
                if not t["ok"]:
                    print(f"       T{t['i']} {t['reason']}: {t['q'][:50]} -> {t['reply'][:80]}")

    print("  >> KB singles...")
    singles = run_singles(args.base, args.client, GUIDE_KB_SINGLE, diag=diag)
    for s in singles:
        if not s["ok"]:
            print(f"     FAIL {s['id']} {s['reason']}: {s['reply'][:90]}")

    all_rows = results_multi + singles
    passed = sum(1 for r in all_rows if r.get("ok"))
    total = len(all_rows)
    foundry = summarize_foundry(all_rows)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base": args.base,
        "client_id": args.client,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / max(total, 1), 4),
        "foundry_diag": foundry,
        "failures": [r for r in all_rows if not r.get("ok")],
        "results": all_rows,
    }
    out_dir = ROOT / "Test_local" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"orch_sdk_guide_{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"RESULT {passed}/{total} ({report['pass_rate']*100:.1f}%) "
        f"foundry_diag={foundry.get('rag_status_counts')} report={out}"
    )
    return 0 if report["pass_rate"] >= 0.7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
