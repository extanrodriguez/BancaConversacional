"""T08-C8 Document consistency verification script."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def check_schemas() -> tuple[list[str], bool]:
    """Verify all schemas are Draft 2020-12 and check already_known enum."""
    results: list[str] = []
    schemas_dir = ROOT / "schemas"
    schemas = sorted(schemas_dir.glob("*.json"))
    results.append(f"Schemas found: {len(schemas)}")

    all_2020_12 = True
    for s in schemas:
        data = json.loads(s.read_text(encoding="utf-8"))
        sv = data.get("$schema", "MISSING")
        ok = "2020-12" in sv
        all_2020_12 = all_2020_12 and ok
        results.append(f"  {s.name}: {'PASS' if ok else 'FAIL'} ($schema={sv[:60]})")

    results.append(f"All Draft 2020-12: {all_2020_12}")

    # Check already_known enum restriction
    results.append("")
    results.append("--- already_known enum restriction ---")
    ti_schema = schemas_dir / "turn_interpretation.schema.json"
    ir_schema = schemas_dir / "intent_resolution.schema.json"

    for schema_file in [ti_schema, ir_schema]:
        if schema_file.exists():
            content = schema_file.read_text(encoding="utf-8")
            has_already_known = "already_known" in content
            # Check if there's an enum constraint on already_known items
            data = json.loads(content)
            enum_found = _find_already_known_enum(data)
            results.append(
                f"  {schema_file.name}: already_known present={has_already_known}, "
                f"enum restricted={enum_found}"
            )
        else:
            results.append(f"  {schema_file.name}: NOT FOUND")

    return results, all_2020_12


def _find_already_known_enum(obj: object, path: str = "") -> bool:
    """Recursively find if already_known has enum restriction."""
    if isinstance(obj, dict):
        if "already_known" in obj:
            ak = obj["already_known"]
            if isinstance(ak, dict):
                items = ak.get("items", {})
                if isinstance(items, dict) and "enum" in items:
                    return True
        for k, v in obj.items():
            if _find_already_known_enum(v, f"{path}.{k}"):
                return True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if _find_already_known_enum(item, f"{path}[{i}]"):
                return True
    return False


def check_evidence_files() -> tuple[list[str], bool]:
    """Verify evidence files exist for C7A-C7E."""
    results: list[str] = []
    evidence_dir = ROOT / "evidence"

    expected = [
        "t08-c7a-business-knowledge-validation.txt",
        "t08-c7b-account-balance-validation.txt",
        "t08-c7c-transfer-validation.txt",
        "t08-c7d-multi-dependent-validation.txt",
        "t08-c7e-minimal-clarification-validation.txt",
    ]

    results.append("--- Evidence files for C7A-C7E ---")
    all_exist = True
    for f in expected:
        exists = (evidence_dir / f).exists()
        all_exist = all_exist and exists
        results.append(f"  {f}: {'EXISTS' if exists else 'MISSING'}")

    results.append(f"All C7A-C7E evidence present: {all_exist}")
    return results, all_exist


def check_directives() -> tuple[list[str], bool]:
    """Verify mandatory-project-directives.md starts with 1.5 and has 1-248."""
    results: list[str] = []
    directives_path = ROOT / ".kiro" / "steering" / "mandatory-project-directives.md"
    content = directives_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    starts_v15 = "1.5" in lines[0]
    results.append(f"Starts with Version 1.5: {starts_v15} (title: {lines[0][:80]})")

    # Check for directive 1 and 248
    has_1 = any(line.strip().startswith("1.") for line in lines)
    has_248 = any(line.strip().startswith("248.") for line in lines)
    results.append(f"Has directive 1: {has_1}")
    results.append(f"Has directive 248: {has_248}")

    return results, starts_v15 and has_1 and has_248


def check_requirements_design() -> tuple[list[str], bool]:
    """Verify requirements.md and design.md reference 1.5."""
    results: list[str] = []
    spec_dir = ROOT / ".kiro" / "specs" / "cognitive-turn-routing-mvp"

    req = (spec_dir / "requirements.md").read_text(encoding="utf-8")
    des = (spec_dir / "design.md").read_text(encoding="utf-8")

    req_15 = "1.5" in req
    des_15 = "1.5" in des
    results.append(f"requirements.md references 1.5: {req_15}")
    results.append(f"design.md references 1.5: {des_15}")

    return results, req_15 and des_15


def check_prompt_registry() -> tuple[list[str], bool]:
    """Verify PromptRegistry loads 1.1.0 current and 1.0.0 explicit."""
    results: list[str] = []
    sys.path.insert(0, str(ROOT / "src"))

    from genesis_cognitive.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry(ROOT / "prompts", ROOT / "schemas")
    current = reg.get_current("turn-decision-agent")
    explicit = reg.get("turn-decision-agent", "1.0.0")

    cur_ok = current.prompt_version == "1.2.0"
    exp_ok = explicit.prompt_version == "1.0.0"

    cur_msg = f"PromptRegistry current version: {current.prompt_version} (expected 1.2.0)"
    results.append(f"{cur_msg}: {'PASS' if cur_ok else 'FAIL'}")
    exp_msg = f"PromptRegistry explicit 1.0.0: {explicit.prompt_version} (expected 1.0.0)"
    results.append(f"{exp_msg}: {'PASS' if exp_ok else 'FAIL'}")

    return results, cur_ok and exp_ok


def main() -> int:
    all_lines: list[str] = [
        "T08-C8 — Document Consistency Checks",
        "=" * 40,
        "",
    ]
    overall = True

    # Check 1: Directives
    all_lines.append("--- Mandatory Project Directives ---")
    lines, ok = check_directives()
    all_lines.extend(lines)
    overall = overall and ok
    all_lines.append("")

    # Check 2: Requirements and Design
    all_lines.append("--- Requirements/Design version references ---")
    lines, ok = check_requirements_design()
    all_lines.extend(lines)
    overall = overall and ok
    all_lines.append("")

    # Check 3: PromptRegistry
    all_lines.append("--- PromptRegistry version loading ---")
    lines, ok = check_prompt_registry()
    all_lines.extend(lines)
    overall = overall and ok
    all_lines.append("")

    # Check 4: Schemas
    all_lines.append("--- Schema validation (Draft 2020-12) ---")
    lines, ok = check_schemas()
    all_lines.extend(lines)
    overall = overall and ok
    all_lines.append("")

    # Check 5: Evidence C7A-C7E
    lines, ok = check_evidence_files()
    all_lines.extend(lines)
    overall = overall and ok
    all_lines.append("")

    all_lines.append(f"OVERALL: {'PASS' if overall else 'FAIL'}")

    # Write evidence
    output = "\n".join(all_lines)
    print(output)
    evidence_path = ROOT / "evidence" / "t08-c8-document-consistency.txt"
    evidence_path.write_text(output, encoding="utf-8")

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
