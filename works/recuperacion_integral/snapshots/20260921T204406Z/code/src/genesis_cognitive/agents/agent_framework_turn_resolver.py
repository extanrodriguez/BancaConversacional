"""AgentFrameworkTurnResolver â€” resolves a turn via Microsoft Agent Framework.

The model produces ModelSemanticProposal (capability_id + intent_id + entities).
The assembler derives all contractual fields deterministically from the
authorized capability manifest. No keyword routing. No financial execution.
"""

from __future__ import annotations

from typing import Any

from agent_framework import Agent, AgentResponse, ChatOptions, Message

from genesis_cognitive.agents.model_cognitive_result import (
    ModelActionProposal,
    ModelDetectedEntities,
    ModelSemanticProposal,
)
from genesis_cognitive.agents.semantic_schema_builder import build_response_format
from genesis_cognitive.agents.semantic_verifier import (
    SemanticVerifier,
    VerifiedSemanticProposal,
)
from genesis_cognitive.decision.types import (
    ClarificationRequest,
    DetectedEntities,
    SemanticAction,
    TurnInterpretation,
    UnsupportedSegment,
)
from genesis_cognitive.enums import InterpretationMode, SelectedRoute
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputEnvelope,
    ProjectedCapability,
)
from genesis_cognitive.prompts.prompt_registry import PromptRegistry
from genesis_cognitive.telemetry.llm_call_timer import LlmCallRecord, time_llm_call

_ENTITY_FIELD_ORDER = (
    "account_ref",
    "source_account_ref",
    "destination_account_ref",
    "amount",
    "currency",
    "knowledge_topic",
)

# Strings the model sometimes emits instead of JSON null
_NULL_STRINGS = {"null", "none", "None", "NULL", "n/a", "N/A", ""}


def _normalize_null_strings(entities: dict[str, Any]) -> dict[str, Any]:
    """Convert string 'null'/'None'/'' to Python None in entity dicts."""
    return {
        k: (None if isinstance(v, str) and v.strip() in _NULL_STRINGS else v)
        for k, v in entities.items()
    }


class ResolverResult:
    """Immutable result from the resolver. All fields set at construction."""

    __slots__ = (
        "interpretation",
        "status",
        "non_operational_message",
        "initial_proposal",
        "verified_proposal",
        "call_records",
    )

    def __init__(
        self,
        interpretation: TurnInterpretation | None,
        status: str,
        non_operational_message: str | None = None,
        initial_proposal: ModelSemanticProposal | None = None,
        verified_proposal: VerifiedSemanticProposal | None = None,
        call_records: list[LlmCallRecord] | None = None,
    ) -> None:
        object.__setattr__(self, "interpretation", interpretation)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "non_operational_message", non_operational_message)
        object.__setattr__(self, "initial_proposal", initial_proposal)
        object.__setattr__(self, "verified_proposal", verified_proposal)
        object.__setattr__(self, "call_records", call_records or [])

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("ResolverResult is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ResolverResult is immutable")


