r"""T13-A2B — ContractInspector smoke test with ONE real inference.

Usage:
    .\.venv\Scripts\python.exe scripts/t13_a2b_contract_inspector_smoke.py

Performs a single real inference:
  Input: "Enséñame los movimientos recientes de la de ahorros."
  Expected: ACCOUNT_MOVEMENTS_READ, AHO001, MovementsResponse,
            catalog_valid=True, entity_refs_valid=True, overall_status=VALID

Saves evidence to evidence/t13-a2b-contract-inspector.txt

Does NOT print secrets. Does NOT execute financial operations.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure src is importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402


async def main() -> None:
    """Run the smoke test."""
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(env_path)

    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

    if not api_key:
        print("ERROR: OPENAI_API_KEY not found in .env")
        sys.exit(1)

    from genesis_cognitive.agents.agent_framework_turn_resolver import create_turn_resolver
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.inspection.contract_inspector import ContractInspector
    from genesis_cognitive.model_input.model_input_builder import (
        ModelInputEnvelope,
        ProjectedCapability,
        ProjectedPendingOperation,
        ProjectedProduct,
    )
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry

    # Build dependencies
    prompts_root = PROJECT_ROOT / "prompts"
    schemas_root = PROJECT_ROOT / "schemas"
    registry = PromptRegistry(prompts_root, schemas_root)
    resolver = create_turn_resolver(registry, api_key, model)
    gate = SemanticContractGate()
    inspector = ContractInspector(resolver, gate)

    # Synthetic portfolio
    portfolio = (
        ProjectedProduct(
            product_ref="COR001",
            product_type="CHECKING",
            label="Cuenta corriente",
            alias="cuenta principal",
            currency="DOP",
            operational_state="ACTIVE",
        ),
        ProjectedProduct(
            product_ref="AHO001",
            product_type="SAVINGS",
            label="Cuenta de ahorros",
            alias="mis ahorros",
            currency="DOP",
            operational_state="ACTIVE",
        ),
    )

    # Effective capabilities from catalog
    catalog = CapabilityCatalog()
    manifests = catalog.get_manifests()
    effective_capabilities = tuple(
        ProjectedCapability(
            capability_id=m.capability_id,
            intent_ids=m.intent_ids,
            capability_candidate=m.capability_candidate,
            domain=m.domain,
            description=m.description,
            selected_route=m.selected_route,
            required_entities=m.required_entities,
            optional_entities=m.optional_entities,
            min_required_entities=m.validation_rules.min_required_entities,
            output_contract=m.output_contract,
            support_level=m.support_level.value,
            requires_confirmation=m.orchestrator_requirements.requires_confirmation,
            requires_idempotency=m.orchestrator_requirements.requires_idempotency,
        )
        for m in manifests
    )

    base_input = ModelInputEnvelope(
        raw_text="",
        language="es",
        locale="es-DO",
        conversation=(),
        portfolio=portfolio,
        pending_operation=ProjectedPendingOperation(),
        effective_capabilities=effective_capabilities,
    )

    # The test question
    question = "Enséñame los movimientos recientes de la de ahorros."

    print(f"Question: {question}")
    print("Running single inference...")

    result = await inspector.inspect(question, base_input)

    # Print results
    print(f"\n{'=' * 60}")
    print("RESULT:")
    print(f"  mode: {result.mode}")
    print(f"  catalog_valid: {result.catalog_valid}")
    print(f"  entity_refs_valid: {result.entity_refs_valid}")
    print(f"  overall_status: {result.overall_status}")
    print(f"  rag_status: {result.rag_status}")
    print(f"  output_contracts: {result.output_contracts}")
    print(f"  violations: {result.violations}")
    print(f"  inference_count: {result.inference_count}")

    if result.raw_interpretation.actions:
        action = result.raw_interpretation.actions[0]
        print("\n  Action 1:")
        print(f"    intent_id: {action.intent_id}")
        print(f"    capability_candidate: {action.capability_candidate}")
        print(f"    selected_route: {action.selected_route}")
        print(f"    detected_entities: {action.detected_entities.model_dump()}")
        print(f"    confidence: {action.confidence}")
        print(f"    missing_requirements: {action.missing_requirements}")

    # Assertions
    checks_passed = 0
    checks_total = 0

    def check(condition: bool, name: str) -> None:
        nonlocal checks_passed, checks_total
        checks_total += 1
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {name}")
        if condition:
            checks_passed += 1

    print(f"\n{'=' * 60}")
    print("CHECKS:")

    action_or_none = (
        result.raw_interpretation.actions[0] if result.raw_interpretation.actions else None
    )

    check(action_or_none is not None, "At least one action present")
    if action_or_none:
        action = action_or_none
        check(
            action.intent_id == "ACCOUNT_MOVEMENTS_READ",
            f"intent_id == ACCOUNT_MOVEMENTS_READ (got: {action.intent_id})",
        )
        check(
            action.detected_entities.account_ref == "AHO001",
            f"account_ref == AHO001 (got: {action.detected_entities.account_ref})",
        )
    check(result.catalog_valid is True, "catalog_valid == True")
    check(result.entity_refs_valid is True, "entity_refs_valid == True")
    check(
        result.overall_status == "VALID",
        f"overall_status == VALID (got: {result.overall_status})",
    )
    check(
        "MovementsResponse" in result.output_contracts,
        f"output_contracts contains MovementsResponse (got: {result.output_contracts})",
    )
    check(result.inference_count == 1, "inference_count == 1")

    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {checks_passed}/{checks_total} checks passed")

    # Save evidence
    evidence_dir = PROJECT_ROOT / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    evidence_path = evidence_dir / "t13-a2b-contract-inspector.txt"

    timestamp = datetime.now(UTC).isoformat()
    evidence_lines = [
        "T13-A2B Contract Inspector Smoke Test Evidence",
        f"{'=' * 60}",
        f"Timestamp: {timestamp}",
        f"Model: {model}",
        f"Question: {question}",
        "",
        "Result:",
        f"  mode: {result.mode}",
        f"  catalog_valid: {result.catalog_valid}",
        f"  entity_refs_valid: {result.entity_refs_valid}",
        f"  overall_status: {result.overall_status}",
        f"  rag_status: {result.rag_status}",
        f"  output_contracts: {result.output_contracts}",
        f"  violations: {result.violations}",
        f"  inference_count: {result.inference_count}",
        "",
    ]

    if action:
        evidence_lines.extend(
            [
                "  Action 1:",
                f"    intent_id: {action.intent_id}",
                f"    capability_candidate: {action.capability_candidate}",
                f"    selected_route: {action.selected_route}",
                f"    detected_entities: {action.detected_entities.model_dump()}",
                f"    confidence: {action.confidence}",
                f"    missing_requirements: {action.missing_requirements}",
                "",
            ]
        )

    evidence_lines.extend(
        [
            f"Checks: {checks_passed}/{checks_total} passed",
            "",
            "Files involved:",
            "  src/genesis_cognitive/decision/semantic_contract_gate.py",
            "  src/genesis_cognitive/inspection/__init__.py",
            "  src/genesis_cognitive/inspection/contract_inspector.py",
            "  src/genesis_cognitive/demo/contract_inspector_app.py",
            "  src/genesis_cognitive/demo/static/index.html",
            "  scripts/run_contract_inspector.py",
            "  tests/unit/test_contract_inspector.py",
            "  scripts/t13_a2b_contract_inspector_smoke.py",
            "",
            "Security: OPENAI_API_KEY loaded from .env, not printed.",
            "Azure: No Azure changes in this task.",
            "Limitations: Smoke test depends on model output consistency.",
        ]
    )

    evidence_path.write_text("\n".join(evidence_lines), encoding="utf-8")
    print(f"\nEvidence saved to: {evidence_path.resolve()}")

    if checks_passed < checks_total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
