"""Convierte CSV del formato funcional a un Markdown de paquete para cognitiva.

Uso:
  python scripts/func_csv_to_markdown.py ^
    --intenciones works/formato_funcional/ejemplos/FUNC_intenciones_EJEMPLO.csv ^
    --dialogos works/formato_funcional/ejemplos/FUNC_dialogos_EJEMPLO.csv ^
    --fallos works/formato_funcional/ejemplos/FUNC_fallos_semana_EJEMPLO.csv ^
    --out works/paquetes/FUNC-EJEMPLO.md
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def _read(path: Path) -> list[dict[str, str]]:
    if not path or not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if any((v or "").strip() for v in row.values())]


def _section_intenciones(rows: list[dict[str, str]]) -> list[str]:
    lines = ["## 1. Intenciones\n"]
    for r in rows:
        lines.append(f"### `{r.get('intent_id') or 'SIN_ID'}` ({r.get('prioridad') or 'P?'})")
        lines.append(f"- **Familia/producto:** {r.get('familia')} / {r.get('producto')}")
        lines.append(f"- **En cristiano:** {r.get('pregunta_en_cristiano')}")
        lines.append(f"- **Frases:** {r.get('frases_del_cliente')}")
        lines.append(f"- **Debe:** {r.get('que_debe_responder')}")
        lines.append(f"- **No debe:** {r.get('que_NO_debe_hacer')}")
        lines.append(f"- **Si hay varias:** {r.get('si_hay_varias_opciones')}")
        lines.append(f"- **Si falta dato:** {r.get('si_falta_el_dato')}")
        lines.append(f"- **Dato sistema:** {r.get('dato_del_sistema')}")
        lines.append("")
    return lines


def _section_dialogos(rows: list[dict[str, str]]) -> list[str]:
    lines = ["## 2. Diálogos golden\n"]
    by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_id[r.get("dialogo_id") or "SIN_ID"].append(r)
    for did, turns in by_id.items():
        lines.append(f"### `{did}`")
        for t in sorted(turns, key=lambda x: int(x.get("turno") or 0)):
            lines.append(f"- **Turno {t.get('turno')}** (`{t.get('customer_id')}`)")
            lines.append(f"  - Usuario: {t.get('mensaje_usuario')}")
            lines.append(f"  - Debe: {t.get('que_debe_pasar')}")
            lines.append(f"  - No debe: {t.get('que_NO_debe_pasar')}")
            if t.get("notas"):
                lines.append(f"  - Notas: {t.get('notas')}")
        lines.append("")
    return lines


def _section_fallos(rows: list[dict[str, str]]) -> list[str]:
    lines = ["## 3. Fallos de la semana\n"]
    for r in rows:
        lines.append(f"### `{r.get('fail_id') or 'F-?'}` — {r.get('gravedad')}")
        lines.append(f"- **Fecha:** {r.get('fecha')}")
        lines.append(f"- **Usuario:** {r.get('frase_exacta_del_usuario')}")
        lines.append(f"- **Bot dijo:** {r.get('que_respondio_el_bot')}")
        lines.append(f"- **Debía:** {r.get('que_debia_responder')}")
        if r.get("comentario"):
            lines.append(f"- **Comentario:** {r.get('comentario')}")
        lines.append("")
    return lines


def main() -> int:
    p = argparse.ArgumentParser(description="CSV funcional → Markdown paquete cognitiva")
    p.add_argument("--intenciones", type=Path, default=None)
    p.add_argument("--dialogos", type=Path, default=None)
    p.add_argument("--fallos", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    lines = [
        "# Paquete funcional transformado (para cognitiva / IA)\n",
        "> Generado automáticamente desde CSV del formato funcional.\n",
    ]
    if args.intenciones:
        lines.extend(_section_intenciones(_read(args.intenciones)))
    if args.dialogos:
        lines.extend(_section_dialogos(_read(args.dialogos)))
    if args.fallos:
        lines.extend(_section_fallos(_read(args.fallos)))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"OK -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
