"""Empaqueta cierre V4 QA (cognitivo) sin secretos ni backend externo."""
from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d")
OUT = ROOT / "works" / f"BancaConversacional_Cierre_V4_QA_{STAMP}.zip"

INCLUDE_DIRS = [
    "src/genesis_cognitive",
    "schemas",
    "data",
    "tests/unit",
]
INCLUDE_FILES = [
    "pyproject.toml",
    "requirements.txt",
    "works/ENTREGA_CIERRE_V4_QA.md",
    "works/_qa_cierre_v4_726588_raw.json",
    "works/RESULTADOS_REDIS_QA_VM.md",
    "deploy/corp-8447/_ssh_patch_ready_redis_async.py",
    "deploy/corp-8447/_remote_restart_cierre_v4.sh",
]
EXCLUDE_PARTS = {
    ".venv", "__pycache__", ".pyc", ".env", "secrets",
    "BSC.genesis.conversational.backend",
}


def _skip(path: Path) -> bool:
    s = path.as_posix()
    return any(p in s for p in EXCLUDE_PARTS)


def main() -> None:
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not _skip(p):
                files.append(p)
    for f in INCLUDE_FILES:
        p = ROOT / f
        if p.is_file():
            files.append(p)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(set(files), key=lambda x: x.as_posix()):
            zf.write(p, p.relative_to(ROOT).as_posix())

    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    meta = {
        "zip": OUT.name,
        "sha256": digest,
        "bytes": OUT.stat().st_size,
        "utc": datetime.now(timezone.utc).isoformat(),
        "includes_redis_entra_async": True,
        "note": "No secrets. Orquestador externo no incluido.",
    }
    meta_path = ROOT / "works" / "ZIP_CIERRE_V4_QA_META.json"
    import json
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # per-file hashes of key cognitive paths
    key = [
        "src/genesis_cognitive/brain/azure_plan_turn.py",
        "src/genesis_cognitive/brain/azure_plan_adapter.py",
        "src/genesis_cognitive/brain/plan_interpreter.py",
        "src/genesis_cognitive/brain/plan_executor.py",
        "src/genesis_cognitive/context/app_channel.py",
        "src/genesis_cognitive/demo/contract_inspector_app.py",
        "src/genesis_cognitive/context/redis_client_factory.py",
    ]
    manifest = {
        rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        for rel in key if (ROOT / rel).is_file()
    }
    (ROOT / "works" / "MANIFEST_SHA256_CIERRE_V4_QA.json").write_text(
        json.dumps({"zip_sha256": digest, "files": manifest}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
