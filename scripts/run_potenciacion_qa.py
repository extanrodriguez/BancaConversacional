#!/usr/bin/env python3
"""Runner Potenciación Lunes — Fase 5/6.

Ejecuta casos vía POST /turn, conserva historial en works/qa_runs/,
separa origen (mock/lab/Azure/Core) y no cuenta omitidos como aprobados.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from potenciacion_eval import ORACLE_VERSION, evaluate_case  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes"
CASOS = PKG / "evaluacion" / "casos_236.json"
P0 = PKG / "evaluacion" / "aceptacion_p0.json"
RUNS = ROOT / "works" / "qa_runs"
DEFAULT_BASE = "http://20.127.25.24:8447"
CUSTOMER = "726588"
LOCK = RUNS / ".runner.lock"
CODE_VERSION = "potenciacion-strict-v2.2"
KNOWLEDGE_VERSION = "bsc-kb-2026-09-19-candidate-1"


def acquire_lock() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    # Crear exclusivamente para evitar carrera entre procesos duplicados
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {utc_now()}\n")
        return
    except FileExistsError:
        pass
    try:
        old = LOCK.read_text(encoding="utf-8").strip()
        pid = int(old.split()[0])
    except Exception:
        try:
            LOCK.unlink()
        except OSError:
            pass
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {utc_now()}\n")
        return
    alive = False
    try:
        import subprocess
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        )
        alive = str(pid) in (r.stdout or "") and "INFO:" not in (r.stdout or "")
    except Exception:
        alive = False
    if alive:
        raise SystemExit(f"Otro runner activo (pid={pid}). Aborto.")
    try:
        LOCK.unlink()
    except OSError:
        pass
    fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {utc_now()}\n")


def release_lock() -> None:
    try:
        if LOCK.exists():
            data = LOCK.read_text(encoding="utf-8")
            if data.startswith(str(os.getpid())):
                LOCK.unlink()
    except OSError:
        pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize(text: str) -> str:
    s = text or ""
    s = re.sub(r"\b\d{4,}\b", "####", s)
    s = re.sub(r"(?i)(RD\$|US\$|\$)\s*[\d,.]+", r"\1[AMT]", s)
    s = re.sub(r"(?i)\b\d[\d,.]*\s*%", "[RATE]%", s)
    return s[:1200]


def http_json(base: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 150) -> dict[str, Any]:
    url = base.rstrip("/") + path
    t0 = time.perf_counter()
    try:
        if payload is None:
            req = request.Request(url, method="GET")
        else:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
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
    except Exception as exc:
        return {"http": 0, "ms": int((time.perf_counter() - t0) * 1000), "body": {"error": str(exc)}}
    return {"http": code, "ms": int((time.perf_counter() - t0) * 1000), "body": body}


def post(base: str, path: str, payload: dict[str, Any], timeout: float = 150) -> dict[str, Any]:
    return http_json(base, path, payload, timeout=timeout)


def reply_of(body: dict[str, Any]) -> str:
    app = body.get("app_channel") or {}
    return str(
        body.get("reply")
        or body.get("message")
        or body.get("client_response")
        or app.get("client_response")
        or body.get("error")
        or ""
    )


def options_of(body: dict[str, Any]) -> list[Any]:
    app = body.get("app_channel") or {}
    opts = app.get("options") or body.get("options") or []
    return opts if isinstance(opts, list) else []


def split_turns(case: dict[str, Any]) -> list[str]:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        out: list[str] = []
        for t in turns:
            if not isinstance(t, str):
                continue
            parts = [p.strip() for p in re.split(r"\s*(?:→|->|⇒)\s*", t) if p.strip()]
            out.extend(parts or [t.strip()])
        return out
    q = str(case.get("question") or "").strip()
    return [q] if q else []


def extract_trace(body: dict[str, Any]) -> dict[str, Any]:
    """Extrae ruta/proveedor/atajo/versiones/tareas del cuerpo /turn.

    El canal web suele envolver la telemetría en `audit` (no en la raíz).
    """
    audit = body.get("audit") if isinstance(body.get("audit"), dict) else {}
    trace_steps = audit.get("decision_trace") or body.get("decision_trace") or []
    first = (trace_steps[0].get("output") if trace_steps and isinstance(trace_steps[0], dict) else {}) or {}
    route = None
    reason = None
    shortcut = None
    brain = first.get("brain_source") or audit.get("brain_source") or body.get("brain_source")
    task_statuses = dict(first.get("task_statuses") or {})
    evidence = first.get("evidence_sources") or first.get("evidence") or body.get("evidence_sources") or audit.get("evidence_sources")
    for step in trace_steps:
        if not isinstance(step, dict):
            continue
        name = str(step.get("step") or "")
        out = step.get("output") or {}
        if isinstance(out.get("task_statuses"), dict):
            task_statuses.update(out["task_statuses"])
        if out.get("brain_source"):
            brain = out.get("brain_source")
        if out.get("evidence_sources"):
            evidence = out.get("evidence_sources")
        rs = str(out.get("route_source") or "")
        if (
            "shortcut" in name
            or out.get("shortcut_reason")
            or out.get("brain_source") in ("structured_shortcut", "deterministic_fastpath_pre_azure")
            or rs.startswith("shortcut:")
            or rs.startswith("field_fastpath:")
        ):
            shortcut = (
                out.get("shortcut_reason")
                or out.get("fastpath_step")
                or rs
                or out.get("source")
                or name
            )
            route = "structured_shortcut" if "shortcut" in str(brain or rs) else (
                "deterministic_fastpath" if "fastpath" in str(brain or rs) else route
            )
            reason = shortcut
        if name in ("azure_plan_error", "azure_plan", "azure_plan_invalid"):
            route = route or "azure_plan"
        if out.get("semantic_mode") and not route:
            route = str(out.get("semantic_mode"))
        if out.get("degraded"):
            reason = reason or "provider_error"
        if out.get("error_stage"):
            reason = reason or str(out.get("error_stage"))
    app = body.get("app_channel") or {}
    # Solo provider explícito — NUNCA usar deployment (nombre de modelo) como proveedor
    provider = body.get("provider") or audit.get("provider") or first.get("provider")
    if provider and str(provider).lower().startswith("gpt-"):
        # Etiqueta errónea: deployment colado como provider
        provider = None
    inference_count = int(
        first.get("inference_count")
        if first.get("inference_count") is not None
        else (
            audit.get("inference_count")
            if audit.get("inference_count") is not None
            else (body.get("inference_count") or 0)
        )
    )
    # Preferir etiqueta honesta cuando el cuerpo aún dice AZURE_OPENAI en atajos
    if brain == "structured_shortcut" or (shortcut and "fastpath" not in str(brain or "")):
        if provider in (None, "", "AZURE_OPENAI") and inference_count == 0:
            provider = "STRUCTURED_SHORTCUT"
            route = route or "structured_shortcut"
            reason = reason or shortcut or "structured_shortcut"
    if brain == "deterministic_fastpath_pre_azure" or str(first.get("route_source") or "").startswith("field_fastpath:"):
        if provider in (None, "", "AZURE_OPENAI") and inference_count == 0:
            provider = "DETERMINISTIC_FASTPATH"
            route = route or "deterministic_fastpath"
            reason = reason or first.get("fastpath_step") or shortcut
    # Heurística / turn_plan_multi en VM Azure sin llamada al modelo
    step0 = str((trace_steps[0].get("step") if trace_steps else "") or "")
    if inference_count == 0 and (
        step0 in ("turn_plan_multi", "plan_executor", "heuristic")
        or brain in ("heuristic_multi", "heuristic", "kb_joven", "kb_cancelacion")
        or str(first.get("source") or "") in ("plan_executor", "heuristic_multi")
    ):
        if provider in (None, "", "AZURE_OPENAI"):
            provider = "LOCAL_HEURISTIC_PLAN"
        route = route or "local_heuristic_plan"
        reason = reason or str(first.get("source") or brain or step0)
        brain = brain or str(first.get("source") or "heuristic_plan")
    if brain in ("resolve_full", "azure_plan") and inference_count > 0:
        provider = provider or "AZURE_OPENAI"
        route = route or "azure_plan_model"
        reason = reason or "model_inference"
    elif brain in ("resolve_full", "azure_plan") and inference_count == 0:
        provider = provider if provider and provider != "AZURE_OPENAI" else "LOCAL_HEURISTIC_PLAN"
        route = route or "azure_plan_no_model"
        reason = reason or "no_model_calls"
    if brain == "structural_repair" and inference_count == 0:
        provider = "LOCAL_HEURISTIC_PLAN"
        route = route or "structural_repair"
    # AZURE_OPENAI con 0 inferencias = etiqueta falsa heredada
    if provider == "AZURE_OPENAI" and inference_count == 0 and not shortcut:
        provider = "LOCAL_HEURISTIC_PLAN"
        route = route or "undeclared_no_model"
        reason = reason or "provider_label_without_inference"
    # Sin telemetría efectiva: declarar desconocido (VM Azure ≠ inferencia)
    if not provider:
        provider = "UNDECLARED"
        route = route or "undeclared"
        reason = reason or "missing_decision_trace_provider"
    resolved = sorted(k for k, v in task_statuses.items() if v in ("available", "ready"))
    pending = sorted(k for k, v in task_statuses.items() if v in ("needs_clarification", "pending"))
    failed = sorted(k for k, v in task_statuses.items() if v in ("absent", "refused", "error", "failed"))
    return {
        "route": route or audit.get("semantic_mode") or body.get("mode") or "undeclared",
        "route_reason": reason or first.get("shortcut_reason") or first.get("error_stage") or first.get("route_source"),
        "provider": provider,
        "model_invoked": bool(inference_count > 0 and str(provider) == "AZURE_OPENAI"),
        "inference_count": inference_count,
        "host_env": "azure_vm_qa",
        "model": body.get("model") or first.get("deployment") or audit.get("model"),
        "prompt_version": body.get("prompt_version") or first.get("prompt_version"),
        "semantic_mode": first.get("semantic_mode") or audit.get("semantic_mode") or body.get("semantic_mode"),
        "shortcut": shortcut,
        "brain_source": brain,
        "intent_id": body.get("intent_id") or app.get("intent_id"),
        "rag_status": body.get("rag_status") or audit.get("rag_status"),
        "status": body.get("status") or app.get("status"),
        "latency_ms": body.get("total_request_ms") or audit.get("total_ms") or (trace_steps[0].get("duration_ms") if trace_steps else None),
        "context_source": (
            (body.get("customer_context") or {}).get("context_source")
            or body.get("context_source")
            or audit.get("context_source")
        ),
        "evidence_sources": evidence,
        "tasks_resolved": resolved,
        "tasks_pending": pending,
        "tasks_failed": failed,
        "task_statuses": task_statuses or None,
        "cognitive_code_version": (
            body.get("cognitive_code_version")
            or first.get("cognitive_code_version")
            or audit.get("cognitive_code_version")
        ),
        "knowledge_version": (
            body.get("knowledge_version")
            or first.get("knowledge_version")
            or audit.get("knowledge_version")
        ),
        "correlation_id": audit.get("correlation_id") or body.get("correlation_id"),
        "field_accreditation": first.get("field_accreditation") or audit.get("field_accreditation"),
        "payment_window": first.get("payment_window") or audit.get("payment_window"),
    }


def load_session(base: str, conv: str, *, lab: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "customer_id": CUSTOMER,
        "conversation_id": conv,
        "allow_lab_fallback": lab,
    }
    if lab:
        payload["portfolio"] = "qa_726588_contract_demo.json"
    return post(base, "/orch/context", payload)


def turn(base: str, conv: str, question: str, selected: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question,
        "customer_id": CUSTOMER,
        "conversation_id": conv,
        "context_info": False,
        "channel": {"type": "web", "entrypoint": "potenciacion_lunes"},
    }
    if selected:
        payload["selected_option_ref"] = selected
    return post(base, "/turn", payload)


def pick_option(opts: list[Any], prefer: str | None = None) -> str | None:
    def _fold(s: str) -> str:
        return (
            (s or "")
            .lower()
            .replace("á", "a").replace("é", "e").replace("í", "i")
            .replace("ó", "o").replace("ú", "u").replace("ü", "u")
        )

    prefer_l = _fold(prefer or "")
    for o in opts:
        if not isinstance(o, dict):
            continue
        lab = _fold(str(o.get("label") or o.get("title") or ""))
        if prefer_l and prefer_l in lab:
            return str(o.get("ref") or (o.get("selection") or {}).get("selected_option_ref") or o.get("id") or "")
    if opts and isinstance(opts[0], dict):
        o = opts[0]
        return str(o.get("ref") or (o.get("selection") or {}).get("selected_option_ref") or o.get("id") or "") or None
    return None


def write_checksums(run_dir: Path) -> None:
    lines = []
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file() or p.name == "checksums.sha256":
            continue
        rel = p.relative_to(run_dir).as_posix()
        lines.append(f"{sha256_file(p)}  {rel}")
    (run_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_index(run_id: str, row: dict[str, Any]) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    idx = RUNS / "INDEX.md"
    if not idx.exists():
        idx.write_text(
            "# Historial de ejecuciones QA — Potenciación Lunes\n\n"
            "| Fecha UTC | Run ID | Entorno | Alcance | Resultado | Resumen |\n"
            "|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    line = (
        f"| {row['started']} | `{run_id}` | {row['env']} | {row['scope']} | "
        f"{row['summary_counts']} | [resumen]({run_id}/resumen.md) |\n"
    )
    with idx.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--scope", choices=["p0", "p0_plus_p", "all"], default="p0")
    ap.add_argument("--lab-fallback", action="store_true", default=True)
    ap.add_argument("--no-lab-fallback", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="", help="CSV de case_id a ejecutar")
    args = ap.parse_args()
    lab = not args.no_lab_fallback

    acquire_lock()
    try:
        return _main_inner(args, lab)
    finally:
        release_lock()


def _main_inner(args: argparse.Namespace, lab: bool) -> int:
    started = utc_now()
    run_id = f"{started}_{uuid.uuid4().hex[:8]}"
    run_dir = RUNS / run_id
    (run_dir / "evidencias").mkdir(parents=True, exist_ok=True)
    cmd_log = (run_dir / "comandos.log").open("w", encoding="utf-8")
    print(f"RUN_START {run_id} scope={args.scope}", flush=True)

    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    if isinstance(casos, dict):
        cases = casos.get("cases") or casos.get("items") or []
    else:
        cases = casos
    p0_list = json.loads(P0.read_text(encoding="utf-8"))
    p0_ids = {x.get("acceptance_id") for x in p0_list}

    only_ids = {x.strip() for x in (args.only or "").split(",") if x.strip()}

    if args.scope == "p0":
        selected = [c for c in cases if c.get("case_id") in p0_ids or c.get("case_id") in {
            "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10",
            "P11", "P12", "P13", "P14", "P15", "TC03", "GR03", "GR09", "IG01",
            "MIX07", "MIX09", "MIX10", "CC02", "CC03",
        }]
        # also include explicit p0 acceptance turns not in cases
        extra_ids = p0_ids - {c.get("case_id") for c in selected}
        for p in p0_list:
            if p.get("acceptance_id") in extra_ids:
                selected.append({
                    "case_id": p["acceptance_id"],
                    "question": (p.get("turns") or [""])[0],
                    "turns": p.get("turns") or [],
                    "expected": "; ".join(p.get("assertions") or []),
                })
    elif args.scope == "p0_plus_p":
        selected = [c for c in cases if str(c.get("case_id", "")).startswith("P")]
    else:
        selected = list(cases)

    if only_ids:
        selected = [c for c in selected if c.get("case_id") in only_ids]
        have = {c.get("case_id") for c in selected}
        for c in cases:
            if c.get("case_id") in only_ids and c.get("case_id") not in have:
                selected.append(c)
                have.add(c.get("case_id"))
        for p in p0_list:
            aid = p.get("acceptance_id")
            if aid in only_ids and aid not in have:
                selected.append({
                    "case_id": aid,
                    "question": (p.get("turns") or [""])[0],
                    "turns": p.get("turns") or [],
                    "expected": "; ".join(p.get("assertions") or []),
                })
                have.add(aid)

    if args.limit:
        selected = selected[: args.limit]

    # health
    health = http_json(args.base, "/health", None)
    cmd_log.write(f"GET /health -> {health.get('http')} {health.get('body')}\n")
    cmd_log.flush()
    print(f"HEALTH {health.get('http')} selected={len(selected)}", flush=True)

    results_path = run_dir / "resultados_casos.jsonl"
    turns_path = run_dir / "turnos.jsonl"
    counts = {
        "inventoried": len(cases),
        "selected": len(selected),
        "executed": 0,
        "PASS_RESOLVED": 0,
        "PASS_CLARIFICATION_EXPECTED": 0,
        "PARTIAL_CAPABILITY": 0,
        "PENDING_EVALUATION": 0,
        "FAIL_INTERPRETATION": 0,
        "FAIL_RETRIEVAL": 0,
        "FAIL_STATE": 0,
        "FAIL_GROUNDING": 0,
        "BLOCKED_DEPENDENCY": 0,
        "NOT_EXECUTED": 0,
        "turns": 0,
    }

    data_origin = "lab_fallback" if lab else "presentation_or_core"
    env_label = f"qa_remote:{args.base}"

    with results_path.open("w", encoding="utf-8") as rf, turns_path.open("w", encoding="utf-8") as tf:
        for case in selected:
            cid = str(case.get("case_id"))
            turns = split_turns(case)
            if not turns:
                counts["NOT_EXECUTED"] += 1
                rf.write(json.dumps({
                    "run_id": run_id,
                    "case_id": cid,
                    "status": "NOT_EXECUTED",
                    "reason": "sin turns",
                }, ensure_ascii=False) + "\n")
                continue

            conv = str(uuid.uuid4())
            ctx = load_session(args.base, conv, lab=lab)
            ctx_body = ctx.get("body") or {}
            context_source = ctx_body.get("context_source") or "unknown"
            if ctx.get("http") and ctx["http"] >= 400 and not lab:
                status = "BLOCKED_DEPENDENCY"
                counts[status] += 1
                rf.write(json.dumps({
                    "run_id": run_id,
                    "case_id": cid,
                    "status": status,
                    "reason": "context bootstrap failed",
                    "http": ctx.get("http"),
                    "data_origin": data_origin,
                }, ensure_ascii=False) + "\n")
                continue

            combined = ""
            turn_records = []
            eval_turns: list[dict[str, Any]] = []
            blocked = False
            for i, q in enumerate(turns, start=1):
                r = turn(args.base, conv, q)
                body = r.get("body") or {}
                text = reply_of(body)
                opts = options_of(body)
                trc = extract_trace(body)
                counts["turns"] += 1
                combined = (combined + "\n" + text).strip()
                eval_turns.append({
                    "question": q,
                    "reply": text,
                    "turn": i,
                    "audit": {
                        "field_accreditation": trc.get("field_accreditation"),
                        "payment_window": trc.get("payment_window"),
                        "provider": trc.get("provider"),
                        "route": trc.get("route"),
                        "context_source": trc.get("context_source"),
                    },
                })
                tr = {
                    "case_id": cid,
                    "turn": i,
                    "session": conv[:8],
                    "question": sanitize(q),
                    "reply": sanitize(text),
                    "http": r.get("http"),
                    "status": body.get("status"),
                    "options": len(opts),
                    "ms": r.get("ms"),
                    "data_origin": context_source,
                    "lab_fallback": lab,
                    "code_version": CODE_VERSION,
                    "knowledge_version": KNOWLEDGE_VERSION,
                    "oracle_version": ORACLE_VERSION,
                    **trc,
                }
                turn_records.append(tr)
                tf.write(json.dumps(tr, ensure_ascii=False) + "\n")
                if opts and (
                    str(body.get("status") or "") in ("requires_selection", "CLARIFICATION_REQUIRED")
                    or any(k in text.lower() for k in ("cuál", "cual", "quieres", "sobre cuál", "sobre cual"))
                ):
                    qn = q.lower()
                    prefer = None
                    if any(s in qn for s in ("multicredit", "multicrédito", "multi crédito", "multi credito")):
                        prefer = "multicredit"
                    elif any(s in qn for s in ("préstamo", "prestamo", "préstamos", "prestamos")):
                        prefer = "prestamo"
                    selected_ref = pick_option(opts, prefer)
                    if selected_ref:
                        r2 = turn(args.base, conv, q, selected=selected_ref)
                        body2 = r2.get("body") or {}
                        text2 = reply_of(body2)
                        trc2 = extract_trace(body2)
                        combined = (combined + "\n" + text2).strip()
                        eval_turns.append({"question": q, "reply": text2, "turn": f"{i}b", "selected": selected_ref, "audit": {
                            "field_accreditation": trc2.get("field_accreditation"),
                            "payment_window": trc2.get("payment_window"),
                            "provider": trc2.get("provider"),
                            "route": trc2.get("route"),
                            "context_source": trc2.get("context_source"),
                        }})
                        trb = {
                            "case_id": cid,
                            "turn": f"{i}b",
                            "session": conv[:8],
                            "question": sanitize(q),
                            "reply": sanitize(text2),
                            "http": r2.get("http"),
                            "status": body2.get("status"),
                            "selected_option_ref": selected_ref,
                            "ms": r2.get("ms"),
                            "data_origin": context_source,
                            "lab_fallback": lab,
                            "code_version": CODE_VERSION,
                            "knowledge_version": KNOWLEDGE_VERSION,
                            **trc2,
                        }
                        turn_records.append(trb)
                        tf.write(json.dumps(trb, ensure_ascii=False) + "\n")
                        counts["turns"] += 1
                if r.get("http") == 0:
                    blocked = True
                    break

            if blocked:
                status = "BLOCKED_DEPENDENCY"
                detail = {"reason": "network/http failure"}
            else:
                status, detail = evaluate_case(cid, turns[0], combined, turns=eval_turns)
            counts["executed"] += 1
            counts[status] = counts.get(status, 0) + 1
            rf.write(json.dumps({
                "run_id": run_id,
                "case_id": cid,
                "oracle_version": ORACLE_VERSION,
                "code_version": CODE_VERSION,
                "knowledge_version": KNOWLEDGE_VERSION,
                "priority": "P0" if cid in p0_ids or cid.startswith("P") else "P1",
                "data_origin": context_source,
                "lab_fallback": lab,
                "expected": sanitize(str(case.get("expected") or "")),
                "obtained": sanitize(combined),
                "assertions": detail,
                "status": status,
                "duration_ms": sum(t.get("ms") or 0 for t in turn_records),
                "turns": len(turn_records),
            }, ensure_ascii=False) + "\n")
            rf.flush()
            tf.flush()
            print(f"CASE {cid} {status} turns={len(turn_records)}", flush=True)

    ended = utc_now()
    summary_counts = (
        f"exec={counts['executed']}/{counts['selected']} "
        f"OK={counts['PASS_RESOLVED']}+clar={counts['PASS_CLARIFICATION_EXPECTED']} "
        f"partial={counts['PARTIAL_CAPABILITY']} "
        f"pending_eval={counts.get('PENDING_EVALUATION', 0)} "
        f"fail={counts['FAIL_INTERPRETATION']+counts['FAIL_RETRIEVAL']+counts['FAIL_STATE']+counts['FAIL_GROUNDING']} "
        f"blocked={counts['BLOCKED_DEPENDENCY']}"
    )
    manifest = {
        "run_id": run_id,
        "started": started,
        "ended": ended,
        "status": "COMPLETED",
        "env": env_label,
        "endpoint": args.base,
        "scope": args.scope,
        "customer_id": CUSTOMER,
        "lab_fallback": lab,
        "data_origin_policy": data_origin,
        "code_version": CODE_VERSION,
        "knowledge_version": KNOWLEDGE_VERSION,
        "oracle_version": ORACLE_VERSION,
        "package_version": KNOWLEDGE_VERSION,
        "counts": counts,
        "health": health.get("body"),
        "notes": [
            "No se indexaron evaluacion/ ni fichas_candidatas.",
            "Valores financieros saneados en evidencias.",
            "Omitidos no cuentan como aprobados.",
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resumen = [
        f"# Resumen corrida `{run_id}`",
        "",
        f"- Inicio UTC: {started}",
        f"- Fin UTC: {ended}",
        f"- Endpoint: `{args.base}`",
        f"- Alcance: {args.scope}",
        f"- lab_fallback: {lab}",
        f"- Cliente: {CUSTOMER} (lectura)",
        "",
        "## Conteos",
        "",
        "```json",
        json.dumps(counts, ensure_ascii=False, indent=2),
        "```",
        "",
        f"Resumen: {summary_counts}",
        "",
        "## Notas",
        "",
        "- Las etiquetas históricas de la guía no son oráculo.",
        "- Core vivo vs lab se registra por `context_source` en cada turno.",
        "",
    ]
    (run_dir / "resumen.md").write_text("\n".join(resumen), encoding="utf-8")
    # minimal junit
    junit_cases = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        st = row.get("status")
        ok = st in ("PASS_RESOLVED", "PASS_CLARIFICATION_EXPECTED", "PARTIAL_CAPABILITY")
        # PARTIAL is not full pass — mark as failure for strict junit functional dim
        passed = st in ("PASS_RESOLVED", "PASS_CLARIFICATION_EXPECTED")
        if passed:
            junit_cases.append(f'<testcase classname="potenciacion" name="{row["case_id"]}"/>')
        elif st == "BLOCKED_DEPENDENCY":
            junit_cases.append(
                f'<testcase classname="potenciacion" name="{row["case_id"]}"><skipped message="blocked"/></testcase>'
            )
        else:
            msg = sanitize(str(row.get("assertions") or st))
            junit_cases.append(
                f'<testcase classname="potenciacion" name="{row["case_id"]}">'
                f'<failure message="{st}">{msg}</failure></testcase>'
            )
    (run_dir / "junit.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="potenciacion_lunes" tests="{len(junit_cases)}">\n'
        + "\n".join(junit_cases)
        + "\n</testsuite>\n",
        encoding="utf-8",
    )
    cmd_log.write(f"run_id={run_id}\nscope={args.scope}\nbase={args.base}\n{summary_counts}\n")
    cmd_log.close()
    write_checksums(run_dir)
    update_index(run_id, {
        "started": started,
        "env": env_label,
        "scope": args.scope,
        "summary_counts": summary_counts,
    })
    print(json.dumps({"run_id": run_id, "counts": counts, "dir": str(run_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
