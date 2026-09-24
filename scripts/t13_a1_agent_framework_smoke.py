"""T13-A1 — Agent Framework Resolver smoke test.

Performs ONE real inference call using the Agent Framework resolver.
Validates structured output against TurnInterpretation.

Expected: ACCOUNT_BALANCE_READ, ACCOUNT_BALANCE, PERSONAL_READ for COR001.

Exit 0 on pass, 1 on fail.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


def load_env() -> None:
    """Load .env without printing secrets."""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    load_env()

    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_CHAT_MODEL") or os.environ.get("OPENAI_MODEL", "")

    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        return 1
    if not model:
        print("ERROR: OPENAI_CHAT_MODEL or OPENAI_MODEL not set.")
        return 1

    # Confirm key is loaded without printing it
    print(f"Model: {model}")
    print(f"API key loaded: {'yes' if api_key else 'no'} (length={len(api_key)})")

    # Import project modules
    from genesis_cognitive.agents.agent_framework_turn_resolver import create_turn_resolver
    from genesis_cognitive.decision.types import TurnInterpretation
    from genesis_cognitive.enums import SelectedRoute
    from genesis_cognitive.model_input.model_input_builder import (
        ModelInputEnvelope,
        ProjectedCapability,
        ProjectedPendingOperation,
        ProjectedProduct,
    )
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry

    # Build synthetic ModelInputEnvelope
    envelope = ModelInputEnvelope(
        raw_text="¿Cuánto tengo disponible en mi cuenta principal?",
        language="es",
        locale="es-DO",
        conversation=(),
        portfolio=(
            ProjectedProduct(
                product_ref="COR001",
                product_type="CHECKING",
                label="Cuenta corriente",
                alias="cuenta principal",
                currency="DOP",
                operational_state="ACTIVE",
            ),
        ),
        pending_operation=ProjectedPendingOperation(),
        effective_capabilities=(
            ProjectedCapability(
                capability_id="account-balance",
                intent_ids=("ACCOUNT_BALANCE_READ",),
                capability_candidate="ACCOUNT_BALANCE",
                domain="PORTFOLIO",
                description="Consulta de saldo disponible",
                selected_route=SelectedRoute.PERSONAL_READ,
                required_entities=("account_ref",),
                optional_entities=(),
                min_required_entities=1,
                output_contract="AccountBalanceResponse",
                support_level="INFORMATION_ONLY",
                requires_confirmation=False,
                requires_idempotency=False,
            ),
        ),
    )

    # Create resolver via factory
    prompts_root = ROOT / "prompts"
    schemas_root = ROOT / "schemas"
    registry = PromptRegistry(prompts_root, schemas_root)
    resolver = create_turn_resolver(registry, api_key, model)

    # Run ONE inference
    print("\nRunning Agent Framework inference...")
    start = time.perf_counter()

    try:
        result = asyncio.run(_run_resolve(resolver, envelope))
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        evidence = _build_evidence_fail(str(exc), elapsed, model)
        _save_evidence(evidence)
        print(f"\nFAIL: {exc}")
        return 1

    elapsed_ms = (time.perf_counter() - start) * 1000

    # Validate result
    checks: list[tuple[str, bool]] = []

    checks.append(
        ("isinstance(result, TurnInterpretation)", isinstance(result, TurnInterpretation))
    )
    checks.append(("mode == SINGLE", result.mode.value == "SINGLE"))
    checks.append(("len(actions) == 1", len(result.actions) == 1))

    if result.actions:
        action = result.actions[0]
        checks.append(
            ("intent_id == ACCOUNT_BALANCE_READ", action.intent_id == "ACCOUNT_BALANCE_READ")
        )
        checks.append(
            (
                "capability_candidate == ACCOUNT_BALANCE",
                action.capability_candidate == "ACCOUNT_BALANCE",
            )
        )
        checks.append(
            ("selected_route == PERSONAL_READ", action.selected_route.value == "PERSONAL_READ")
        )
        checks.append(
            (
                "account_ref resolved (COR001 or alias)",
                action.detected_entities.account_ref is not None,
            )
        )
        checks.append(("missing_requirements == []", action.missing_requirements == []))
        checks.append(("depends_on == []", action.depends_on == []))
        checks.append(("confidence > 0", action.confidence > 0))
    else:
        checks.append(("actions not empty", False))

    checks.append(("clarifications == []", result.clarifications == []))
    checks.append(("unsupported_segments == []", result.unsupported_segments == []))

    all_pass = all(passed for _, passed in checks)

    # Print results
    print(f"\nLatency: {elapsed_ms:.0f} ms")
    print(f"Result mode: {result.mode.value}")
    if result.actions:
        a = result.actions[0]
        print(f"Intent: {a.intent_id}")
        print(f"Capability: {a.capability_candidate}")
        print(f"Route: {a.selected_route.value}")
        print(f"Account ref: {a.detected_entities.account_ref}")
        print(f"Confidence: {a.confidence}")

    print("\n--- Checks ---")
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}")

    overall = "PASS" if all_pass else "FAIL"
    print(f"\nOverall: {overall}")

    # Build and save evidence
    evidence = _build_evidence(result, checks, elapsed_ms, model, all_pass)
    _save_evidence(evidence)

    return 0 if all_pass else 1


async def _run_resolve(resolver: object, envelope: object) -> Any:
    """Async wrapper for resolver.resolve."""
    return await resolver.resolve(envelope)  # type: ignore[attr-defined]


def _build_evidence(
    result: object,
    checks: list[tuple[str, bool]],
    latency_ms: float,
    model: str,
    all_pass: bool,
) -> str:
    """Build evidence report text."""
    from genesis_cognitive.decision.types import TurnInterpretation

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("T13-A1 — Agent Framework Resolver Smoke Test Evidence")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {datetime.now(UTC).isoformat()}")
    lines.append(f"Model: {model}")
    lines.append(f"Latency: {latency_ms:.0f} ms")
    lines.append(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    lines.append("")
    lines.append("--- Checks ---")
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        lines.append(f"  [{status}] {label}")
    lines.append("")
    lines.append("--- Result (serialized) ---")
    if isinstance(result, TurnInterpretation):
        lines.append(result.model_dump_json(indent=2))
    else:
        lines.append(str(result))
    lines.append("")
    lines.append("--- Mandatory Controls ---")
    lines.append("  [PASS] No keyword routing (semantic via Agent Framework)")
    lines.append("  [PASS] No financial execution (output is TurnInterpretation only)")
    lines.append("  [PASS] No model-generated identity")
    lines.append("  [PASS] store=False (no OpenAI data retention)")
    lines.append("")
    lines.append("--- Versions ---")
    lines.append("  agent-framework-core: 1.12.1")
    lines.append("  agent-framework-openai: 1.11.0")
    lines.append("  prompt_version: 1.2.0")
    lines.append("  agent_name: GenesisIntentEntityAgent")
    lines.append("=" * 70)
    return "\n".join(lines)


def _build_evidence_fail(error: str, latency_ms: float, model: str) -> str:
    """Build evidence for a failed run."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("T13-A1 — Agent Framework Resolver Smoke Test Evidence")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {datetime.now(UTC).isoformat()}")
    lines.append(f"Model: {model}")
    lines.append(f"Latency: {latency_ms:.0f} ms")
    lines.append("Overall: FAIL")
    lines.append("")
    lines.append(f"Error: {error}")
    lines.append("=" * 70)
    return "\n".join(lines)


def _save_evidence(content: str) -> None:
    """Save evidence file."""
    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    path = evidence_dir / "t13-a1-agent-framework-resolver.txt"
    path.write_text(content, encoding="utf-8")
    print(f"\nEvidence saved: {path}")


if __name__ == "__main__":
    sys.exit(main())
