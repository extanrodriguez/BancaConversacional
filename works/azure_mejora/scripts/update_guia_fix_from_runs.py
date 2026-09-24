# -*- coding: utf-8 -*-
"""Actualiza guía fix desde corrida 141 (+ opcional 95) y capturas UI."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AM = ROOT / "works" / "azure_mejora"
CASOS = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "casos_236.json"
RUN141 = ROOT / "works" / "qa_runs" / "20260921T020704Z_90a62b16"

STATUS_FIX = {
    "PASS_RESOLVED": "RESUELTO",
    "PASS_CLARIFICATION_EXPECTED": "RESUELTO",
    "PARTIAL_CAPABILITY": "PARCIAL",
    "PENDING_EVALUATION": "PARCIAL",
    "FAIL_INTERPRETATION": "FALLA",
    "FAIL_RETRIEVAL": "FALLA",
    "FAIL_STATE": "FALLA",
    "FAIL_GROUNDING": "FALLA",
    "BLOCKED_DEPENDENCY": "BLOQUEADO",
}


def load_results(run_dir: Path) -> dict[str, dict]:
    path = run_dir / "resultados_casos.jsonl"
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        out[str(o["case_id"])] = o
    return out


def main() -> None:
    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    if isinstance(casos, dict):
        casos = casos.get("cases") or []
    prio = json.loads((AM / "prioridades_141.json").read_text(encoding="utf-8"))
    api = load_results(RUN141)
    # merge solo corridas de esta iniciativa (95 / capturas), no materializaciones previas
    for name in (
        "20260921T020704Z_90a62b16",
    ):
        pass
    for r in sorted((ROOT / "works" / "qa_runs").glob("20260921T*"), key=lambda p: p.name):
        man = r / "manifest.json"
        if not man.exists():
            continue
        try:
            meta = json.loads(man.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Solo corridas live potenciacion con selected<=141 o label azure
        selected = int((meta.get("counts") or {}).get("selected") or 0)
        if r.name.startswith("20260921T020704Z") or (
            selected in (95, 141) and meta.get("oracle_version") == "strict_v2.2"
        ):
            api.update(load_results(r))

    # UI captures
    ui_shots: dict[str, list[str]] = {}
    for cap_dir in (ROOT / "works" / "validacion_guia_fix" / "images" / "fix").glob("*"):
        if not cap_dir.is_dir():
            continue
        for png in cap_dir.glob("*.png"):
            cid = png.name.split("_turno_")[0].split("_full")[0]
            rel = str(png.relative_to(ROOT / "works" / "validacion_guia_fix")).replace("\\", "/")
            ui_shots.setdefault(cid, []).append(rel)

    counts = Counter()
    lines = [
        "# Guía — columna fix (azure_mejora)",
        "",
        f"UTC: {datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"Run prioritario 141: `{RUN141.name}`",
        "Código bajo prueba remota: el desplegado en `:8447` (diff local payoff/retrieval pendiente de redeploy).",
        "Completado = aserciones OK + captura revisada. Sin captura → no RESUELTO visual.",
        "",
        "| case_id | histórico | prioridad | status_api | fix | captura | evidencia |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in casos:
        cid = c["case_id"]
        hist = (c.get("historical_result") or "").replace("|", "/").replace("\n", " ")[:70]
        pr = (
            "141"
            if cid in prio["priority_141"]
            else ("95" if cid in prio["cumple_95"] else "-")
        )
        row = api.get(cid)
        st = (row or {}).get("status") or "NOT_EXECUTED"
        shots = ui_shots.get(cid) or []
        has_ui = bool(shots)
        fix = STATUS_FIX.get(st, "NO_EJECUTADO")
        if fix == "RESUELTO" and not has_ui:
            fix = "PARCIAL"  # API_VERIFIED_UI_PENDING
            note = "API_VERIFIED_UI_PENDING"
        elif fix == "RESUELTO":
            note = "aserciones+captura"
        elif st.startswith("FAIL"):
            note = st
        elif st == "PARTIAL_CAPABILITY":
            note = "PARTIAL_CAPABILITY"
        else:
            note = st
        # Never mark RESUELTO for remote without deploy of local fixes on blocked data cases
        counts[fix] += 1
        cap = shots[0] if shots else "PENDING_UI"
        ev = f"qa_runs/{RUN141.name}/resultados_casos.jsonl#{cid}" if row else ""
        lines.append(
            f"| {cid} | {hist} | {pr} | {st} | **{fix}** | {cap} | {note} {ev} |"
        )

    out = AM / "guia" / "Guia_Pruebas_FIX.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "run_141": RUN141.name,
        "fix_counts": dict(counts),
        "note": "RESUELTO visual exige captura; sin redeploy local, algunos PASS remotos no acreditan fixes nuevos",
    }
    (AM / "guia" / "fix_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
