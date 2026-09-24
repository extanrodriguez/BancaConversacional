#!/usr/bin/env python3
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src_reeval = ROOT / "works/qa_runs/reeval_strict_v2.2_20260920T165755Z_3e71ec52"
src_turns = ROOT / "works/qa_runs/20260920T165755Z_3e71ec52"
out = ROOT / "works/qa_runs/20260920T202000Z_reeval236_materialized"
out.mkdir(parents=True, exist_ok=True)

rows = [
    json.loads(l)
    for l in (src_reeval / "reeval_resultados.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]
shutil.copy2(src_turns / "turnos.jsonl", out / "turnos.jsonl")
lines = []
for r in rows:
    lines.append(
        json.dumps(
            {
                "run_id": out.name,
                "case_id": r["case_id"],
                "oracle_version": "strict_v2.2",
                "code_version": "potenciacion-strict-v2.2",
                "knowledge_version": "bsc-kb-2026-09-19-candidate-1",
                "status": r["status"],
                "assertions": r.get("assertions"),
                "previous_status": r.get("previous_status"),
                "data_origin": "lab_fallback_reeval",
                "lab_fallback": True,
                "note": (
                    "Reevaluación strict_v2.2 sobre turnos de "
                    "20260920T165755Z_3e71ec52."
                ),
            },
            ensure_ascii=False,
        )
    )
(out / "resultados_casos.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
counts = dict(Counter(r["status"] for r in rows))
(out / "manifest.json").write_text(
    json.dumps(
        {
            "run_id": out.name,
            "source": "reeval_strict_v2.2_20260920T165755Z_3e71ec52",
            "oracle_version": "strict_v2.2",
            "scope": "all",
            "executed": len(rows),
            "counts": counts,
        },
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(out / "resumen.md").write_text(
    "# Reeval materializado\n\n"
    "Fuente turnos: `20260920T165755Z_3e71ec52`\n"
    "Oráculo: `strict_v2.2`\n\n"
    f"Conteos: `{counts}`\n",
    encoding="utf-8",
)
print(out.name, len(rows), counts)
