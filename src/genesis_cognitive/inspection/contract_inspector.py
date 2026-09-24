"""ContractInspector — orchestrates resolver + gate for inspection.

Performs a single inference, validates the result, and returns a structured
inspection result with contract information. No keyword routing, no financial execution.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from genesis_cognitive.agents.agent_framework_turn_resolver import AgentFrameworkTurnResolver
from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
from genesis_cognitive.decision.types import TurnInterpretation
from genesis_cognitive.model_input.model_input_builder import ModelInputEnvelope


class ContractInspectionResult(BaseModel):
    """Complete inspection result from resolver + gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str
    mode: str
    raw_interpretation: TurnInterpretation
    catalog_valid: bool
    entity_refs_valid: bool
    violations: tuple[str, ...]
    output_contracts: tuple[str, ...]
    overall_status: str  # "VALID" or "INVALID"
    rag_status: str  # "RAG_PENDING" or "NOT_REQUIRED"
    inference_count: int  # always 1


class ContractInspector:
    """Orchestrates AgentFrameworkTurnResolver + SemanticContractGate.

    Performs exactly ONE model inference per inspect() call.
    Does NOT route by keywords, execute financial operations, or generate identity.
    """

    def __init__(
        self,
        resolver: AgentFrameworkTurnResolver,
        gate: SemanticContractGate,
    ) -> None:
        self._resolver = resolver
        self._gate = gate

    async def inspect(
        self, question: str, base_input: ModelInputEnvelope
    ) -> ContractInspectionResult:
        """Inspect a question against the base model input.

        Steps:
        1. Copy base_input with new raw_text.
        2. Call resolver.resolve() ONCE.
        3. Pass result to gate.validate().
        4. Determine output_contracts from matching capabilities.
        5. Determine overall_status and rag_status.
        6. Return structured result.
        """
        # 1. Copy base_input with new raw_text
        model_input = base_input.model_copy(update={"raw_text": question})

        # 2. Call resolver ONCE
        interpretation: TurnInterpretation = await self._resolver.resolve(model_input)

        # 3. Validate
        validated = self._gate.validate(interpretation, model_input)

        # 4. Determine output_contracts
        output_contracts = self._resolve_output_contracts(interpretation, model_input)

        # 5. Determine overall_status and rag_status
        overall_status = (
            "VALID" if validated.catalog_valid and validated.entity_refs_valid else "INVALID"
        )
        rag_status = self._determine_rag_status(interpretation)

        return ContractInspectionResult.model_construct(
            question=question,
            mode=interpretation.mode.value,
            raw_interpretation=interpretation,
            catalog_valid=validated.catalog_valid,
            entity_refs_valid=validated.entity_refs_valid,
            violations=validated.violations,
            output_contracts=output_contracts,
            overall_status=overall_status,
            rag_status=rag_status,
            inference_count=1,
        )

    def _resolve_output_contracts(
        self,
        interpretation: TurnInterpretation,
        model_input: ModelInputEnvelope,
    ) -> tuple[str, ...]:
        """For each action, find the matching capability and get its output_contract."""
        contracts: list[str] = []
        for action in interpretation.actions:
            for cap in model_input.effective_capabilities:
                if (
                    action.intent_id in cap.intent_ids
                    and cap.capability_candidate == action.capability_candidate
                    and cap.selected_route.value == action.selected_route.value
                ):
                    contracts.append(cap.output_contract)
                    break
            else:
                contracts.append("UNKNOWN")
        return tuple(contracts)

    def _determine_rag_status(self, interpretation: TurnInterpretation) -> str:
        """If any action has intent_id containing 'BUSINESS_KNOWLEDGE', return RAG_PENDING."""
        for action in interpretation.actions:
            if "BUSINESS_KNOWLEDGE" in action.intent_id:
                return "RAG_PENDING"
        return "NOT_REQUIRED"
