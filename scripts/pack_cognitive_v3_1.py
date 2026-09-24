"""Empaqueta la capa cognitiva V3.1 sin secretos ni backend externo."""

from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "works" / f"BancaConversacional_Cognitivo_V3_1_{datetime.now(timezone.utc).strftime('%Y%m%d')}.zip"

INCLUDE_DIRS = [
    "src/genesis_cognitive",
    "schemas",
    "data",
    "tests/unit",
]

INCLUDE_FILES = [
    "pyproject.toml",
    "README.md",
    "works/ENTREGA_CIERRE_COGNITIVO_V3_1.md",
    "works/ENTREGA_MEJORA_COGNITIVA_V3.md",
    "works/ENTREGA_CORRECCION_AUDITADA_V3_1.md",
    "works/DOC_PLAN_INTERPRETER_V3_1.md",
    "works/MATRIZ_COBERTURA_CIERRE_V3_1.json",
    "works/RESULTADOS_CASOS_ADICIONALES_V3.json",
    "works/VINCULACION_9_CASOS_APROBADOS_V3_1.json",
    "works/MANIFEST_SHA256_CIERRE_V3_1.json",
    "works/PACK_COGNITIVE_V3_1_NOTES.md",
    "works/Banca_Cierre_V3_1/Prompt_Cursor_Cierre_V3_1.md",
    "works/Banca_Cierre_V3_1/insumos/Casos_QA_236_Extraidos.jsonl",
    "works/Banca_Cierre_V3_1/insumos/Casos_QA_Adicionales_V3.jsonl",
    "works/Banca_Cierre_V3_1/insumos/Resumen_QA.json",
    "works/Banca_Cierre_V3_1/insumos/Modelo_Mejora_Cognitiva_QA_V3.md",
    "works/Banca_Cierre_V3_1/insumos/Prompt_Cursor_Banca_V3_Pruebas_QA.md",
]

EXCLUDE_NAME_PARTS = (
    ".env",
    ".env.",
    "credentials",
    "access_key",
    ".pem",
    ".pfx",
    "__pycache__",
    ".pyc",
    ".venv",
    "node_modules",
)

# Nombres de código que NO son secretos reales (no excluir por substring "secret")
ALLOWLIST_CODE_NAMES = frozenset({
    "security_secrets.py",
})


EXCLUDE_PATH_PARTS = (
    "BSC.genesis.conversational.backend",
    "lab_fallback",
    "customer_real",
)


README = """# Paquete capa cognitiva V3.1

Fecha UTC empaquetado: {ts}

## Contenido
- Código: `src/genesis_cognitive`
- Pruebas: `tests/unit` (incluye test_correccion_auditada_v3_1, test_casos_adicionales_v3, test_cierre_cognitivo_v3_1, test_cognitive_improvement_v3)
- FAQ local: `data/kb_faq_vf01.json` (+ overlay) y `data/kb_glossary_local_v31.json`
- Incluye `src/genesis_cognitive/brain/security_secrets.py` (allowlist; no es secreto real)
- Insumos 236+24 y entregables en `works/`

## Excluido
- Secretos / `.env`
- `BSC.genesis.conversational.backend`
- Datos reales de clientes
- `.venv` / caches

## Cómo probar
```
python -m venv .venv
.venv\\Scripts\\pip install -e ".[dev]"   # o dependencias del pyproject
.venv\\Scripts\\python -m pytest tests/unit/test_casos_adicionales_v3.py tests/unit/test_cierre_cognitivo_v3_1.py tests/unit/test_cognitive_improvement_v3.py -q
```

GENESIS_AZURE_BRAIN=0 para ejecución local determinista.
No desplegar ni modificar Foundry desde este paquete.

## Resultados incluidos
- `works/RESULTADOS_CASOS_ADICIONALES_V3.json`
- `works/MATRIZ_COBERTURA_CIERRE_V3_1.json`
- `works/VINCULACION_9_CASOS_APROBADOS_V3_1.json`
- `works/DOC_PLAN_INTERPRETER_V3_1.md`
"""


def _skip(path: Path) -> bool:
    s = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    if path.name in ALLOWLIST_CODE_NAMES or name in {a.lower() for a in ALLOWLIST_CODE_NAMES}:
        # Solo aplicar exclusiones de path peligrosas, no el filtro por nombre "secret"
        return any(p in s for p in EXCLUDE_PATH_PARTS)
    if any(p in s for p in EXCLUDE_PATH_PARTS):
        return True
    # Secretos reales: .env*, *credentials*, access_key, keys — no módulos de detección
    if name.startswith(".env") or name.endswith(".env"):
        return True
    if any(p in name for p in EXCLUDE_NAME_PARTS):
        return True
    if "secret" in name and name not in {a.lower() for a in ALLOWLIST_CODE_NAMES}:
        # p. ej. secrets.json, api_secret.txt — no security_secrets.py (allowlist)
        if name.endswith((".json", ".txt", ".pem", ".key", ".env")) or "credentials" in name:
            return True
    return False


def main() -> None:
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not _skip(p):
                files.append(p)
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if p.is_file() and not _skip(p):
            files.append(p)

    # dedupe
    uniq = sorted({p.resolve() for p in files}, key=lambda x: str(x))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()

    readme_body = README.format(ts=datetime.now(timezone.utc).isoformat())
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README_PAQUETE_COGNITIVO_V3_1.md", readme_body)
        for p in uniq:
            arc = p.relative_to(ROOT).as_posix()
            zf.write(p, arcname=arc)

    h = hashlib.sha256(OUT.read_bytes()).hexdigest()
    meta = ROOT / "works" / "ZIP_COGNITIVO_V3_1_META.json"
    meta.write_text(
        __import__("json").dumps(
            {
                "zip": OUT.name,
                "path": str(OUT),
                "sha256": h,
                "bytes": OUT.stat().st_size,
                "file_count": len(uniq) + 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(OUT)
    print("sha256", h)
    print("files", len(uniq) + 1, "bytes", OUT.stat().st_size)


if __name__ == "__main__":
    main()
