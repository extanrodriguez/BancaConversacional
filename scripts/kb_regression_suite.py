#!/usr/bin/env python3
"""Batería de regresión KB (Excel VF01 / FAQ) con variantes de pregunta.

Uso:
  .venv/Scripts/python.exe scripts/kb_regression_suite.py
  .venv/Scripts/python.exe scripts/kb_regression_suite.py --limit 50
  .venv/Scripts/python.exe scripts/kb_regression_suite.py --remote http://20.127.25.24:8447

Evalúa FAQ local (rápido) y opcionalmente /inspect remoto.
Genera: Test_local/reports/kb_regression_*.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from genesis_cognitive.learning.feedback_store import FeedbackEvent, record_feedback
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache, load_faq_entries


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    stop = {"de", "del", "la", "el", "los", "las", "un", "una", "y", "o", "en", "a", "al", "que", "es", "por", "con", "para", "se", "su", "sus", "mi", "mis"}
    return {t for t in _norm(s).split() if len(t) > 2 and t not in stop}


def overlap_score(expected: str, got: str) -> float:
    e, g = _tokens(expected), _tokens(got)
    if not e or not g:
        return 0.0
    return len(e & g) / max(len(e), 1)


def variants_for(expr: str, topic: str) -> list[str]:
    """Distintos modos de preguntar el mismo escenario KB."""
    base = (expr or "").strip()
    topic = (topic or "").strip()
    out: list[str] = []
    if base:
        out.append(base)
        # sin signos
        out.append(re.sub(r"[¿?¡!]", "", base).strip())
    t = topic or base
    if t and len(t) < 80:
        out.extend(
            [
                f"qué es {t}",
                f"que es {t}",
                f"explicame {t}",
                f"dime qué significa {t}",
                f"hablame de {t}",
                f"información sobre {t}",
            ]
        )
    # únicos preservando orden
    seen: set[str] = set()
    uniq: list[str] = []
    for q in out:
        qn = _norm(q)
        if q and qn and qn not in seen:
            seen.add(qn)
            uniq.append(q)
    return uniq


def load_kb_cases() -> list[dict]:
    from genesis_cognitive.router.faq_guardrail import _default_faq_path

    entries = load_faq_entries(_default_faq_path())
    # Escenarios de matriz de prueba / personales: no son glosario FAQ
    skip_ids = {
        "vf01-r325", "vf01-r328", "vf01-r329", "vf01-r330",
        "vf01-r333", "vf01-r335", "vf01-r337", "vf01-r338",
        "vf01-r341", "vf01-r344",
    }
    skip_topic_bits = (
        "intencion no identificable",
        "información no disponible",
        "informacion no disponible",
        "potencialmente desactualizada",
        "groseria",
        "prompt injection",
        "jailbreak",
    )
    cases = []
    for e in entries:
        eid = str(e.get("id") or "")
        if eid in skip_ids:
            continue
        topic_n = _norm(e.get("topic") or "")
        if any(b in topic_n for b in skip_topic_bits):
            continue
        intent_n = _norm(e.get("intent") or "")
        # Datos personales del portafolio → Cognitiva, no FAQ
        if any(
            s in intent_n
            for s in (
                "consultar saldo",
                "consultar dato personal",
                "portafolio personal",
                "manejar groseria",
                "manejar inyeccion",
            )
        ):
            continue
        ans = (e.get("answer") or "").strip()
        if len(ans) < 40:
            continue
        # saltar placeholders de matriz
        if "basada exclusivamente en el contexto aprobado" in ans.lower():
            continue
        exprs = list(e.get("expressions") or [])
        if not exprs and e.get("topic"):
            exprs = [f"qué es {e.get('topic')}"]
        # Expresiones contaminadas del Excel (mismo texto genérico en muchos topics)
        polluted = {
            _norm("Cuéntame sobre 4.2.5. Usa la tarjeta de manera responsable"),
            _norm("¿Qué información tienes sobre 4.2.5. Usa la tarjeta de manera responsable?"),
            _norm("Explícame 4.2.5. Usa la tarjeta de manera responsable"),
        }
        topic_n = _norm(e.get("topic") or "")
        exprs = [
            x
            for x in exprs
            if _norm(x) not in polluted
            or any(k in topic_n for k in ("responsable", "uso del credito", "formas y canales"))
        ]
        # Expresión de cancelación pegada a topic de seguridad/robo (basura Excel)
        cleaned = []
        for x in exprs:
            xn = _norm(x)
            if "cancelo" in xn or "cancelar" in xn:
                if any(k in topic_n for k in ("perdida", "robo", "compromiso", "seguridad")):
                    continue
                if "general" in xn and "cancelacion de productos" in topic_n:
                    # Reescribir a frase usable
                    cleaned.append("cómo cancelo un producto")
                    continue
            cleaned.append(x)
        exprs = cleaned or ([f"qué es {e.get('topic')}"] if e.get("topic") else [])
        if not exprs:
            continue
        cases.append(
            {
                "id": e.get("id"),
                "topic": e.get("topic"),
                "product": e.get("product"),
                "intent": e.get("intent"),
                "expressions": exprs,
                "answer": ans,
            }
        )
    return cases


def eval_local(cases: list[dict], *, max_variants: int, limit: int | None) -> dict:
    clear_faq_cache()
    results = []
    fail = []
    n = 0
    for case in cases:
        if limit is not None and n >= limit:
            break
        qs = []
        for ex in case["expressions"]:
            qs.extend(variants_for(ex, case.get("topic") or ""))
        # acotar variantes por caso
        qs = qs[:max_variants]
        for q in qs:
            if limit is not None and n >= limit:
                break
            n += 1
            gr = apply_faq_guardrail(None, q, None)
            got = (gr[2] if gr else "") or ""
            score = overlap_score(case["answer"], got)
            hit_id = None
            if gr and gr[1]:
                hit_id = (gr[1][0].get("detected_entities") or {}).get("knowledge_topic")
            topic_ok = False
            if hit_id and case.get("topic"):
                topic_ok = overlap_score(str(case["topic"]), str(hit_id)) >= 0.5
            row = {
                "case_id": case["id"],
                "topic": case["topic"],
                "question": q,
                "ok": bool(got) and (score >= 0.18 or topic_ok),
                "score": round(score, 3),
                "matched_topic": hit_id,
                "reply_preview": got[:180].replace("\n", " "),
            }
            # Fallos duros: vacío, saludo, o topic Cliente cuando preguntan responsabilidad
            low_q = _norm(q)
            low_g = _norm(got)
            if not got or low_g.startswith("hola"):
                row["ok"] = False
                row["reason"] = "empty_or_greeting"
            elif "responsabilidad del banco" in low_q and "como cliente" in low_g[:80]:
                row["ok"] = False
                row["reason"] = "bank_vs_client_swap"
            elif score < 0.12 and got:
                row["ok"] = False
                row["reason"] = "low_overlap"
            results.append(row)
            if not row["ok"]:
                fail.append(row)
            try:
                record_feedback(
                    FeedbackEvent(
                        question=q,
                        matched_id=str(case["id"]) if row["ok"] else (hit_id or None),
                        matched_topic=hit_id or case.get("topic"),
                        score=float(row["score"]),
                        ok=bool(row["ok"]),
                        corrected_id=str(case["id"]) if not row["ok"] else None,
                        source="kb_regression_local",
                        meta={"reason": row.get("reason"), "case_id": case["id"]},
                    )
                )
            except Exception:
                pass
    passed = sum(1 for r in results if r["ok"])
    return {
        "mode": "local_faq",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / max(len(results), 1), 4),
        "failures": fail[:200],
        "results": results,
    }


def eval_remote(cases: list[dict], base_url: str, *, max_variants: int, limit: int | None) -> dict:
    results = []
    fail = []
    n = 0
    for case in cases:
        if limit is not None and n >= limit:
            break
        qs = []
        for ex in case["expressions"][:2]:
            qs.extend(variants_for(ex, case.get("topic") or "")[:3])
        qs = qs[:max_variants]
        for q in qs:
            if limit is not None and n >= limit:
                break
            n += 1
            body = json.dumps(
                {
                    "question": q,
                    "conversation_id": f"kbreg-{case['id']}-{n}",
                    "customer_id": "CUST001",
                }
            ).encode()
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/inspect",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode())
                got = (data.get("client_response") or "").strip()
                rag = data.get("rag_status")
            except Exception as exc:
                got = ""
                rag = f"ERROR:{exc}"
            score = overlap_score(case["answer"], got)
            row = {
                "case_id": case["id"],
                "topic": case["topic"],
                "question": q,
                "ok": bool(got) and score >= 0.15 and "cognitive_turn_failed" not in got.lower(),
                "score": round(score, 3),
                "rag_status": rag,
                "reply_preview": got[:180].replace("\n", " "),
            }
            if not row["ok"]:
                fail.append(row)
            results.append(row)
            time.sleep(0.05)
    passed = sum(1 for r in results if r["ok"])
    return {
        "mode": "remote_inspect",
        "base_url": base_url,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / max(len(results), 1), 4),
        "failures": fail[:200],
        "results": results,
    }


def failure_clusters(failures: list[dict]) -> list[dict]:
    by_case: dict[str, list] = {}
    for f in failures:
        by_case.setdefault(str(f.get("case_id")), []).append(f)
    clusters = []
    for cid, items in sorted(by_case.items(), key=lambda x: -len(x[1])):
        clusters.append(
            {
                "case_id": cid,
                "topic": items[0].get("topic"),
                "fail_count": len(items),
                "sample_q": items[0].get("question"),
                "sample_reply": items[0].get("reply_preview"),
                "reason": items[0].get("reason"),
            }
        )
    return clusters[:40]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Máx. preguntas (variantes)")
    ap.add_argument("--max-variants", type=int, default=4)
    ap.add_argument("--remote", type=str, default="", help="Base URL 8447 para /inspect")
    ap.add_argument("--remote-limit", type=int, default=40)
    args = ap.parse_args()

    cases = load_kb_cases()
    print(f"Casos KB con respuesta: {len(cases)}")
    local = eval_local(cases, max_variants=args.max_variants, limit=args.limit)
    print(
        f"LOCAL FAQ: {local['passed']}/{local['total']} "
        f"({local['pass_rate']*100:.1f}%) fallos={local['failed']}"
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases),
        "local": {
            k: local[k]
            for k in ("mode", "total", "passed", "failed", "pass_rate", "failures")
        },
        "local_clusters": failure_clusters(local["failures"]),
    }
    if args.remote:
        remote = eval_remote(
            cases,
            args.remote,
            max_variants=min(2, args.max_variants),
            limit=args.remote_limit,
        )
        print(
            f"REMOTE: {remote['passed']}/{remote['total']} "
            f"({remote['pass_rate']*100:.1f}%) fallos={remote['failed']}"
        )
        report["remote"] = {
            k: remote[k]
            for k in ("mode", "base_url", "total", "passed", "failed", "pass_rate", "failures")
        }
        report["remote_clusters"] = failure_clusters(remote["failures"])

    out_dir = ROOT / "Test_local" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"kb_regression_{stamp}.json"
    # no guardar todos los results (pesado); sí failures + clusters
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out}")
    print("Top clusters locales:")
    for c in report["local_clusters"][:12]:
        print(f"  - {c['case_id']} ({c['fail_count']}x) {c['topic']}: {c['sample_q'][:60]}")
    return 0 if local["pass_rate"] >= 0.7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
