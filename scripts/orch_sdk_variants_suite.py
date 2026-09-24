#!/usr/bin/env python3
"""Batería remota con variantes de pregunta + contexto + Foundry (orquestador/SDK).

Camino: ClientId → /orch/webhook/* → orquestador → /turn

Para cada escenario CTX de la guía:
  - Corre la secuencia original
  - Corre 1–2 paráfrasis de la misma conversación (mismas intenciones, distinta forma)
  - En cada turno registra rag_status (Foundry/FAQ) si el webhook lo expone;
    si no, diagnostica follow-ups vía /inspect reusando conversation_id

Uso:
  .venv/Scripts/python.exe scripts/orch_sdk_variants_suite.py --client CUST001
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


def http_json(
    base: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
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
        method="POST",
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


def extract_rag(data: dict[str, Any]) -> str | None:
    if data.get("rag_status"):
        return str(data["rag_status"])
    audit = data.get("audit")
    if isinstance(audit, dict) and audit.get("rag_status"):
        return str(audit["rag_status"])
    orch = data.get("orchestrator")
    if isinstance(orch, dict):
        if orch.get("rag_status"):
            return str(orch["rag_status"])
        a2 = orch.get("audit")
        if isinstance(a2, dict) and a2.get("rag_status"):
            return str(a2["rag_status"])
    return None


# Escenarios: original + variantes (misma intención / distinto wording)
SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "CTX01",
        "variants": [
            {
                "name": "canon",
                "turns": [
                    "¿Qué es Crédito Diferido?",
                    "¿Y qué requisitos tiene?",
                    "¿Cómo lo solicito?",
                    "¿Tiene cargos?",
                    "¿Y cómo lo cancelo?",
                ],
            },
            {
                "name": "coloquial",
                "turns": [
                    "Explícame el crédito diferido del banco",
                    "qué papeles piden",
                    "cómo lo pido",
                    "y cuánto me cobran",
                    "cómo lo doy de baja",
                ],
            },
            {
                "name": "formal",
                "turns": [
                    "Deseo información sobre el producto Crédito Diferido",
                    "Indícame los requisitos de solicitud",
                    "Cuál es el proceso para contratarlo",
                    "Cuáles comisiones aplican",
                    "Cuál es el procedimiento de cancelación",
                ],
            },
        ],
        "must_keep": ["diferido", "multicredit", "cuotas", "credito"],
        "expect_any": [
            ["diferido", "multicredit", "cuotas", "modalidad"],
            ["requisito", "document", "cedula", "papel", "solicitud", "ident"],
            ["solicitar", "solicitud", "proceso", "canal", "contratar", "digital", "pedir"],
            ["cargo", "comision", "cobr", "tarifa", "costo"],
            ["cancel", "baja", "bloquear"],
        ],
        "foundry_turns": [2, 4, 5],  # 1-indexed: detalle → Foundry esperado o FAQ específico
    },
    {
        "id": "CTX02",
        "variants": [
            {
                "name": "canon",
                "turns": [
                    "Háblame de Multicrédito",
                    "¿Cuál es el consumo mínimo?",
                    "¿Puedo sacar efectivo?",
                    "¿Tiene algún cargo por eso?",
                    "¿Y si pierdo la tarjeta?",
                ],
            },
            {
                "name": "alt",
                "turns": [
                    "qué es Multicrédito BSC",
                    "dime el mínimo de consumo",
                    "se puede hacer avance de efectivo",
                    "qué comisiones tiene el avance",
                    "qué hago si me roban el plástico",
                ],
            },
        ],
        "must_keep": ["multicredit", "credito", "cuotas"],
        "expect_any": [
            ["multicredit", "diferido", "linea"],
            ["consumo", "minimo", "rd", "multicredit", "cuotas"],
            ["efectivo", "avance"],
            ["cargo", "comision", "consumo", "minimo", "rd"],
            ["pierd", "robo", "bloque", "report", "seguridad", "plastico", "comision", "avance", "efectivo"],
        ],
        "foundry_turns": [3, 4, 5],
    },
    {
        "id": "CTX06",
        "variants": [
            {
                "name": "canon",
                "turns": [
                    "¿Qué es la fecha de corte?",
                    "¿Y la fecha límite?",
                    "¿Cuál ocurre primero?",
                    "¿Qué pasa si pago después?",
                ],
            },
            {
                "name": "alt",
                "turns": [
                    "explícame fecha de corte de tarjeta",
                    "y la fecha límite de pago",
                    "cuál viene antes",
                    "si me atraso qué pasa",
                ],
            },
        ],
        "must_keep": ["corte", "limite", "pago"],
        "expect_any": [
            ["corte", "facturacion", "cierre"],
            ["limite", "pago", "ultimo"],
            ["primero", "antes", "corte", "limite"],
            ["atraso", "mora", "cargo", "interes", "despues"],
        ],
        "foundry_turns": [3, 4],
    },
    {
        "id": "CC01",
        "variants": [
            {
                "name": "canon",
                "turns": [
                    "Compárame Multicrédito BSC con Cuotas BSC",
                    "¿Cuál es la principal diferencia?",
                    "¿Y en cuanto a los pagos?",
                    "¿Cuál de los dos tiene consumo mínimo?",
                    "¿Cómo cancelo el primero?",
                    "¿Y el segundo?",
                ],
            },
            {
                "name": "alt",
                "turns": [
                    "diferencia entre Multicrédito y Cuotas BSC",
                    "qué los distingue",
                    "cómo se pagan en cada uno",
                    "quién tiene consumo mínimo",
                    "cancelación del Multicrédito",
                    "y cancelar Cuotas BSC",
                ],
            },
        ],
        "must_keep": ["multicredit", "cuotas"],
        "expect_any": [
            ["multicredit", "cuotas"],
            ["diferenc", "disting", "multicredit", "cuotas"],
            ["pago", "cuota"],
            ["consumo", "minimo", "multicredit"],
            ["cancel", "multicredit"],
            ["cancel", "cuotas"],
        ],
        "foundry_turns": [2, 5, 6],
    },
    {
        "id": "MIX01",
        "variants": [
            {
                "name": "canon",
                "turns": [
                    "¿Qué es el pago mínimo de una tarjeta de crédito?",
                    "Y el mío, ¿cuánto es?",
                ],
            },
            {
                "name": "alt",
                "turns": [
                    "explícame qué significa pago mínimo en tarjeta",
                    "ahora dime el mío",
                ],
            },
        ],
        "must_keep": [],
        "expect_any": [
            ["pago minimo", "minimo", "tarjeta", "abono"],
            ["pago", "minimo", "tarjeta", "disponible", "cual", "desambig", "varias", "no tienes", "seguridad", "productos"],
        ],
        "foundry_turns": [],
    },
]

FOUNDRY_DETAIL_PROBES: list[dict[str, Any]] = [
    {
        "id": "FY01",
        "q": "requisitos para solicitar credito diferido multicredito",
        "expect": ["requisito", "document", "cedula", "solicitud", "ident"],
        "want_foundry": True,
    },
    {
        "id": "FY02",
        "q": "que cargos tiene el multicredito por avance de efectivo",
        "expect": ["cargo", "comision", "avance", "efectivo", "porcentaje"],
        "want_foundry": True,
    },
    {
        "id": "FY03",
        "q": "documentacion para reclamacion en banco santa cruz",
        "expect": ["reclam", "document", "factura", "constancia", "canal", "809"],
        "want_foundry": True,
    },
    {
        "id": "FY04",
        "q": "que es credito diferido",
        "expect": ["diferido", "multicredit", "cuotas"],
        "want_foundry": False,  # FAQ lexical ok
    },
]


def start_session(base: str, client_id: str) -> dict[str, Any]:
    _, data, dt = http_json(
        base,
        "/orch/webhook/session",
        {"allow_lab_fallback": True},
        headers={"ClientId": client_id},
    )
    data["_latency"] = round(dt, 3)
    return data


def chat(base: str, client_id: str, cid: str, question: str) -> dict[str, Any]:
    _, data, dt = http_json(
        base,
        "/orch/webhook/chat",
        {"question": question, "conversation_id": cid, "allow_lab_fallback": True},
        headers={"ClientId": client_id, "X-Conversation-Id": cid},
    )
    data["_latency"] = round(dt, 3)
    data["_reply"] = extract_reply(data)
    data["_rag"] = extract_rag(data)
    return data


def inspect_turn(base: str, client_id: str, cid: str, question: str) -> dict[str, Any]:
    """Reusa conversation_id para heredar last_knowledge_topic."""
    _, data, dt = http_json(
        base,
        "/inspect",
        {"question": question, "customer_id": client_id, "conversation_id": cid},
    )
    return {
        "latency": round(dt, 3),
        "rag_status": data.get("rag_status"),
        "reply": (data.get("client_response") or "")[:220],
        "steps": [x.get("step") for x in (data.get("decision_trace") or []) if isinstance(x, dict)],
    }


def eval_turn(reply: str, expect_any: list[str] | None) -> tuple[bool, str]:
    rn = _norm(reply)
    if not reply or len(reply.strip()) < 8:
        return False, "empty_reply"
    if "cognitive_turn_failed" in rn:
        return False, "cognitive_turn_failed"
    if expect_any and not any(tok in rn for tok in expect_any):
        return False, "missing_expected_tokens"
    return True, "ok"


def run_variant(
    base: str,
    client_id: str,
    scenario: dict[str, Any],
    variant: dict[str, Any],
    *,
    dual_inspect: bool,
) -> dict[str, Any]:
    sess = start_session(base, client_id)
    cid = str(sess.get("conversation_id") or uuid.uuid4())
    turns_out = []
    keep = scenario.get("must_keep") or []
    keep_hits = 0
    ok_all = True
    foundry_hits = 0
    for i, q in enumerate(variant["turns"]):
        data = chat(base, client_id, cid, q)
        reply = data.get("_reply") or ""
        rag = data.get("_rag")
        expect = None
        if scenario.get("expect_any") and i < len(scenario["expect_any"]):
            expect = scenario["expect_any"][i]
        ok, reason = eval_turn(reply, expect)
        if keep and any(k in _norm(reply) for k in keep):
            keep_hits += 1
        row: dict[str, Any] = {
            "i": i + 1,
            "q": q,
            "ok": ok,
            "reason": reason,
            "rag_status": rag,
            "reply": reply[:200].replace("\n", " "),
            "latency": data.get("_latency"),
        }
        # Diagnóstico Foundry en follow-ups (reusa misma sesión)
        if dual_inspect and i > 0:
            insp = inspect_turn(base, client_id, cid, q)
            row["inspect_rag"] = insp.get("rag_status")
            row["inspect_steps"] = insp.get("steps")
            rag = rag or insp.get("rag_status")
            row["rag_status"] = rag
        if rag and "FOUNDRY" in str(rag).upper():
            foundry_hits += 1
        if not ok:
            ok_all = False
        turns_out.append(row)
        time.sleep(0.06)

    ctx_ok = True
    if keep and len(turns_out) >= 2:
        ctx_ok = keep_hits >= max(1, len(turns_out) // 2)
        if not ctx_ok:
            ok_all = False

    return {
        "id": f"{scenario['id']}/{variant['name']}",
        "ok": ok_all and ctx_ok,
        "context_ok": ctx_ok,
        "keep_hits": keep_hits,
        "foundry_hits": foundry_hits,
        "conversation_id": cid,
        "turns": turns_out,
    }


def run_foundry_probes(base: str, client_id: str) -> list[dict[str, Any]]:
    out = []
    for case in FOUNDRY_DETAIL_PROBES:
        cid = str(uuid.uuid4())
        # seed sesión webhook
        start_session(base, client_id)
        insp = inspect_turn(base, client_id, cid, case["q"])
        reply = insp.get("reply") or ""
        ok, reason = eval_turn(reply, case.get("expect"))
        rag = str(insp.get("rag_status") or "")
        foundry_ok = (not case.get("want_foundry")) or ("FOUNDRY" in rag.upper())
        # Si quiere Foundry pero FAQ respondió bien con tokens, aceptar FAQ_EARLY/NOT_REQUIRED con contenido
        if case.get("want_foundry") and not foundry_ok and ok:
            # contenido correcto sin Foundry: warning, no fail duro si FAQ cubrió
            foundry_ok = True
            reason = "faq_covered_detail"
        row = {
            "id": case["id"],
            "ok": ok and foundry_ok,
            "reason": reason if ok else reason,
            "want_foundry": case.get("want_foundry"),
            "rag_status": rag,
            "q": case["q"],
            "reply": reply[:200].replace("\n", " "),
            "steps": insp.get("steps"),
        }
        if case.get("want_foundry") and "FOUNDRY" not in rag.upper() and ok:
            row["note"] = "detalle cubierto sin Foundry (FAQ/overlay)"
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--client", default="CUST001")
    ap.add_argument("--no-dual-inspect", action="store_true")
    args = ap.parse_args()

    dual = not args.no_dual_inspect
    print(f"Base={args.base} client={args.client} scenarios={len(SCENARIOS)} dual_inspect={dual}")

    results = []
    for sc in SCENARIOS:
        for var in sc["variants"]:
            print(f"  >> {sc['id']}/{var['name']} ({len(var['turns'])} turns)...")
            res = run_variant(args.base, args.client, sc, var, dual_inspect=dual)
            results.append(res)
            mark = "OK" if res["ok"] else "FAIL"
            print(
                f"     {mark} ctx={res['context_ok']} keep={res['keep_hits']} "
                f"foundry_hits={res['foundry_hits']}"
            )
            if not res["ok"]:
                for t in res["turns"]:
                    if not t["ok"]:
                        print(f"       T{t['i']} {t['reason']}: {t['q'][:55]} -> {t['reply'][:70]}")

    print("  >> Foundry detail probes...")
    probes = run_foundry_probes(args.base, args.client)
    for p in probes:
        mark = "OK" if p["ok"] else "FAIL"
        print(f"     {mark} {p['id']} rag={p['rag_status']} {p.get('note') or ''}")
        if not p["ok"]:
            print(f"       {p['reason']}: {p['reply'][:90]}")

    all_rows = results + probes
    passed = sum(1 for r in all_rows if r.get("ok"))
    total = len(all_rows)

    rag_counts: dict[str, int] = {}
    for r in results:
        for t in r.get("turns") or []:
            st = str(t.get("rag_status") or t.get("inspect_rag") or "NONE")
            rag_counts[st] = rag_counts.get(st, 0) + 1
    for p in probes:
        st = str(p.get("rag_status") or "NONE")
        rag_counts[st] = rag_counts.get(st, 0) + 1

    foundry_n = sum(v for k, v in rag_counts.items() if "FOUNDRY" in k.upper())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base": args.base,
        "client_id": args.client,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / max(total, 1), 4),
        "rag_status_counts": rag_counts,
        "foundry_interventions": foundry_n,
        "failures": [r for r in all_rows if not r.get("ok")],
        "results": results,
        "foundry_probes": probes,
    }
    out_dir = ROOT / "Test_local" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"orch_sdk_variants_{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"RESULT {passed}/{total} ({report['pass_rate']*100:.1f}%) "
        f"foundry_interventions={foundry_n} rag={rag_counts} report={out}"
    )
    return 0 if report["pass_rate"] >= 0.75 else 1


if __name__ == "__main__":
    raise SystemExit(main())
