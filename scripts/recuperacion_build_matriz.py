#!/usr/bin/env python3
"""Construye inventario histórico de capacidades desde runs QA + guía FIX."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "works" / "recuperacion_integral"
CASOS = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "casos_236.json"
FIX_MD = ROOT / "works" / "validacion_guia_fix" / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD"
RUNS = ROOT / "works" / "qa_runs"

PASSISH = ("PASS", "PASS_RESOLVED", "PASS_CLARIFICATION_EXPECTED", "PARTIAL_CAPABILITY", "API_VERIFIED_UI_PENDING")


def load_cases() -> list[dict]:
    raw = json.loads(CASOS.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("cases") or raw.get("items") or []
    return raw


def parse_fix_column(md: str) -> dict[str, str]:
    """Best-effort: map case_id -> fix status from FIX guide tables."""
    out: dict[str, str] = {}
    # rows like | CMP01 | ... | RESUELTO |
    for m in re.finditer(
        r"\|\s*([A-Z]{1,5}\d{2}[A-Z]?)\s*\|(?:[^|\n]*\|){1,12}\s*(RESUELTO|PARCIAL|FALLA|PENDING[^|\n]*)\s*\|",
        md,
        flags=re.I,
    ):
        out[m.group(1)] = m.group(2).strip().upper()
    return out


def iter_run_results():
    for d in sorted(RUNS.glob("*")):
        rj = d / "resultados_casos.jsonl"
        if not rj.is_file():
            continue
        # skip partial helpers
        if d.name.startswith("_") or "reeval" in d.name and "materialized" in d.name:
            pass
        try:
            rows = [json.loads(l) for l in rj.read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception:
            continue
        if not rows:
            continue
        yield d.name, rows


def best_accredited(case_id: str, history: list[tuple[str, str, dict]]) -> dict | None:
    """Última evidencia histórica de acreditación (PASSISH), si existe."""
    for run_id, status, row in reversed(history):
        if status.startswith("PASS") or status == "PARTIAL_CAPABILITY":
            return {"run_id": run_id, "status": status, "duration_ms": row.get("duration_ms")}
    return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    case_ids = [c.get("case_id") for c in cases if c.get("case_id")]
    by_case_meta = {c["case_id"]: c for c in cases if c.get("case_id")}

    fix_map = {}
    if FIX_MD.is_file():
        fix_map = parse_fix_column(FIX_MD.read_text(encoding="utf-8", errors="replace"))

    hist: dict[str, list] = defaultdict(list)
    run_summaries = []
    for run_id, rows in iter_run_results():
        ctr = Counter(r.get("status") for r in rows)
        run_summaries.append({"run_id": run_id, "n": len(rows), "counts": dict(ctr)})
        for r in rows:
            cid = r.get("case_id")
            if not cid:
                continue
            hist[cid].append((run_id, str(r.get("status") or ""), r))

    # Prefer full-ish runs chronologically (directory name starts with date)
    # Latest complete-ish for "current" proxy: largest recent with >=200 cases if any
    recent_full = None
    for run_id, rows in sorted(iter_run_results(), key=lambda x: x[0], reverse=True):
        if len(rows) >= 200:
            recent_full = (run_id, {r["case_id"]: r for r in rows if r.get("case_id")})
            break
    # also take deploy_fix_merged if present
    merged = RUNS / "20260921T130100Z_deploy_fix_merged" / "resultados_casos.jsonl"
    current_proxy = None
    if merged.is_file():
        rows = [json.loads(l) for l in merged.read_text(encoding="utf-8").splitlines() if l.strip()]
        current_proxy = ("20260921T130100Z_deploy_fix_merged", {r["case_id"]: r for r in rows if r.get("case_id")})
    elif recent_full:
        current_proxy = recent_full

    matrix = []
    class_ctr = Counter()
    for cid in case_ids:
        meta = by_case_meta.get(cid) or {}
        history = hist.get(cid) or []
        accredited = best_accredited(cid, history)
        cur = None
        if current_proxy:
            cur_row = current_proxy[1].get(cid)
            if cur_row:
                cur = {"run_id": current_proxy[0], "status": cur_row.get("status")}

        fix_st = fix_map.get(cid)

        # Classification (conservative — evidence based)
        classification = "E"  # PENDIENTE_DE_EVIDENCIA
        if accredited and cur:
            a_ok = str(accredited["status"]).startswith("PASS") or accredited["status"] == "PARTIAL_CAPABILITY"
            c_fail = str(cur["status"]).startswith("FAIL") or cur["status"] in (
                "BLOCKED_DEPENDENCY",
                "PROVIDER_ERROR",
            )
            c_ok = str(cur["status"]).startswith("PASS") or cur["status"] == "PARTIAL_CAPABILITY"
            if a_ok and c_fail:
                classification = "A"  # REGRESION_CONFIRMADA (histórica en runs; falta smoke live)
            elif a_ok and c_ok:
                classification = "B_STABLE_IN_RUNS"  # provisional label → map later
            elif not a_ok and c_fail:
                classification = "B"  # FALLO_PREEXISTENTE
            else:
                classification = "E"
        elif accredited and not cur:
            classification = "E"
        elif not accredited:
            classification = "B" if (cur and str(cur.get("status", "")).startswith("FAIL")) else "E"

        # Override hint from FIX column RESUELTO historically accredited in UI pack
        if fix_st == "RESUELTO" and cur and str(cur.get("status", "")).startswith("FAIL"):
            classification = "A"
            evidence_note = "FIX guía marcó RESUELTO; run proxy actual FAIL"
        else:
            evidence_note = ""

        label = {
            "A": "REGRESION_CONFIRMADA",
            "B": "FALLO_PREEXISTENTE",
            "C": "DIFERENCIA_DE_ENTORNO_O_DATOS",
            "D": "CAMBIO_DE_ORACULO",
            "E": "PENDIENTE_DE_EVIDENCIA",
            "B_STABLE_IN_RUNS": "ESTABLE_EN_RUNS_HISTORICOS",
        }.get(classification, classification)
        class_ctr[label] += 1

        matrix.append(
            {
                "case_id": cid,
                "expected_hint": (meta.get("expected") or meta.get("acceptance") or "")[:180],
                "priority": meta.get("priority"),
                "fix_guide_status": fix_st,
                "last_accredited": accredited,
                "current_proxy": cur,
                "classification": label,
                "evidence_note": evidence_note,
                "history_n": len(history),
                "history_statuses": Counter(s for _, s, _ in history),
                "component": None,
                "fix": None,
                "recovery_evidence": None,
            }
        )

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(matrix),
        "current_proxy_run": current_proxy[0] if current_proxy else None,
        "classification_counts": dict(class_ctr),
        "note": (
            "Clasificación A basada en runs históricos PASS/PARTIAL vs proxy actual FAIL. "
            "NO equivale a revalidación live QA 726588. "
            "Requiere smoke/regresión live para confirmar A."
        ),
        "matrix": matrix,
        "run_summaries_top": sorted(run_summaries, key=lambda x: x["run_id"], reverse=True)[:25],
    }
    (OUT / "MATRIZ_RECUPERACION_CAPACIDADES.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # Markdown resumen
    md = [
        "# MATRIZ_RECUPERACION_CAPACIDADES",
        "",
        f"Generado: {payload['generated_utc']}",
        "",
        f"Casos inventariados: **{payload['n_cases']}**",
        f"Proxy resultado actual (runs): `{payload['current_proxy_run']}`",
        "",
        "## Conteos de clasificación (preliminar por evidencia de runs)",
        "",
        "| Clase | N |",
        "|---|---|",
    ]
    for k, v in sorted(class_ctr.items(), key=lambda x: -x[1]):
        md.append(f"| {k} | {v} |")
    md += [
        "",
        "## Nota metodológica",
        "",
        payload["note"],
        "",
        "Detalle JSON: `MATRIZ_RECUPERACION_CAPACIDADES.json`",
        "",
        "## Muestra REGRESION_CONFIRMADA (hasta 40)",
        "",
        "| case_id | última acreditación | proxy actual | fix guía |",
        "|---|---|---|---|",
    ]
    regs = [m for m in matrix if m["classification"] == "REGRESION_CONFIRMADA"][:40]
    for m in regs:
        la = m["last_accredited"] or {}
        cu = m["current_proxy"] or {}
        md.append(
            f"| {m['case_id']} | {la.get('status')} @ `{la.get('run_id','')}` | {cu.get('status')} | {m.get('fix_guide_status') or ''} |"
        )
    (OUT / "MATRIZ_RECUPERACION_CAPACIDADES.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"n": len(matrix), "counts": dict(class_ctr), "proxy": payload["current_proxy_run"], "reg_sample": len(regs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
