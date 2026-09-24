"""ROOT-CAUSE-TRACE-1 — Single inference diagnostic.

Traces the exact boundary where the contradiction originates:
  account_ref = AHO001  AND  missing_requirements = ["account_ref"]

Does NOT modify any production code. Does NOT repair output.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

AZURE_ENDPOINT = "https://aoai-genesis-871a5b-7e0e0.openai.azure.com/"
AZURE_DEPLOYMENT = "gpt-4o-mini"


async def main() -> None:
    from agent_framework import Agent, AgentResponse, ChatOptions, Message
    from agent_framework.openai import OpenAIChatCompletionClient
    from azure.identity import AzureCliCredential

    from genesis_cognitive.agents.agent_framework_turn_resolver import (
        convert_model_result_to_canonical,
    )
    from genesis_cognitive.agents.model_cognitive_result import ModelCognitiveResult
    from genesis_cognitive.context.adapters.in_memory_capability_context import (
        InMemoryCapabilityContextProvider,
    )
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.capability_types import CapabilityQueryContext
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.enums import SelectedRoute
    from genesis_cognitive.model_input.model_input_builder import (
        ModelInputEnvelope,
        ProjectedCapability,
        ProjectedPendingOperation,
        ProjectedProduct,
        ProjectedTurn,
    )
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry

    # --- Build the same envelope as the demo ---
    portfolio = (
        ProjectedProduct(
            product_ref="COR001", product_type="CHECKING",
            label="Cuenta corriente", alias="cuenta principal",
            currency="DOP", operational_state="ACTIVE",
        ),
        ProjectedProduct(
            product_ref="AHO001", product_type="SAVINGS",
            label="Cuenta de ahorros", alias="mis ahorros",
            currency="DOP", operational_state="ACTIVE",
        ),
    )

    # Real effective capabilities (no core.transfer)
    catalog = CapabilityCatalog()
    ctx = CapabilityQueryContext(
        channel="web-demo", authenticated=True,
        authentication_level=None, customer_segment=None,
        app_capabilities=(), orchestrator_capabilities=(),
    )
    manifests = catalog.get_effective_capabilities(ctx)
    effective_caps = tuple(
        ProjectedCapability(
            capability_id=m.capability_id, intent_ids=m.intent_ids,
            capability_candidate=m.capability_candidate, domain=m.domain,
            description=m.description, selected_route=m.selected_route,
            required_entities=m.required_entities, optional_entities=m.optional_entities,
            min_required_entities=m.validation_rules.min_required_entities,
            output_contract=m.output_contract, support_level=m.support_level.value,
            requires_confirmation=m.orchestrator_requirements.requires_confirmation,
            requires_idempotency=m.orchestrator_requirements.requires_idempotency,
        )
        for m in manifests
    )

    envelope = ModelInputEnvelope(
        raw_text="saldo de cuenta de ahorro",
        language="es", locale="es-DO",
        conversation=(), portfolio=portfolio,
        pending_operation=ProjectedPendingOperation(),
        effective_capabilities=effective_caps,
    )

    print(f"effective_capability_ids: {[c.capability_id for c in effective_caps]}")
    print()

    # --- Build agent ---
    registry = PromptRegistry(ROOT / "prompts", ROOT / "schemas")
    pv = registry.get_current("turn-decision-agent")
    instructions = (
        f"{pv.instructions.role}\n\n"
        "Objectives:\n" + "\n".join(f"- {o}" for o in pv.instructions.objectives) + "\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in pv.instructions.prohibitions)
    )

    credential = AzureCliCredential()
    client = OpenAIChatCompletionClient(
        model=AZURE_DEPLOYMENT,
        azure_endpoint=AZURE_ENDPOINT,
        api_version="2024-12-01-preview",
        credential=credential,
    )
    agent = Agent(client, instructions=instructions, name="GenesisIntentEntityAgent")

    # === A. RESPONSE FORMAT ===
    print("=" * 60)
    print("A. RESPONSE FORMAT")
    print(f"  response_format_class: {ModelCognitiveResult.__name__}")
    print(f"  response_format_module: {ModelCognitiveResult.__module__}")
    schema = ModelCognitiveResult.model_json_schema()
    print(f"  response_format_schema_json:")
    print(f"  {json.dumps(schema, indent=2, ensure_ascii=False)[:2000]}")
    print()

    # === RUN INFERENCE ===
    messages = [Message(role="user", contents=[envelope.model_dump_json()])]
    options = ChatOptions(response_format=ModelCognitiveResult, temperature=0)

    print("Running inference...")
    response = await agent.run(messages, options=options)

    # === B. DIRECT AGENT RESPONSE ===
    print("=" * 60)
    print("B. RESPUESTA DIRECTA DEL AGENTE")
    print(f"  agent_response_type: {type(response).__name__}")
    value = response.value
    print(f"  response_value_type: {type(value).__name__}")
    value_json = value.model_dump_json(indent=2) if value else "None"
    print(f"  response_value_model_dump_json:")
    print(f"  {value_json}")
    print()

    # === C. CONVERSION ===
    print("=" * 60)
    print("C. CONVERSION")
    print(f"  converter: convert_model_result_to_canonical")
    print(f"  converter_input_json:")
    print(f"  {value_json}")
    print()

    try:
        result = convert_model_result_to_canonical(value)
        if result.interpretation:
            out_json = result.interpretation.model_dump_json(indent=2)
        else:
            out_json = f"None (status={result.status})"
        print(f"  converter_output_json:")
        print(f"  {out_json}")
    except Exception as exc:
        print(f"  converter_exception_type: {type(exc).__name__}")
        print(f"  converter_exception_message: {exc}")
        print(f"  converter_exception_traceback:")
        traceback.print_exc()
        print()
        print("=" * 60)
        print("CONCLUSION: ORIGEN_CONVERTIDOR")
        return

    # === D. CANONICAL ===
    print()
    print("=" * 60)
    print("D. CONTRATO CANONICO")
    if result.interpretation:
        print(f"  canonical_turn_interpretation_json:")
        print(f"  {result.interpretation.model_dump_json(indent=2)}")
    else:
        print(f"  interpretation: None (status={result.status})")

    # === E. GATE ===
    print()
    print("=" * 60)
    print("E. GATE")
    if result.interpretation and result.interpretation.actions:
        gate = SemanticContractGate()
        validated = gate.validate(result.interpretation, envelope)
        print(f"  catalog_valid: {validated.catalog_valid}")
        print(f"  entity_refs_valid: {validated.entity_refs_valid}")
        print(f"  violations: {list(validated.violations)}")
    else:
        print("  (no actions to validate)")

    # === CONCLUSION ===
    print()
    print("=" * 60)
    print("CONCLUSION")
    if value:
        dump = value.model_dump()
        # Check if model output itself contains the contradiction
        if dump.get("result_type") == "OPERATIONAL":
            for a in dump.get("actions", []):
                ent = a.get("detected_entities", {})
                missing = a.get("missing_requirements", [])
                if ent.get("account_ref") and "account_ref" in missing:
                    print("  ORIGEN_MODELO_O_TRANSPORTE")
                    print("  El modelo devolvio simultaneamente:")
                    print(f"    account_ref = {ent['account_ref']}")
                    print(f"    missing_requirements = {missing}")
                    print("  Archivo responsable: Azure gpt-4o-mini output")
                    print("  Funcion: agent.run() → response.value")
                    return
        if dump.get("result_type") == "CLARIFICATION":
            pa = dump.get("partial_action", {})
            ent = pa.get("detected_entities", {})
            missing = pa.get("missing_requirements", [])
            if ent.get("account_ref") and "account_ref" in missing:
                print("  ORIGEN_MODELO_O_TRANSPORTE")
                print("  El modelo devolvio simultaneamente:")
                print(f"    account_ref = {ent['account_ref']}")
                print(f"    missing_requirements = {missing}")
                print("  Archivo responsable: Azure gpt-4o-mini output")
                print("  Funcion: agent.run() → response.value")
                return

    print("  (unable to determine automatically — review output above)")


if __name__ == "__main__":
    asyncio.run(main())