class AgentFrameworkTurnResolver:
    """Resolves a cognitive turn using Microsoft Agent Framework.

    Requires both a proposer agent AND a verifier agent.
    Cannot be constructed without a verifier.
    """

    def __init__(self, agent: Agent[Any], verifier: SemanticVerifier) -> None:
        self._agent = agent
        self._verifier = verifier

    async def resolve(self, model_input: ModelInputEnvelope) -> TurnInterpretation:
        """Returns canonical TurnInterpretation or raises."""
        result = await self.resolve_full(model_input)
        if result.interpretation is None:
            raise InvalidModelOutputError()
        return result.interpretation

    async def resolve_full(self, model_input: ModelInputEnvelope) -> ResolverResult:
        """Full resolution: proposer → verifier → assembler."""
        from agent_framework.exceptions import ChatClientException

        call_records: list[LlmCallRecord] = []

        # 1. Proposer: contextual schema
        response_format = build_response_format(model_input)
        messages: list[Message] = [
            Message(role="user", contents=[model_input.model_dump_json()]),
        ]
        try:
            from genesis_cognitive.brain.semantic_mode import (
                azure_chat_options,
                azure_deployment_name,
            )
            _deploy = azure_deployment_name()
            options = ChatOptions(
                **azure_chat_options(
                    response_format=response_format,
                    temperature=0,
                    deployment=_deploy,
                )
            )
            proposer_record, response = await time_llm_call(
                name="proposer",
                coro=self._agent.run(messages, options=options),
                deployment=_deploy,
            )
            call_records.append(proposer_record)
        except ChatClientException as exc:
            from genesis_cognitive.errors.cognitive_errors import ModelInvocationError
            raise ModelInvocationError(internal_cause=exc) from exc

        # Parse raw dict to ModelSemanticProposal
        raw_value = response.value
        if raw_value is None:
            raise InvalidModelOutputError()

        try:
            if isinstance(raw_value, dict):
                initial = ModelSemanticProposal(
                    result_type=raw_value["result_type"],
                    actions=tuple(
                        ModelActionProposal(
                            sequence=a["sequence"],
                            capability_id=a["capability_id"],
                            intent_id=a["intent_id"],
                            detected_entities=ModelDetectedEntities(**_normalize_null_strings(a["detected_entities"])),
                            depends_on=tuple(a.get("depends_on", [])),
                            confidence=a["confidence"],
                        )
                        for a in raw_value.get("actions", [])
                    ),
                    non_operational_message=raw_value.get("non_operational_message"),
                    unsupported_segments=tuple(raw_value.get("unsupported_segments", [])),
                )
            elif isinstance(raw_value, ModelSemanticProposal):
                initial = raw_value
            else:
                raise InvalidModelOutputError()
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidModelOutputError(internal_cause=exc) from exc

        # 2. Verifier (mandatory) — timed
        try:
            verifier_record, verified = await time_llm_call(
                name="verifier",
                coro=self._verifier.verify(initial, model_input),
                deployment=_deploy,
            )
            call_records.append(verifier_record)
        except ChatClientException as exc:
            from genesis_cognitive.errors.cognitive_errors import ModelInvocationError

            raise ModelInvocationError(internal_cause=exc) from exc
        except InvalidModelOutputError:
            raise

        if verified is None:
            raise InvalidModelOutputError()

        # 3. Validate branch invariants
        _validate_branch_invariants(verified)

        # 4. Assemble (no fallback, no mutation)
        try:
            result = _assemble_from_verified(verified, model_input)
        except InvalidModelOutputError:
            raise

        # Return immutable result with all proposals + call records
        return ResolverResult(
            interpretation=result.interpretation,
            status=result.status,
            non_operational_message=result.non_operational_message,
            initial_proposal=initial,
            verified_proposal=verified,
            call_records=call_records,
        )


def _validate_branch_invariants(verified: VerifiedSemanticProposal) -> None:
    """Validate that the verified proposal has coherent branch structure."""
    rt = verified.result_type

    if rt == "ACTIONS":
        if not verified.actions:
            raise InvalidModelOutputError()
    elif rt == "CLARIFICATION":
        # actions can be empty for pure disambiguation; assembler handles both cases
        pass
    elif rt == "NON_OPERATIONAL":
        if verified.actions:
            raise InvalidModelOutputError()
        if not verified.non_operational_message:
            raise InvalidModelOutputError()
    elif rt == "UNSUPPORTED":
        if verified.actions:
            raise InvalidModelOutputError()
        if not verified.unsupported_segments:
            raise InvalidModelOutputError()
    else:
        raise InvalidModelOutputError()


