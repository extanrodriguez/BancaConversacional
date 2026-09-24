r"""Run the ContractInspector demo — Azure OpenAI + session.

Usage:
    .\.venv\Scripts\python.exe scripts/run_contract_inspector.py

Environment variables (loaded from .env if python-dotenv installed):
    GENESIS_HOST       (default 0.0.0.0)
    GENESIS_PORT       (default 8445, range 8440-8449, NEVER 8443)
    GENESIS_ENV        (default dev)
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_CHAT_DEPLOYMENT
    AZURE_OPENAI_API_VERSION
    GENESIS_SQLITE_PATH

Does NOT execute financial operations.
"""

from __future__ import annotations

import os
import sys

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Load .env if python-dotenv available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Azure config from env (fallback to hardcoded dev values)
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://aoai-genesis-871a5b-7e0e0.openai.azure.com/")
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")


def main() -> None:
    """Build pipeline with Azure OpenAI API-key auth and run uvicorn."""
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatCompletionClient

    from genesis_cognitive.agents.agent_framework_turn_resolver import (
        AgentFrameworkTurnResolver,
    )
    from genesis_cognitive.agents.model_cognitive_result import ModelSemanticProposal
    from genesis_cognitive.context.adapters.in_memory_capability_context import (
        InMemoryCapabilityContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_conversation_context import (
        InMemoryConversationContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_pending_operation_context import (
        InMemoryPendingOperationContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_portfolio_context import (
        InMemoryPortfolioContextProvider,
    )
    from genesis_cognitive.context.context_assembler import ContextAssembler
    from genesis_cognitive.context.context_types import PortfolioContext
    from genesis_cognitive.context.types import PortfolioProduct, PortfolioSnapshot
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.demo.contract_inspector_app import create_app
    from genesis_cognitive.enums import FreshnessState, OperationalState
    from genesis_cognitive.model_input.model_input_builder import ModelInputBuilder
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry
    from genesis_cognitive.validation.input_validator import InputValidator

    # Prompt
    registry = PromptRegistry(PROJECT_ROOT / "prompts", PROJECT_ROOT / "schemas")
    pv = registry.get_current("turn-decision-agent")
    instructions = (
        f"{pv.instructions.role}\n\n"
        "Objectives:\n" + "\n".join(f"- {o}" for o in pv.instructions.objectives) + "\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in pv.instructions.prohibitions)
    )

    # Azure OpenAI client with API-key auth (safe for non-interactive systemd).
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("AZURE_OPENAI_API_KEY is required for the 8446 service")
    client = OpenAIChatCompletionClient(
        model=AZURE_DEPLOYMENT,
        azure_endpoint=AZURE_ENDPOINT,
        api_version=AZURE_API_VERSION,
        api_key=api_key,
    )
    agent: Agent[ModelSemanticProposal] = Agent(
        client, instructions=instructions, name="GenesisIntentEntityAgent"
    )

    # Verifier agent (second opinion)
    from genesis_cognitive.agents.semantic_verifier import SemanticVerifier

    verifier_reg = PromptRegistry(PROJECT_ROOT / "prompts", PROJECT_ROOT / "schemas")
    verifier_pv = verifier_reg.get_current("semantic-verifier-agent")
    verifier_instructions = (
        f"{verifier_pv.instructions.role}\n\n"
        "Objectives:\n" + "\n".join(f"- {o}" for o in verifier_pv.instructions.objectives) + "\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in verifier_pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in verifier_pv.instructions.prohibitions)
    )
    verifier_agent = Agent(
        client, instructions=verifier_instructions, name="GenesisSemanticVerifierAgent"
    )
    verifier = SemanticVerifier(verifier_agent)

    resolver = AgentFrameworkTurnResolver(agent, verifier=verifier)  # type: ignore[arg-type]

    # Domain Router classifiers (parallel scorers)
    from genesis_cognitive.router.domain_classifier import (
        BusinessClassifier,
        OodClassifier,
        OwnProductClassifier,
    )

    own_product_pv = registry.get_current("domain-own-product")
    own_product_instructions = (
        f"{own_product_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in own_product_pv.instructions.rules)
    )
    own_product_agent = Agent(client, instructions=own_product_instructions, name="DomainOwnProduct")
    own_classifier = OwnProductClassifier(own_product_agent)

    business_pv = registry.get_current("domain-business")
    business_instructions = (
        f"{business_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in business_pv.instructions.rules)
    )
    business_agent = Agent(client, instructions=business_instructions, name="DomainBusiness")
    business_classifier = BusinessClassifier(business_agent)

    ood_pv = registry.get_current("domain-ood")
    ood_instructions = (
        f"{ood_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in ood_pv.instructions.rules)
    )
    ood_agent = Agent(client, instructions=ood_instructions, name="DomainOod")
    ood_classifier = OodClassifier(ood_agent)

    # Product specialists classifiers (Capa 1)
    from genesis_cognitive.router.product_classifiers import (
        ProductMutationClassifier,
        ProductReadClassifier,
    )

    product_read_pv = registry.get_current("product-read")
    product_read_instructions = (
        f"{product_read_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in product_read_pv.instructions.rules)
    )
    product_read_agent = Agent(client, instructions=product_read_instructions, name="ProductRead")
    product_read_clf = ProductReadClassifier(product_read_agent)

    product_mutation_pv = registry.get_current("product-mutation")
    product_mutation_instructions = (
        f"{product_mutation_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in product_mutation_pv.instructions.rules)
    )
    product_mutation_agent = Agent(client, instructions=product_mutation_instructions, name="ProductMutation")
    product_mutation_clf = ProductMutationClassifier(product_mutation_agent)

    # Final Response Agent
    from genesis_cognitive.router.final_response_agent import FinalResponseAgent

    final_resp_pv = registry.get_current("final-response")
    final_resp_instructions = (
        f"{final_resp_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in final_resp_pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in final_resp_pv.instructions.prohibitions)
    )
    final_resp_agent_inst = Agent(client, instructions=final_resp_instructions, name="FinalResponse")
    final_response_agent = FinalResponseAgent(final_resp_agent_inst)

    # Pipeline components
    now = datetime.now(tz=UTC)
    portfolio_data = {
        "demo-customer": PortfolioContext(
            snapshot=PortfolioSnapshot(
                version="demo-v1",
                generated_at=now,
                fresh_until=now + timedelta(minutes=5),
                freshness_state=FreshnessState.FRESH,
                products=(
                    PortfolioProduct(
                        product_ref="COR001",
                        product_type="CHECKING",
                        label="Cuenta corriente",
                        alias="cuenta principal",
                        currency="DOP",
                        operational_state=OperationalState.ACTIVE,
                        recent_balance=Decimal("12500.75"),
                        known_reserved_amount=Decimal("500.00"),
                        balance_as_of=now,
                    ),
                    PortfolioProduct(
                        product_ref="AHO001",
                        product_type="SAVINGS",
                        label="Cuenta de ahorros",
                        alias="mis ahorros",
                        currency="DOP",
                        operational_state=OperationalState.ACTIVE,
                        recent_balance=Decimal("3200.25"),
                        known_reserved_amount=Decimal("0"),
                        balance_as_of=now,
                    ),
                ),
            )
        )
    }

    context_assembler = ContextAssembler(
        InMemoryConversationContextProvider(),
        InMemoryPortfolioContextProvider(data=portfolio_data),
        InMemoryPendingOperationContextProvider(),
        InMemoryCapabilityContextProvider(CapabilityCatalog()),
    )

    app = create_app(
        resolver=resolver,
        gate=SemanticContractGate(),
        input_validator=InputValidator(),
        context_assembler=context_assembler,
        model_input_builder=ModelInputBuilder(),
        azure_model=AZURE_DEPLOYMENT,
        prompt_version=pv.prompt_version,
        db_path=Path(os.getenv("GENESIS_SQLITE_PATH", str(PROJECT_ROOT / "data" / "demo" / "modelo_bancario_genesis_v2.sqlite"))),
        domain_classifiers=(own_classifier, business_classifier, ood_classifier),
        product_classifiers=(product_read_clf, product_mutation_clf),
        final_response_agent=final_response_agent,
    )

    import uvicorn

    host = os.getenv("GENESIS_HOST", "0.0.0.0")
    port = int(os.getenv("GENESIS_PORT", "8445"))
    # Safety: port must be in allowed range, NEVER 8443
    if port == 8443 or port < 8440 or port > 8449:
        print(f"ERROR: GENESIS_PORT={port} not in allowed range 8440-8449 (excluding 8443). Defaulting to 8445.")
        port = 8445

    genesis_env = os.getenv("GENESIS_ENV", "dev")

    print("=" * 60)
    print("Genesis Contract Inspector")
    print("=" * 60)
    print(f"Environment:    {genesis_env}")
    print(f"Provider:       AZURE_OPENAI")
    print(f"Authentication: API_KEY")
    print(f"Deployment:     {AZURE_DEPLOYMENT}")
    print(f"Endpoint:       {AZURE_ENDPOINT[:50]}...")
    print(f"API Version:    {AZURE_API_VERSION}")
    print(f"Framework:      MICROSOFT_AGENT_FRAMEWORK")
    print(f"Prompt:         {pv.prompt_version}")
    print(f"Host:           {host}")
    print(f"Port:           {port}")
    print("=" * 60)
    print(f"URL: http://{host}:{port}")
    print("Press Ctrl+C to stop.\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
