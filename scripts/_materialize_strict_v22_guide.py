# -*- coding: utf-8 -*-
"""Materializa resultados de reevaluación canónica v2.2 (oráculos guía + P12 estricto)."""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_RUN = ROOT / "works/qa_runs/20260920T203909Z_d83c1c54"
REEVAL = ROOT / "works/qa_runs/reeval_strict_v2.2_20260920T203909Z_d83c1c54"
OUT_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_strict_v22_oracle_guide"
OUT = ROOT / "works/qa_runs" / OUT_ID
OUT.mkdir(parents=True, exist_ok=True)

reeval = {
    json.loads(l)["case_id"]: json.loads(l)
    for l in (REEVAL / "reeval_resultados.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
}
counts: Counter[str] = Counter()
lines = []
for line in (SRC_RUN / "resultados_casos.jsonl").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    old = json.loads(line)
    cid = old["case_id"]
    rv = reeval.get(cid) or {}
    status = rv.get("status") or old.get("status")
    counts[status] += 1
    row = dict(old)
    row["status"] = status
    row["assertions"] = rv.get("assertions") or old.get("assertions")
    row["oracle_version"] = "strict_v2.2"
    row["code_version"] = "potenciacion-strict-v2.2"
    row["reeval_source"] = REEVAL.name
    row["previous_status"] = rv.get("previous_status") or old.get("status")
    lines.append(json.dumps(row, ensure_ascii=False))

(OUT / "resultados_casos.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
if (SRC_RUN / "turnos.jsonl").exists():
    shutil.copy2(SRC_RUN / "turnos.jsonl", OUT / "turnos.jsonl")
manifest = {
    "run_id": OUT_ID,
    "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "oracle_version": "strict_v2.2",
    "code_version": "potenciacion-strict-v2.2",
    "source_run": SRC_RUN.name,
    "reeval": REEVAL.name,
    "customer_id": "726588",
    "counts": dict(counts),
    "note": "Materialización canónica: histórico intacto + oráculos guía v2.2; P12/L09/MIX10 parciales hasta redeploy con ventana/audit.",
}
(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
md = [
    f"# Run materializado `{OUT_ID}`",
    "",
    f"- Fuente turnos: `{SRC_RUN.name}`",
    f"- Reevaluación: `{REEVAL.name}`",
    f"- Conteos: `{json.dumps(dict(counts), ensure_ascii=False)}`",
    "",
]
(OUT / "resumen.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print(OUT_ID)
print(dict(counts))
