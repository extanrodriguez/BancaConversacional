"""ROOT-CAUSE-CATALOG-1 diagnostic — 3 inferences max."""
from __future__ import annotations
import asyncio, json, os, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

AZURE_ENDPOINT = "https://aoai-genesis-871a5b-7e0e0.openai.azure.com/"
AZURE_DEPLOYMENT = "gpt-4o-mini"

async def run_case(question: str, portfolio_order: list[dict[str,str]]) -> None:
    from agent_framework import Agent, ChatOptions, Message
    from agent_framework.openai import OpenAIChatCompletionClient
    from azure.identity import AzureCliCredential
    from genesis_cognitive.agents.agent_framework_turn_resolver import assemble_canonical_interpretation
    from genesis_cognitive.agents.model_cognitive_result import ModelSemanticProposal
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.capability_types import CapabilityQueryContext
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.model_input.model_input_builder import (
        ModelInputEnvelope, ProjectedCapability, ProjectedPendingOperation, ProjectedProduct,
    )
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry

    portfolio = tuple(
        ProjectedProduct(
            product_ref=p["ref"], product_type=p["type"], label=p["label"],
            alias=p["alias"], currency=p["cur"], operational_state="ACTIVE",
        ) for p in portfolio_order
    )
    catalog = CapabilityCatalog()
    ctx = CapabilityQueryContext(
        channel="web-demo", authenticated=True, authentication_level=None,
        customer_segment=None, app_capabilities=(), orchestrator_capabilities=(),
    )
    manifests = catalog.get_effective_capabilities(ctx)
    caps = tuple(
        ProjectedCapability(
            capability_id=m.capability_id, intent_ids=m.intent_ids,
            capability_candidate=m.capability_candidate, domain=m.domain,
            description=m.description, selected_route=m.selected_route,
            required_entities=m.required_entities, optional_entities=m.optional_entities,
            min_required_entities=m.validation_rules.min_required_entities,
            output_contract=m.output_contract, support_level=m.support_level.value,
            requires_confirmation=m.orchestrator_requirements.requires_confirmation,
            requires_idempotency=m.orchestrator_requirements.requires_idempotency,
        ) for m in manifests
    )
    envelope = ModelInputEnvelope(
        raw_text=question, language="es", locale="es-DO", conversation=(),
        portfolio=portfolio, pending_operation=ProjectedPendingOperation(),
        effective_capabilities=caps,
    )
    print(f"  portfolio_product_count: {len(portfolio)}")
    print(f"  portfolio_product_refs: {[p.product_ref for p in portfolio]}")
    print(f"  effective_capability_ids: {[c.capability_id for c in caps]}")
    print(f"  orchestrator_capabilities: ()")
    print(f"  channel: web-demo | authenticated: True")

    reg = PromptRegistry(ROOT/"prompts", ROOT/"schemas")
    pv = reg.get_current("turn-decision-agent")
    instructions = (
        f"{pv.instructions.role}\n\nObjectives:\n"
        + "\n".join(f"- {o}" for o in pv.instructions.objectives)
        + "\n\nRules:\n" + "\n".join(f"- {r}" for r in pv.instructions.rules)
        + "\n\nProhibitions:\n" + "\n".join(f"- {p}" for p in pv.instructions.prohibitions)
    )
    cred = AzureCliCredential()
    client = OpenAIChatCompletionClient(
        model=AZURE_DEPLOYMENT, azure_endpoint=AZURE_ENDPOINT,
        api_version="2024-12-01-preview", credential=cred,
    )
    agent = Agent(client, instructions=instructions, name="GenesisIntentEntityAgent")
    messages = [Message(role="user", contents=[envelope.model_dump_json()])]
    options = ChatOptions(response_format=ModelSemanticProposal, temperature=0)
    resp = await agent.run(messages, options=options)
    proposal = resp.value
    print(f"\n  === ModelSemanticProposal (raw from model) ===")
    print(f"  {proposal.model_dump_json(indent=2)}")

    print(f"\n  === Assembler ===")
    try:
        result = assemble_canonical_interpretation(proposal, envelope)
        if result.interpretation:
            print(f"  status: {result.status}")
            print(f"  TurnInterpretation: {result.interpretation.model_dump_json(indent=2)}")
            gate = SemanticContractGate()
            v = gate.validate(result.interpretation, envelope)
            print(f"\n  === Gate ===")
            print(f"  catalog_valid: {v.catalog_valid}")
            print(f"  entity_refs_valid: {v.entity_refs_valid}")
            print(f"  violations: {list(v.violations)}")
        else:
            print(f"  status: {result.status}")
            print(f"  non_operational_message: {result.non_operational_message}")
    except Exception as e:
        print(f"  ASSEMBLER_ERROR: {type(e).__name__}: {e}")

async def main() -> None:
    products_normal = [
        {"ref":"COR001","type":"CHECKING","label":"Cuenta corriente","alias":"cuenta principal","cur":"DOP"},
        {"ref":"AHO001","type":"SAVINGS","label":"Cuenta de ahorros","alias":"mis ahorros","cur":"DOP"},
    ]
    products_reversed = list(reversed(products_normal))

    print("="*60)
    print("CASO A: Quiero consultar mi saldo.")
    print("="*60)
    await run_case("Quiero consultar mi saldo.", products_normal)

    print("\n\n" + "="*60)
    print("CASO B: Quiero mover dinero entre mis cuentas.")
    print("="*60)
    await run_case("Quiero mover dinero entre mis cuentas.", products_normal)

    print("\n\n" + "="*60)
    print("CASO A (REVERSED): Quiero consultar mi saldo.")
    print("="*60)
    await run_case("Quiero consultar mi saldo.", products_reversed)

if __name__ == "__main__":
    asyncio.run(main())
