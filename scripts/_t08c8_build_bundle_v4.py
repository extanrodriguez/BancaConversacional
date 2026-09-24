"""Build T08-C8 V4 validation bundle ZIP with FILE_MANIFEST_SHA256.txt."""

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
ZIP_NAME = "Genesis_v2_T08_validation_bundle_20260727_v4.zip"
ZIP_PATH = ROOT.parent / ZIP_NAME
ZIP_ROOT = "Genesis_v2_T08_validation_bundle_20260727_v4"

# Directories to include
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

# Files to include at root
INCLUDE_FILES = [
    "pyproject.toml",
    "requirements.lock.txt",
    "README_VALIDATION.md",
    ".gitignore",
]

# Exclusion patterns
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
    """Check if a path should be excluded."""
    for part in path.parts:
        if part in EXCLUDE_NAMES:
            return True
    return path.suffix in EXCLUDE_EXTENSIONS


def collect_files() -> list[Path]:
    """Collect all files to include in the bundle."""
    files: list[Path] = []

    # Collect directory contents
    for dir_rel in INCLUDE_DIRS:
        dir_path = ROOT / dir_rel
        if dir_path.exists():
            for f in sorted(dir_path.rglob("*")):
                if f.is_file() and not should_exclude(f.relative_to(ROOT)):
                    files.append(f)

    # Collect root files
    for file_rel in INCLUDE_FILES:
        file_path = ROOT / file_rel
        if file_path.exists():
            files.append(file_path)

    return sorted(set(files))


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    files = collect_files()
    print(f"Collected {len(files)} files for bundle")

    # Build manifest
    manifest_lines: list[str] = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        sha = compute_sha256(f)
        manifest_lines.append(f"{sha}  {rel}")

    manifest_content = "\n".join(manifest_lines) + "\n"

    # Write manifest to evidence dir as well
    manifest_evidence = ROOT / "evidence" / "FILE_MANIFEST_SHA256.txt"
    manifest_evidence.write_text(manifest_content, encoding="utf-8")
    print(f"Manifest written to {manifest_evidence}")

    # Create ZIP
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add all source files
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            arcname = f"{ZIP_ROOT}/{rel}"
            zf.write(f, arcname)

        # Add FILE_MANIFEST_SHA256.txt at root of payload
        zf.writestr(
            f"{ZIP_ROOT}/FILE_MANIFEST_SHA256.txt",
            manifest_content,
        )

    # Stats
    zip_size = ZIP_PATH.stat().st_size
    zip_sha = compute_sha256(ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        entry_count = len(zf.namelist())

    print(f"\nBundle created: {ZIP_PATH}")
    print(f"Size: {zip_size:,} bytes")
    print(f"Entries: {entry_count}")
    print(f"SHA-256: {zip_sha}")

    # Verify no .env
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        env_files = [n for n in zf.namelist() if ".env" in n.split("/")[-1]]
        if env_files:
            print(f"ERROR: .env files found: {env_files}")
        else:
            print(".env present: NO (verified)")


if __name__ == "__main__":
    main()
