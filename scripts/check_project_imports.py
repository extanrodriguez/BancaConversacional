"""T08-C8 — Import integrity scan for genesis_cognitive package."""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"


def scan_imports() -> int:
    """Discover and import all modules under genesis_cognitive."""
    sys.path.insert(0, str(SRC))

    discovered: list[str] = []
    imported: list[str] = []
    failed: list[tuple[str, str]] = []

    package_path = str(SRC / "genesis_cognitive")

    for _importer, modname, _ispkg in pkgutil.walk_packages(
        path=[package_path],
        prefix="genesis_cognitive.",
    ):
        discovered.append(modname)
        try:
            importlib.import_module(modname)
            imported.append(modname)
        except Exception as e:
            failed.append((modname, f"{type(e).__name__}: {e}"))

    # AST scan for prohibited imports
    violations: list[tuple[str, str]] = []
    src_files = list((SRC / "genesis_cognitive").rglob("*.py"))

    prohibited_prefixes = ("tests", "scripts", ".kiro")

    for py_file in src_files:
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in prohibited_prefixes:
                        if alias.name.startswith(prefix):
                            violations.append((str(py_file), alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for prefix in prohibited_prefixes:
                        if node.module.startswith(prefix):
                            violations.append((str(py_file), node.module))

    # Print report
    print(f"modules_discovered: {len(discovered)}")
    print(f"modules_imported: {len(imported)}")
    print(f"modules_failed: {len(failed)}")
    if failed:
        for name, err in failed:
            print(f"  FAIL: {name} -> {err}")
    print(f"production_dependency_violations: {len(violations)}")
    if violations:
        for filepath, imp in violations:
            print(f"  VIOLATION: {filepath} imports {imp}")

    # Write evidence
    evidence_path = ROOT / "evidence" / "t08-c8-import-integrity.txt"
    lines = [
        "T08-C8 — Import Integrity Scan",
        "=" * 40,
        "",
        "Discovered modules:",
    ]
    for m in sorted(discovered):
        status = "PASS" if m in imported else "FAIL"
        lines.append(f"  {m}: {status}")
    lines.append("")
    lines.append(f"total_discovered: {len(discovered)}")
    lines.append(f"total_imported: {len(imported)}")
    lines.append(f"total_failed: {len(failed)}")
    if failed:
        lines.append("")
        lines.append("Failures:")
        for name, err in failed:
            lines.append(f"  {name}: {err}")
    lines.append("")
    lines.append(f"production_dependency_violations: {len(violations)}")
    if violations:
        for filepath, imp in violations:
            lines.append(f"  {filepath} -> {imp}")
    lines.append("")
    lines.append(f"exit_code: {1 if failed or violations else 0}")
    evidence_path.write_text("\n".join(lines), encoding="utf-8")

    return 1 if failed or violations else 0


if __name__ == "__main__":
    sys.exit(scan_imports())
