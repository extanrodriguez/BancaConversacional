# -*- coding: utf-8 -*-
"""Inicializa guía con columna fix (NOT_EXECUTED/PENDING_UI) desde original + casos_236."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AM = ROOT / "works" / "azure_mejora"
CASOS = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "casos_236.json"
OUT = AM / "guia" / "Guia_con_fix_SEED.MD"

casos = json.loads(CASOS.read_text(encoding="utf-8"))
if isinstance(casos, dict):
    casos = casos.get("cases") or []
prio = json.loads((AM / "prioridades_141.json").read_text(encoding="utf-8"))
priority = set(prio["priority_141"])
cumple = set(prio["cumple_95"])

lines = [
    "# Guía derivada — columna fix (semilla)",
    "",
    f"Generado UTC: {datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    "Histórico conservado. Nueva evidencia empieza NOT_EXECUTED / PENDING_UI.",
    "Completado solo con aserciones verificadas + captura real revisada.",
    "",
    "| case_id | histórico | prioridad | fix | captura |",
    "|---|---|---|---|---|",
]
for c in casos:
    cid = c["case_id"]
    hist = (c.get("historical_result") or "").replace("|", "/").replace("\n", " ")[:80]
    pr = "141_fallo_parcial" if cid in priority else ("regresion_95" if cid in cumple else "otro")
    lines.append(f"| {cid} | {hist} | {pr} | NOT_EXECUTED | PENDING_UI |")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", OUT, "rows", len(casos))
