# -*- coding: utf-8 -*-
"""Empaqueta entrega strict-v2.2 y publica SHA256 fuera del ZIP."""
from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
zip_path = ROOT / "works" / "qa_runs" / f"EVIDENCIAS_STRICT_V22_CONTINUACION_{stamp}.zip"
hash_path = ROOT / "works" / "qa_runs" / f"EVIDENCIAS_STRICT_V22_CONTINUACION_{stamp}.sha256"

include = [
    ROOT / "works" / "ENTREGA_STRICT_V22_CONTINUACION.md",
    ROOT / "works" / "qa_runs" / "RECORRIDOS_CAPTURA_UI_PENDIENTES.md",
    ROOT / "works" / "qa_runs" / "_v22_fail_taxonomy.json",
    ROOT / "works" / "qa_runs" / "20260921T004314Z_strict_v22_oracle_guide",
    ROOT / "works" / "qa_runs" / "reeval_strict_v2.2_20260920T203909Z_d83c1c54",
    ROOT / "works" / "qa_runs" / "reeval_strict_v2.2_20260920T201855Z_c6702543",
    ROOT / "works" / "validacion_guia_fix" / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD",
    ROOT / "works" / "validacion_guia_fix" / "Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.html",
    ROOT / "works" / "validacion_guia_fix" / "RESUMEN_VALIDACION.md",
    ROOT / "works" / "validacion_guia_fix" / "qa_runs_ui" / "20260921T004500Z_chrome_p0fix",
    ROOT / "works" / "validacion_guia_fix" / "images" / "fix" / "20260921T004500Z_chrome_p0fix",
    ROOT / "works" / "qa_runs" / "guia_columna_fix.md",
]

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for item in include:
        if not item.exists():
            continue
        if item.is_file():
            zf.write(item, item.relative_to(ROOT).as_posix())
        else:
            for p in item.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(ROOT).as_posix())

h = hashlib.sha256()
with zip_path.open("rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        h.update(chunk)
digest = h.hexdigest().upper()
hash_path.write_text(
    f"{digest}  {zip_path.name}\n"
    f"# Publicado FUERA del ZIP para evitar autorreferencia.\n"
    f"# generated_utc={stamp}\n",
    encoding="utf-8",
)
# También en el informe (fuera del zip)
informe = ROOT / "works" / "ENTREGA_STRICT_V22_CONTINUACION.md"
txt = informe.read_text(encoding="utf-8")
if "SHA256 del ZIP" not in txt:
    informe.write_text(
        txt
        + f"\n## Hash del ZIP (fuera del archivo)\n\n"
        + f"- ZIP: `{zip_path.relative_to(ROOT).as_posix()}`\n"
        + f"- SHA256: `{digest}`\n"
        + f"- Archivo hash: `{hash_path.relative_to(ROOT).as_posix()}`\n",
        encoding="utf-8",
    )
print(zip_path)
print(digest)
print(hash_path)
