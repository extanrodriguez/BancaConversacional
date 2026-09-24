"""Genera genesis_corp_8446.zip para deploy en VM (rutas POSIX, sin secretos)."""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "deploy" / "corp-8446" / "dist"
ZIP_NAME = "genesis_corp_8446.zip"
STAGING = ROOT / ".build_corp_staging"

INCLUDE_TOP = (
    "pyproject.toml",
    "requirements.runtime.txt",
)

INCLUDE_DIRS = (
    "src",
    "scripts",
    "prompts",
    "schemas",
    "deploy",
    "tests",
    "data",
    "Knowledge_Base",
    "docs",
)

SKIP_DIR_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".swp"}
SKIP_FILE_NAMES = {".env", ".env.local", ".env.production"}


def _sync_lab_portfolios(staging: Path) -> None:
    """Asegura qa_andres_david.json actualizado en lab_portfolios."""
    src = ROOT / "Test_local" / "data" / "portfolios" / "qa_andres_david.json"
    dst_dir = staging / "data" / "lab_portfolios"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dst_dir / "qa_andres_david.json")


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix in SKIP_FILE_SUFFIXES:
        return True
    for part in path.parts:
        if part in SKIP_DIR_NAMES:
            return True
    if path.suffix in (".sqlite-shm", ".sqlite-wal"):
        return True
    return False


def _collect_files(staging: Path) -> list[Path]:
    files: list[Path] = []
    for rel in INCLUDE_TOP:
        fp = staging / rel
        if fp.is_file():
            files.append(fp)
    for rel_dir in INCLUDE_DIRS:
        base = staging / rel_dir
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for fn in filenames:
                fp = Path(dirpath) / fn
                if _should_skip(fp):
                    continue
                files.append(fp)
    return sorted(set(files))


def main() -> int:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    for rel in INCLUDE_TOP:
        src = ROOT / rel
        if src.is_file():
            dst = STAGING / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    for rel_dir in INCLUDE_DIRS:
        src = ROOT / rel_dir
        if src.exists():
            def _ignore(dirpath: str, names: list[str]) -> set[str]:
                ignored = set(SKIP_DIR_NAMES)
                if "dist" in names and rel_dir == "deploy":
                    ignored.add("dist")
                if ".build_corp_staging" in names:
                    ignored.add(".build_corp_staging")
                return ignored

            shutil.copytree(
                src,
                STAGING / rel_dir,
                ignore=_ignore,
                dirs_exist_ok=True,
            )

    # La UI canónica ya está bajo src/genesis_cognitive/demo/pruebas_ui.
    # No sobrescribirla con la copia histórica de "interfaz Prueba/web".
    _sync_lab_portfolios(STAGING)

    # Manifest de build
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = STAGING / "deploy" / "corp-8446" / "BUILD_STAMP.txt"
    manifest.write_text(f"built_at={stamp}\nsource={ROOT}\n", encoding="utf-8")

    files = _collect_files(STAGING)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUT_DIR / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    # Scripts bash deben tener LF (evitar set: pipefail\r en Linux)
    for fp in files:
        if fp.suffix == ".sh":
            raw = fp.read_bytes()
            fp.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            arcname = fp.relative_to(STAGING).as_posix()
            zf.write(fp, arcname)

    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"ZIP: {zip_path}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"Files: {len(files)}")
    print(f"SHA256: {sha}")
    (OUT_DIR / "genesis_corp_8446.sha256").write_text(f"{sha}  {ZIP_NAME}\n", encoding="utf-8")

    shutil.rmtree(STAGING, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
