#!/usr/bin/env python3
"""Genera Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD/.html con columna fix."""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIX_ROOT = ROOT / "works" / "validacion_guia_fix"
GUIDE = FIX_ROOT / "source" / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados.MD"
CASOS = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "casos_236.json"
RUNS = ROOT / "works" / "qa_runs"

STATUS_MAP = {
    "PASS_RESOLVED": "RESUELTO",
    "PASS_CLARIFICATION_EXPECTED": "RESUELTO",
    "PARTIAL_CAPABILITY": "PARCIAL",
    "PENDING_EVALUATION": "PARCIAL",
    "FAIL_INTERPRETATION": "FALLA",
    "FAIL_RETRIEVAL": "FALLA",
    "FAIL_STATE": "FALLA",
    "FAIL_GROUNDING": "FALLA",
    "BLOCKED_DEPENDENCY": "BLOQUEADO",
    "NOT_APPLICABLE": "NO_APLICA",
    "NOT_EXECUTED": "NO_EJECUTADO",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def map_fix_status(api_status: str | None, has_capture: bool) -> str:
    if not api_status or api_status == "NOT_EXECUTED":
        return "NO_EJECUTADO"
    base = STATUS_MAP.get(api_status, "FALLA")
    # RESUELTO exige captura real
    if base == "RESUELTO" and not has_capture:
        return "PARCIAL"  # funcional OK, evidencia visual pendiente
    return base


def fix_cell(
    case_id: str,
    hist: str,
    api: dict[str, Any] | None,
    shots: list[dict[str, Any]],
    run_id: str,
    code_version: str,
) -> str:
    has_capture = bool(shots)
    api_status = (api or {}).get("status")
    fix_st = map_fix_status(api_status, has_capture)
    if api_status in ("PASS_RESOLVED", "PASS_CLARIFICATION_EXPECTED") and has_capture:
        note = "regresión confirmada" if (hist or "").lower().startswith("cumple") and "parcial" not in (hist or "").lower() else "aserciones OK + captura QA"
    elif api_status == "PARTIAL_CAPABILITY":
        note = "cobertura parcial (facetas A/N o capacidad limitada lab_fallback)"
    elif api_status and str(api_status).startswith("FAIL"):
        note = f"sigue fallando: {api_status}"
    elif not api:
        note = "sin ejecución en esta corrida"
    else:
        note = str(api_status)
    if api_status in ("PASS_RESOLVED", "PASS_CLARIFICATION_EXPECTED") and not has_capture:
        note = "API_VERIFIED_UI_PENDING — funcional OK; falta captura /pruebas"
        fix_st = "PARCIAL"

    imgs = ""
    for s in shots:
        rel = s.get("path") or ""
        # rutas relativas desde el MD en FIX_ROOT
        imgs += f'<div class="img-row"><img class="doc-img" src="{html_lib.escape(rel)}" alt="Evidencia QA del caso {html_lib.escape(case_id)}" /></div>'

    logs = f"works/qa_runs/{run_id}/resultados_casos.jsonl#{case_id}" if run_id else ""
    return (
        f"<b>{fix_st}</b><br/>"
        f"run_id={html_lib.escape(run_id or 'n/a')}<br/>"
        f"UTC={utc_now()} · code={html_lib.escape(code_version)}<br/>"
        f"{html_lib.escape(note)}<br/>"
        f"{imgs}"
        f"<small>registros: {html_lib.escape(logs)}</small>"
    )


def inject_fix_column(md: str, cells: dict[str, str]) -> str:
    """Añade columna fix a tablas HTML que tengan ID en primera columna."""
    # Encabezado: insertar <th>fix</th> tras última th de filas de header que contengan ID
    def add_th(m: re.Match[str]) -> str:
        block = m.group(0)
        if "fix" in block.lower():
            return block
        return block + "<th>fix</th>"

    md2 = re.sub(
        r"(<tr>\s*(?:<th>[^<]*</th>\s*){3,6}</tr>)",
        add_th,
        md,
        count=0,
        flags=re.I,
    )

    def add_td(m: re.Match[str]) -> str:
        full = m.group(0)
        cid = m.group(1)
        cell = cells.get(cid, f"<b>NO_EJECUTADO</b><br/>sin datos de reejecución para {html_lib.escape(cid)}")
        if re.search(r"<td>\s*fix\s*</td>", full, re.I):
            return full
        # insertar antes de </tr>
        return full[:-5] + f"<td>{cell}</td></tr>"

    md2 = re.sub(
        r"<tr>\s*<td>\s*([A-Z]{1,4}\d{2})\s*</td>.*?</tr>",
        add_td,
        md2,
        flags=re.S,
    )
    return md2


def section_tables(md: str, cells: dict[str, str], hist: dict[str, str], api_by: dict[str, Any]) -> str:
    """Para IDs que no quedaron en tablas, anexar tablas fix al final por ID faltante."""
    present = set(re.findall(r"<td>\s*([A-Z]{1,4}\d{2})\s*</td>", md))
    missing = [cid for cid in cells if cid not in present]
    if not missing:
        return md
    extra = ["\n\n# Anexo — escenarios con tabla fix por ID\n"]
    for cid in missing:
        extra.append(f"\n## {cid}\n")
        extra.append(
            "<div class=\"table-wrap\"><table>"
            "<tr><th>ID</th><th>Resultado original</th><th>Resultado reejecución</th><th>fix</th></tr>"
            f"<tr><td>{cid}</td>"
            f"<td>{html_lib.escape((hist.get(cid) or '')[:500])}</td>"
            f"<td>{html_lib.escape(str((api_by.get(cid) or {}).get('status') or 'NO_EJECUTADO'))}</td>"
            f"<td>{cells[cid]}</td></tr></table></div>\n"
        )
    return md + "\n".join(extra)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-run", required=True, help="run_id bajo works/qa_runs")
    ap.add_argument("--ui-run", default="", help="run_id de capturas UI")
    ap.add_argument("--code-version", default="potenciacion-strict-v2.1.3")
    args = ap.parse_args()

    api_rows = load_jsonl(RUNS / args.api_run / "resultados_casos.jsonl")
    api_by = {str(r["case_id"]): r for r in api_rows if r.get("case_id")}
    mani = {}
    mp = RUNS / args.api_run / "manifest.json"
    if mp.exists():
        mani = json.loads(mp.read_text(encoding="utf-8"))

    shots_by: dict[str, list[dict[str, Any]]] = {}
    if args.ui_run:
        cap = FIX_ROOT / "qa_runs_ui" / args.ui_run / "capturas.jsonl"
        for row in load_jsonl(cap):
            shots_by[str(row["case_id"])] = row.get("screenshots") or []
        # también escanear carpeta images/fix
        img_dir = FIX_ROOT / "images" / "fix" / args.ui_run
        if img_dir.exists():
            for p in sorted(img_dir.glob("*.png")):
                cid = p.name.split("_turno_")[0].split("_full")[0]
                rel = f"images/fix/{args.ui_run}/{p.name}"
                shots_by.setdefault(cid, [])
                if not any(s.get("path") == rel for s in shots_by[cid]):
                    shots_by[cid].append({"path": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})

    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    if isinstance(casos, dict):
        casos = casos.get("cases") or []
    hist = {str(c["case_id"]): str(c.get("historical_result") or "") for c in casos}
    all_ids = [str(c["case_id"]) for c in casos]

    cells: dict[str, str] = {}
    for cid in all_ids:
        cells[cid] = fix_cell(
            cid,
            hist.get(cid, ""),
            api_by.get(cid),
            shots_by.get(cid, []),
            args.api_run,
            args.code_version,
        )

    md = GUIDE.read_text(encoding="utf-8", errors="replace")
    md_fix = inject_fix_column(md, cells)
    md_fix = section_tables(md_fix, cells, hist, api_by)

    header = (
        f"\n\n---\n\n# Informe FIX (columna `fix`)\n\n"
        f"- Generado UTC: {utc_now()}\n"
        f"- API run: `{args.api_run}`\n"
        f"- UI run: `{args.ui_run or 'n/a'}`\n"
        f"- code_version: `{args.code_version}`\n"
        f"- oracle: `{(mani.get('oracle_version') if mani else None) or 'strict_v2.1'}`\n"
        f"- Cliente QA: 726588 · lab_fallback\n"
        f"- Imágenes históricas: `images/img_XXXX.png` · nuevas: `images/fix/...`\n\n"
        f"**Leyenda fix:** RESUELTO requiere aserciones + captura real `/pruebas`. "
        f"PARCIAL puede ser capacidad limitada o API_VERIFIED_UI_PENDING.\n\n---\n\n"
    )
    out_md = FIX_ROOT / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD"
    out_md.write_text(header + md_fix, encoding="utf-8")

    # HTML navegable
    html_body = header + md_fix
    # ya contiene HTML de tablas; envolver
    html_doc = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"/>
<title>Guía FIX — Banca Conversacional BSC</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1200px}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}
th,td{{border:1px solid #ccc;padding:8px;vertical-align:top}}
th{{background:#0d2149;color:#fff}}
.doc-img{{max-width:220px;height:auto;display:block;margin:6px 0;border:1px solid #ddd}}
.img-row{{display:flex;flex-wrap:wrap;gap:6px}}
.table-wrap{{overflow-x:auto}}
</style></head><body>
{html_body}
</body></html>"""
    out_html = FIX_ROOT / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.html"
    out_html.write_text(html_doc, encoding="utf-8")

    # Matriz aceptación
    counts: dict[str, int] = {}
    matrix = []
    for cid in all_ids:
        api = api_by.get(cid)
        st = map_fix_status((api or {}).get("status"), bool(shots_by.get(cid)))
        if (api or {}).get("status") in ("PASS_RESOLVED", "PASS_CLARIFICATION_EXPECTED") and not shots_by.get(cid):
            st = "PARCIAL"
        counts[st] = counts.get(st, 0) + 1
        matrix.append({
            "case_id": cid,
            "historical": hist.get(cid, "")[:200],
            "api_status": (api or {}).get("status") or "NOT_EXECUTED",
            "fix_status": st,
            "has_capture": bool(shots_by.get(cid)),
            "shots": shots_by.get(cid) or [],
        })
    (FIX_ROOT / "matriz_aceptacion.json").write_text(
        json.dumps({"counts": counts, "cases": matrix, "api_run": args.api_run, "ui_run": args.ui_run}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"out_md": str(out_md), "out_html": str(out_html), "counts": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
