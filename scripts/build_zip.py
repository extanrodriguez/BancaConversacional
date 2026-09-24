"""Build T02 validation ZIP with forward slashes and SHA-256 manifest."""

import hashlib
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
ZIP_NAME = "Genesis_v2_T08_validation_bundle_20260726_v2.zip"
ZIP_PATH = ROOT / "evidence" / ZIP_NAME
BUNDLE_PREFIX = "Genesis_v2_T08_validation_bundle_20260726_v2"

# Explicit file list (relative to ROOT, using /)
FILES = [
    "pyproject.toml",
    ".gitignore",
    "requirements.lock.txt",
    ".kiro/steering/mandatory-project-directives.md",
    ".kiro/specs/cognitive-turn-routing-mvp/requirements.md",
    ".kiro/specs/cognitive-turn-routing-mvp/design.md",
    ".kiro/specs/cognitive-turn-routing-mvp/tasks.md",
    "schemas/orchestrator_turn_request.schema.json",
    "schemas/cognitive_turn_request.schema.json",
    "schemas/error_response.schema.json",
    "schemas/turn_interpretation.schema.json",
    "schemas/intent_resolution.schema.json",
    "schemas/capability_manifest.schema.json",
    "scripts/generate_schemas.py",
    "scripts/generate_prompt_schema.py",
    "scripts/generate_prompt_v1.py",
    "scripts/fix_schemas_uniqueitems.py",
    "scripts/write_coherence_tests.py",
    "scripts/write_test_types.py",
    "prompts/schemas/agent_prompt.schema.json",
    "prompts/turn-decision-agent/1.0.0/prompt.json",
    "prompts/turn-decision-agent/current.json",
    "evidence/microsoft-agent-framework-dependency-report.md",
    "README_VALIDATION.md",
    "evidence/t01-validation-report.md",
    "evidence/t01-python-environment.txt",
    "evidence/t01-global-pip-check.txt",
    "evidence/t01-venv-pip-check.txt",
    "evidence/t01-pytest-collect.txt",
    "evidence/t01-pytest-run.txt",
    "evidence/t01-ruff-format.txt",
    "evidence/t01-ruff-check.txt",
    "evidence/t01-mypy.txt",
    "evidence/t01-installed-packages.txt",
    "evidence/t02-schema-validation-report.md",
    "evidence/t02-pytest-schemas.txt",
    "evidence/t02-pytest-full.txt",
    "evidence/t02-ruff-format.txt",
    "evidence/t02-ruff-check.txt",
    "evidence/t02-mypy.txt",
    "evidence/t02-pip-check.txt",
    "evidence/t03-model-validation-report.md",
    "evidence/t03-pytest-types.txt",
    "evidence/t03-pytest-coherence.txt",
    "evidence/t03-pytest-full.txt",
    "evidence/t03-coverage.txt",
    "evidence/t03-ruff-format.txt",
    "evidence/t03-ruff-check.txt",
    "evidence/t03-mypy.txt",
    "evidence/t03-pip-check.txt",
    "evidence/t04-prompt-validation-report.md",
    "evidence/t04-pytest-prompts.txt",
    "evidence/t04-pytest-full.txt",
    "evidence/t04-coverage.txt",
    "evidence/t04-ruff-format.txt",
    "evidence/t04-ruff-check.txt",
    "evidence/t04-mypy.txt",
    "evidence/t04-pip-check.txt",
    "evidence/t05-prompt-registry-validation-report.md",
    "evidence/t05-pytest-prompts.txt",
    "evidence/t05-pytest-registry.txt",
    "evidence/t05-pytest-coherence.txt",
    "evidence/t05-pytest-full.txt",
    "evidence/t05-coverage.txt",
    "evidence/t05-ruff-format.txt",
    "evidence/t05-ruff-check.txt",
    "evidence/t05-mypy.txt",
    "evidence/t05-pip-check.txt",
    "evidence/t06-capability-catalog-validation-report.md",
    "evidence/t06-pytest-catalog.txt",
    "evidence/t06-pytest-route-table.txt",
    "evidence/t06-pytest-full.txt",
    "evidence/t06-coverage.txt",
    "evidence/t06-ruff-format.txt",
    "evidence/t06-ruff-check.txt",
    "evidence/t06-mypy.txt",
    "evidence/t06-pip-check.txt",
    "evidence/t07-pytest-adapters.txt",
    "evidence/t07-pytest-full.txt",
    "evidence/t07-coverage.txt",
    "evidence/t07-ruff-check.txt",
    "evidence/t07-mypy.txt",
    "evidence/t07-pip-check.txt",
    "evidence/t08-pytest-catalog.txt",
    "evidence/t08-pytest-adapters.txt",
    "evidence/t08-pytest-full.txt",
    "evidence/t08-coverage.txt",
    "evidence/t08-ruff-format.txt",
    "evidence/t08-ruff-check.txt",
    "evidence/t08-mypy.txt",
    "evidence/t08-pip-check.txt",
    "evidence/agentic-rag-architecture-rebaseline-report.md",
    "evidence/t08-openai-connectivity.txt",
    "evidence/t08-openai-semantic-preflight.json",
    "evidence/t08-openai-semantic-preflight-report.md",
    "scripts/check_openai_connectivity.py",
    "scripts/run_openai_semantic_preflight.py",
    "tests/unit/test_project_scaffold.py",
    "tests/unit/test_schemas.py",
    "tests/unit/test_types.py",
    "tests/unit/test_model_schema_coherence.py",
    "tests/unit/test_prompts.py",
    "tests/unit/test_prompt_registry.py",
    "tests/unit/test_capability_catalog.py",
    "tests/unit/test_route_table.py",
    "tests/unit/test_adapters.py",
]

