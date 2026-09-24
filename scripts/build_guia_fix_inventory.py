#!/usr/bin/env python3
"""Inventario de IDs desde la guía MD + casos_236; reporta faltantes/duplicados."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "works" / "validacion_guia_fix" / "source" / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados.MD"
CASOS = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "casos_236.json"
OUT = ROOT / "works" / "validacion_guia_fix" / "inventario_ids.json"

ID_RE = re.compile(
    r"<td>\s*([A-Z]{1,4}\d{2}[A-Z]?)\s*</td>"
    r"|^\|\s*([A-Z]{1,4}\d{2}[A-Z]?)\s*\|"
    r"|^(?:#{1,4}\s+)?(?:Escenario|Caso|ID)\s*[:=]?\s*([A-Z]{1,4}\d{2}[A-Z]?)\b",
    re.M,
)


def main() -> None:
    text = GUIDE.read_text(encoding="utf-8", errors="replace")
    found: list[str] = []
    for m in ID_RE.finditer(text):
        cid = next(g for g in m.groups() if g)
        found.append(cid)
    # También celdas sueltas tipo >P01< en encabezados de sección
    for m in re.finditer(r"\b((?:P|L|CC|MIX|IG|TC|GR|CMP|CTX|R|X|S|A|F|M|C|T)\d{2})\b", text):
        found.append(m.group(1))

    # Deduplicar conservando orden de primera aparición en tablas HTML (más fiable)
    html_ids = re.findall(r"<td>\s*([A-Z]{1,4}\d{2})\s*</td>", text)
    guide_ordered: list[str] = []
    seen: set[str] = set()
    for cid in html_ids:
        if cid not in seen:
            seen.add(cid)
            guide_ordered.append(cid)

    casos_raw = json.loads(CASOS.read_text(encoding="utf-8"))
    casos = casos_raw if isinstance(casos_raw, list) else casos_raw.get("cases") or []
    casos_ids = [str(c.get("case_id")) for c in casos if c.get("case_id")]

    c_guide = Counter(guide_ordered)
    c_casos = Counter(casos_ids)
    dup_guide = sorted([k for k, v in c_guide.items() if v > 1])
    only_guide = sorted(set(guide_ordered) - set(casos_ids))
    only_casos = sorted(set(casos_ids) - set(guide_ordered))

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "guide_path": str(GUIDE),
        "guide_sha256": hashlib.sha256(GUIDE.read_bytes()).hexdigest(),
        "expected_236": 236,
        "guide_unique_count": len(guide_ordered),
        "casos_236_count": len(casos_ids),
        "guide_ids_ordered": guide_ordered,
        "casos_ids": casos_ids,
        "duplicates_in_guide_tables": dup_guide,
        "only_in_guide": only_guide,
        "only_in_casos_236": only_casos,
        "count_differs_from_236": len(guide_ordered) != 236 or len(casos_ids) != 236,
        "notes": (
            "Inventario reconciliado contra tablas HTML de la guía y casos_236.json. "
            "No se fuerza el conteo."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "guide_unique": len(guide_ordered),
        "casos": len(casos_ids),
        "only_guide": only_guide[:20],
        "only_casos": only_casos[:20],
        "dup_guide": dup_guide,
        "out": str(OUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
