#!/usr/bin/env python3
"""Empaqueta VALIDACION_GUIA_BSC_FIX_<fecha>.zip con evidencias."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "works" / "validacion_guia_fix"
RUNS = ROOT / "works" / "qa_runs"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-run", required=True)
    ap.add_argument("--ui-run", default="")
    ap.add_argument("--out-dir", default=str(FIX))
    args = ap.parse_args()
    fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
    zip_path = Path(args.out_dir) / f"VALIDACION_GUIA_BSC_FIX_{fecha}.zip"

    # Ensure report exists
    md = FIX / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD"
    html = FIX / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.html"
    if not md.exists():
        raise SystemExit("Falta guía FIX; ejecuta build_guia_fix_report.py primero")

    matriz = FIX / "matriz_aceptacion.json"
    counts = {}
    if matriz.exists():
        counts = json.loads(matriz.read_text(encoding="utf-8")).get("counts") or {}

    leeme = FIX / "LEEME_ABRIR_INFORME.md"
    leeme.write_text(
        f"""# Cómo abrir el informe FIX

1. Extraer este ZIP completo (conservar estructura de carpetas).
2. Abrir `Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.html` en el navegador.
3. La columna **fix** está al final de cada fila de escenario.
4. Imágenes históricas: `images/img_XXXX.png` (ZIP guía original).
5. Capturas nuevas: `images/fix/<run_id>/…`.
6. Registros API: `qa_runs_api/<run_id>/`.
7. Hash del ZIP fuente original: ver `source_zip_checksum.json`.

API run: `{args.api_run}`  
UI run: `{args.ui_run or 'n/a'}`  
Conteos fix: `{json.dumps(counts, ensure_ascii=False)}`
""",
        encoding="utf-8",
    )

    # Copy API run into package tree
    api_dst = FIX / "qa_runs_api" / args.api_run
    api_src = RUNS / args.api_run
    if api_src.exists():
        if api_dst.exists():
            shutil.rmtree(api_dst)
        shutil.copytree(api_src, api_dst, ignore=shutil.ignore_patterns("evidencias"))

    # Manifest hashes
    hash_lines = []
    for p in sorted(FIX.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".md", ".html", ".json", ".jsonl", ".png", ".sha256"}:
            try:
                rel = p.relative_to(FIX).as_posix()
                hash_lines.append(f"{sha256(p)}  {rel}")
            except Exception:
                pass
    (FIX / "MANIFESTO_HASHES.sha256").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in FIX.rglob("*"):
            if not p.is_file():
                continue
            # skip previous zips
            if p.suffix.lower() == ".zip":
                continue
            # skip junction duplication of huge images if linked from downloads - include them
            rel = p.relative_to(FIX).as_posix()
            zf.write(p, rel)

    print(json.dumps({"zip": str(zip_path), "bytes": zip_path.stat().st_size, "counts": counts}, indent=2))


if __name__ == "__main__":
    main()