# Collect all .py files from src and tests
for dirpath, _, filenames in os.walk(ROOT / "src"):
    for f in filenames:
        if f.endswith(".py"):
            rel = Path(dirpath, f).relative_to(ROOT).as_posix()
            FILES.append(rel)

for dirpath, _, filenames in os.walk(ROOT / "tests"):
    for f in filenames:
        if f.endswith(".py"):
            rel = Path(dirpath, f).relative_to(ROOT).as_posix()
            FILES.append(rel)

FILES = sorted(set(FILES))


def main() -> None:
    # Generate manifest
    manifest_lines = [
        "# FILE_MANIFEST_SHA256.txt",
        "# This manifest self-excludes itself.",
        f"# Total files declared: {len(FILES)}",
        "",
    ]
    for f in FILES:
        fp = ROOT / f
        size = fp.stat().st_size
        sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        manifest_lines.append(f"{f} | {size} bytes | {sha}")

    manifest_content = "\n".join(manifest_lines) + "\n"

    # Build ZIP
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        # Manifest
        zf.writestr(f"{BUNDLE_PREFIX}/FILE_MANIFEST_SHA256.txt", manifest_content)

        # All files
        for f in FILES:
            fp = ROOT / f
            arcname = f"{BUNDLE_PREFIX}/{f}"
            zf.write(fp, arcname)

    # Verify
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        entries = zf.namelist()

    # README is now in FILES list directly
    # Manifest is the only extra entry (self-excluded)
    total_zip_entries = len(entries)
    manifest_declares = len(FILES)

    print(f"ZIP: {ZIP_PATH}")
    print(f"Size: {ZIP_PATH.stat().st_size} bytes")
    print(f"SHA256: {hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()}")
    print(f"Total ZIP entries: {total_zip_entries}")
    print(f"Manifest declares: {manifest_declares} files")
    print(f"ZIP entries - 1 manifest = {total_zip_entries - 1}")
    print(f"Match: {total_zip_entries - 1 == manifest_declares}")

    # Exclusion checks
    forbidden = [
        ".env",
        ".venv",
        ".git/",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        ".pem",
        ".key",
    ]
    for pattern in forbidden:
        matches = [e for e in entries if pattern in e]
        status = "PASS" if len(matches) == 0 else "FAIL"
        print(f"{status}: '{pattern}' -> {len(matches)} matches")

    # Forward slash check
    backslash_entries = [e for e in entries if "\\" in e]
    print(f"Backslash entries: {len(backslash_entries)}")


if __name__ == "__main__":
    main()