def _assemble_from_verified(
    verified: VerifiedSemanticProposal,
    model_input: ModelInputEnvelope,
) -> ResolverResult:
    """Assemble canonical interpretation from verified proposal."""
    rt = verified.result_type

    if rt == "NON_OPERATIONAL":
        return ResolverResult(
            interpretation=None,
            status="NON_OPERATIONAL",
            non_operational_message=verified.non_operational_message or "",
        )

    if rt == "UNSUPPORTED":
        reasons = verified.unsupported_segments or ("Solicitud no soportada",)
        segments = [
            UnsupportedSegment(segment_description=r, reason="No soportado")
            for r in reasons
        ]
        ti = TurnInterpretation(
            mode=InterpretationMode.UNSUPPORTED,
            actions=[],
            clarifications=[],
            unsupported_segments=segments,
        )
        return ResolverResult(interpretation=ti, status="UNSUPPORTED")

    if rt == "CLARIFICATION":
        if not verified.actions:
            return ResolverResult(interpretation=None, status="CLARIFICATION_REQUIRED")
        # Build partial action from verified
        vp = verified.actions[0]
        cap = _find_capability(vp.capability_id, vp.intent_id, model_input.effective_capabilities)
        if cap is None:
            raise InvalidModelOutputError()
        entities = DetectedEntities(
            account_ref=vp.detected_entities.get("account_ref"),
            source_account_ref=vp.detected_entities.get("source_account_ref"),
            destination_account_ref=vp.detected_entities.get("destination_account_ref"),
            amount=vp.detected_entities.get("amount"),
            currency=vp.detected_entities.get("currency"),
            knowledge_topic=vp.detected_entities.get("knowledge_topic"),
        )
        non_null = {k for k, v in entities.model_dump().items() if v is not None}
        required = set(cap.required_entities)
        missing = sorted(required - non_null)
        already_known = [f for f in _ENTITY_FIELD_ORDER if f in non_null]

        # T6 guard: verifier said CLARIFICATION but all required entities present.
        # Exception: capability has no required_entities by design (disambiguation case);
        # use "query_scope" as synthetic disambiguation requirement and switch to
        # the clarification capability to avoid false RAG_PENDING status.
        if not missing:
            if not cap.required_entities and verified.clarification_question:
                # Disambiguation clarification (e.g. personal vs business/catalog)
                # Switch to clarification capability
                clar_cap = _find_capability(
                    "clarification", "CLARIFICATION_REQUIRED", model_input.effective_capabilities
                )
                if clar_cap is None:
                    raise InvalidModelOutputError()
                missing = ["query_scope"]
                # Clear entities that don't belong in disambiguation
                entities = DetectedEntities()
                non_null = set()
                already_known = []
                cap = clar_cap
            else:
                raise InvalidModelOutputError()

        action = SemanticAction(
            sequence=vp.sequence,
            intent_id=cap.intent_ids[0] if cap.intent_ids else vp.intent_id,
            capability_candidate=cap.capability_candidate,
            selected_route=cap.selected_route,
            detected_entities=entities,
            missing_requirements=missing,
            depends_on=list(vp.depends_on),
            confidence=vp.confidence,
        )
        question = verified.clarification_question or "Necesito mas informacion."
        clar = ClarificationRequest(
            target_action_sequence=vp.sequence,
            missing_requirements=missing,
            suggested_question=question,
            already_known=already_known,
        )
        ti = TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[action],
            clarifications=[clar],
            unsupported_segments=[],
        )
        return ResolverResult(interpretation=ti, status="CLARIFICATION_REQUIRED")

    if rt == "ACTIONS":
        # Convert to ModelSemanticProposal-compatible and use existing assembler
        proposal = ModelSemanticProposal(
            result_type="ACTIONS",
            actions=tuple(
                ModelActionProposal(
                    sequence=a.sequence,
                    capability_id=a.capability_id,
                    intent_id=a.intent_id,
                    detected_entities=ModelDetectedEntities(
                        account_ref=a.detected_entities.get("account_ref"),
                        source_account_ref=a.detected_entities.get("source_account_ref"),
                        destination_account_ref=a.detected_entities.get("destination_account_ref"),
                        amount=a.detected_entities.get("amount"),
                        currency=a.detected_entities.get("currency"),
                        knowledge_topic=a.detected_entities.get("knowledge_topic"),
                    ),
                    depends_on=a.depends_on,
                    confidence=a.confidence,
                )
                for a in verified.actions
            ),
        )
        return assemble_canonical_interpretation(proposal, model_input)

    raise InvalidModelOutputError()


def assemble_canonical_interpretation(
    proposal: ModelSemanticProposal,
    model_input: ModelInputEnvelope,
) -> ResolverResult:
    """Convert model proposal to canonical interpretation using authorized capabilities.

    Derives all contractual fields from the capability manifest.
    Does NOT read raw_text, alias, or label.
    """
    rt = proposal.result_type

    # --- NON_OPERATIONAL ---
    if rt == "NON_OPERATIONAL":
        if proposal.actions:
            raise InvalidModelOutputError()
        return ResolverResult(
            interpretation=None,
            status="NON_OPERATIONAL",
            non_operational_message=proposal.non_operational_message or "",
        )

    # --- UNSUPPORTED ---
    if rt == "UNSUPPORTED":
        if proposal.actions:
            raise InvalidModelOutputError()
        reasons = proposal.unsupported_segments or ("Solicitud no soportada",)
        segments = [
            UnsupportedSegment(segment_description=r, reason="No soportado")
            for r in reasons
        ]
        ti = TurnInterpretation(
            mode=InterpretationMode.UNSUPPORTED,
            actions=[],
            clarifications=[],
            unsupported_segments=segments,
        )
        return ResolverResult(
            interpretation=ti, status="UNSUPPORTED", 
        )

    # --- ACTIONS ---
    if rt == "ACTIONS":
        if not proposal.actions:
            raise InvalidModelOutputError()
        return _assemble_actions(proposal, model_input)

    raise InvalidModelOutputError()


