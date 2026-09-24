"""T13-A2B-E1 Validation Bundle Builder for Project Genesis."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\boris\Documents\Genesis\Genesis_v2")
ZIP_NAME = "Genesis_v2_T13_A2B_validation_bundle_20260727_v1"
ZIP_PATH = ROOT.parent / f"{ZIP_NAME}.zip"
VENV_PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
VENV_RUFF = str(ROOT / ".venv" / "Scripts" / "ruff.exe")

INCLUDE_DIRS = [
    ".kiro/steering",
    ".kiro/specs/cognitive-turn-routing-mvp",
    "src",
    "schemas",
    "prompts",
    "scripts",
    "tests",
    "evidence",
]
INCLUDE_FILES = [
    "pyproject.toml",
    "requirements.lock.txt",
    "README_VALIDATION.md",
    ".gitignore",
]
EXCLUDE_NAMES = {
    ".env",
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "Knowledge_Base",
}
EXCLUDE_EXTENSIONS = {".pdf", ".zip", ".pyc"}


def should_exclude(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_NAMES:
            return True
    if path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return True
    return path.name == "FILE_MANIFEST_SHA256.txt"


def sha256(fpath: Path) -> str:
    h = hashlib.sha256()
    with open(fpath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def effective_files(root: Path) -> list[Path]:
    result = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if f.name == "FILE_MANIFEST_SHA256.txt":
            continue
        rp = f.relative_to(root).parts
        if any(p in (".mypy_cache", "__pycache__", ".pytest_cache", ".ruff_cache") for p in rp):
            continue
        if f.suffix == ".pyc":
            continue
        result.append(f)
    return result


def main() -> None:
    # Collect files
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        dp = ROOT / d
        if dp.exists():
            for f in sorted(dp.rglob("*")):
                if f.is_file() and not should_exclude(f.relative_to(ROOT)):
                    files.append(f)
    for fr in INCLUDE_FILES:
        fp = ROOT / fr
        if fp.exists():
            files.append(fp)
    files = sorted(set(files))
    print(f"Files collected: {len(files)}")

    # Create staging directory
    tmp = tempfile.mkdtemp(prefix="t13a2b_")
    stage = Path(tmp) / ZIP_NAME
    stage.mkdir()
    for f in files:
        rel = f.relative_to(ROOT)
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)

    # Import origin check
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stage / "src")
    expected_dir = str(stage / "src" / "genesis_cognitive")
    import_check_code = (
        "import pathlib, genesis_cognitive; "
        "actual = str(pathlib.Path(genesis_cognitive.__file__).resolve()); "
        f"print(f'import_origin={{actual}}'); "
        f"assert r'{expected_dir}' in actual"
    )
    r = subprocess.run(
        [VENV_PYTHON, "-c", import_check_code],
        cwd=str(stage),
        capture_output=True,
        text=True,
        env=env,
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print("FAIL: import origin")
        print(r.stderr)
        shutil.rmtree(tmp)
        sys.exit(1)

    # Clean-room gates
    gates = [
        ([VENV_PYTHON, "-m", "pytest", "-q"], "pytest"),
        ([VENV_PYTHON, "-m", "pip", "check"], "pip_check"),
        ([VENV_RUFF, "format", "--check", "."], "ruff_format"),
        ([VENV_RUFF, "check", "."], "ruff_check"),
        ([VENV_PYTHON, "-m", "mypy", "src", "scripts"], "mypy"),
    ]
    for args, name in gates:
        r = subprocess.run(args, cwd=str(stage), capture_output=True, text=True, env=env)
        status = "PASS" if r.returncode == 0 else "FAIL"
        print(f"  {name}: {status} (exit {r.returncode})")
        if r.returncode != 0:
            print(r.stdout[-500:] if r.stdout else "")
            print(r.stderr[-500:] if r.stderr else "")
            shutil.rmtree(tmp)
            sys.exit(1)

    # Enumerate payload for manifest
    payload = effective_files(stage)
    print(f"Payload files: {len(payload)}")

    # Build manifest
    lines = []
    for pf in payload:
        pf_rel = pf.relative_to(stage).as_posix()
        lines.append(f"{sha256(pf)}  {pf_rel}")
    lines.sort(key=lambda x: x.split("  ", 1)[1].encode("utf-8"))
    manifest_content = "\n".join(lines) + "\n"
    manifest_count = len(lines)
    (stage / "FILE_MANIFEST_SHA256.txt").write_text(manifest_content, encoding="utf-8")

    # Create ZIP
    prefix = f"{ZIP_NAME}/"
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for pf in payload:
            pf_rel = pf.relative_to(stage).as_posix()
            zf.write(pf, prefix + pf_rel)
        zf.writestr(prefix + "FILE_MANIFEST_SHA256.txt", manifest_content)

    zip_size = ZIP_PATH.stat().st_size
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zip_entries = len(zf.namelist())
    print(f"ZIP: {ZIP_PATH}")
    print(f"Size: {zip_size} bytes")
    print(f"Entries: {zip_entries}")
    print(f"Manifest files: {manifest_count}")

    # Verify ZIP integrity
    manifest_map: dict[str, str] = {}
    for line in manifest_content.strip().split("\n"):
        hash_val, rel_path = line.split("  ", 1)
        manifest_map[rel_path] = hash_val

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        names = zf.namelist()
        unlisted = sum(
            1
            for n in names
            if not n.endswith("FILE_MANIFEST_SHA256.txt") and n[len(prefix) :] not in manifest_map
        )
        zip_rels = {n[len(prefix) :] for n in names if not n.endswith("FILE_MANIFEST_SHA256.txt")}
        missing = sum(1 for key in manifest_map if key not in zip_rels)
        mismatches = 0
        for n in names:
            if n.endswith("FILE_MANIFEST_SHA256.txt"):
                continue
            entry_rel = n[len(prefix) :]
            if entry_rel in manifest_map:
                actual = hashlib.sha256(zf.read(n)).hexdigest()
                if actual != manifest_map[entry_rel]:
                    mismatches += 1
        dups = len(names) - len(set(names))
        unsafe = sum(1 for n in names if ".." in n or n.startswith("/"))
        excluded = sum(
            1
            for n in names
            if any(
                p in n.split("/")
                for p in [".env", ".venv", "__pycache__", ".git", "Knowledge_Base"]
            )
            and not n.endswith("FILE_MANIFEST_SHA256.txt")
        )
        m_count = sum(1 for n in names if n.endswith("FILE_MANIFEST_SHA256.txt"))

    print(f"unlisted_entries: {unlisted}")
    print(f"missing_manifest_entries: {missing}")
    print(f"hash_mismatches: {mismatches}")
    print(f"duplicate_entries: {dups}")
    print(f"unsafe_paths: {unsafe}")
    print(f"excluded_files_found: {excluded}")
    print(f"manifest_count: {m_count}")

    # ZIP SHA-256
    zip_sha = sha256(ZIP_PATH)
    print(f"ZIP SHA-256: {zip_sha}")

    # Sidecar
    sidecar_path = ROOT.parent / f"{ZIP_NAME}.sha256.txt"
    sidecar_path.write_text(f"{zip_sha}  {ZIP_NAME}.zip\n", encoding="utf-8")
    print(f"Sidecar: {sidecar_path}")

    shutil.rmtree(tmp, ignore_errors=True)
    print("OVERALL: PASS")


if __name__ == "__main__":
    main()