def _assemble_actions(
    proposal: ModelSemanticProposal,
    model_input: ModelInputEnvelope,
) -> ResolverResult:
    """Assemble canonical actions from model proposals."""
    actions: list[SemanticAction] = []
    clarifications: list[ClarificationRequest] = []
    has_missing = False

    for ap in proposal.actions:
        # Find matching capability
        cap = _find_capability(ap.capability_id, ap.intent_id, model_input.effective_capabilities)
        if cap is None:
            raise InvalidModelOutputError()

        # Build entities
        entities = DetectedEntities(
            account_ref=ap.detected_entities.account_ref,
            source_account_ref=ap.detected_entities.source_account_ref,
            destination_account_ref=ap.detected_entities.destination_account_ref,
            amount=ap.detected_entities.amount,
            currency=ap.detected_entities.currency,
            knowledge_topic=ap.detected_entities.knowledge_topic,
        )

        # Derive already_known and missing_requirements from manifest
        non_null_fields = {
            k for k, v in entities.model_dump().items() if v is not None
        }
        required = set(cap.required_entities)
        missing_requirements = sorted(required - non_null_fields)
        already_known = [f for f in _ENTITY_FIELD_ORDER if f in non_null_fields]

        action = SemanticAction(
            sequence=ap.sequence,
            intent_id=ap.intent_id,
            capability_candidate=cap.capability_candidate,
            selected_route=cap.selected_route,
            detected_entities=entities,
            missing_requirements=missing_requirements,
            depends_on=list(ap.depends_on),
            confidence=ap.confidence,
        )
        actions.append(action)

        if missing_requirements:
            has_missing = True
            clarifications.append(
                ClarificationRequest(
                    target_action_sequence=ap.sequence,
                    missing_requirements=missing_requirements,
                    suggested_question=f"Falta informacion para completar la accion {ap.sequence}.",
                    already_known=already_known,
                )
            )

    # Determine mode
    if has_missing:
        mode = InterpretationMode.CLARIFICATION
        status = "CLARIFICATION_REQUIRED"
    elif len(actions) == 1:
        mode = InterpretationMode.SINGLE
        status = "VALID_CONTRACT"
    elif any(a.depends_on for a in actions):
        mode = InterpretationMode.MULTI_DEPENDENT
        status = "VALID_CONTRACT"
    else:
        mode = InterpretationMode.MULTI_INDEPENDENT
        status = "VALID_CONTRACT"

    # Check RAG
    for a in actions:
        if a.intent_id == "BUSINESS_KNOWLEDGE_QUERY":
            status = "RAG_PENDING"
            break

    ti = TurnInterpretation(
        mode=mode,
        actions=actions,
        clarifications=clarifications,
        unsupported_segments=[],
    )
    return ResolverResult(interpretation=ti, status=status)


def _find_capability(
    capability_id: str,
    intent_id: str,
    capabilities: tuple[ProjectedCapability, ...],
) -> ProjectedCapability | None:
    """Find exact match by capability_id AND intent_id."""
    for cap in capabilities:
        if cap.capability_id == capability_id and intent_id in cap.intent_ids:
            return cap
    return None


def create_turn_resolver(
    prompt_registry: PromptRegistry,
    api_key: str,
    model: str,
) -> AgentFrameworkTurnResolver:
    """Factory for public OpenAI (used by unit tests and preflights)."""
    from agent_framework.openai import OpenAIChatClient

    prompt_version = prompt_registry.get_current("turn-decision-agent")
    instructions = _build_instructions(prompt_version)
    client = OpenAIChatClient(model=model, api_key=api_key)
    agent: Agent[Any] = Agent(
        client, instructions=instructions, name="GenesisIntentEntityAgent"
    )
    return AgentFrameworkTurnResolver(agent)


def _build_instructions(prompt_version: Any) -> str:
    pv = prompt_version
    parts: list[str] = [
        pv.instructions.role,
        "",
        "Objectives:",
        *[f"- {o}" for o in pv.instructions.objectives],
        "",
        "Rules:",
        *[f"- {r}" for r in pv.instructions.rules],
        "",
        "Prohibitions:",
        *[f"- {p}" for p in pv.instructions.prohibitions],
    ]
    return "\n".join(parts)



