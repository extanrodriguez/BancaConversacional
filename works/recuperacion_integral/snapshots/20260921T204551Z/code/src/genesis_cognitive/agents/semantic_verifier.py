"""SemanticVerifier — second agent that validates and refines the initial proposal."""

from __future__ import annotations

import json
from typing import Any, Literal

from agent_framework import Agent, ChatOptions, Message
from pydantic import BaseModel, ConfigDict, Field

from genesis_cognitive.agents.model_cognitive_result import ModelSemanticProposal
from genesis_cognitive.agents.semantic_schema_builder import build_semantic_proposal_schema
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError
from genesis_cognitive.model_input.model_input_builder import ModelInputEnvelope

# Strings the model sometimes emits instead of JSON null
_NULL_STRINGS_V = {"null", "none", "None", "NULL", "n/a", "N/A", ""}


def _normalize_null_strings_v(entities: dict[str, Any]) -> dict[str, str | None]:
    """Convert string 'null'/'None'/'' to Python None in entity dicts."""
    return {
        k: (None if isinstance(v, str) and v.strip() in _NULL_STRINGS_V else v)
        for k, v in entities.items()
    }


class VerifiedActionProposal(BaseModel):
    """A verified action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    sequence: int = Field(ge=1)
    capability_id: str
    intent_id: str
    detected_entities: dict[str, str | None]
    depends_on: tuple[int, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


class VerifiedSemanticProposal(BaseModel):
    """Output of the semantic verifier. Strict, frozen, extra=forbid."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    result_type: Literal["ACTIONS", "CLARIFICATION", "NON_OPERATIONAL", "UNSUPPORTED"]
    actions: tuple[VerifiedActionProposal, ...] = ()
    clarification_question: str | None = None
    non_operational_message: str | None = None
    unsupported_segments: tuple[str, ...] = ()
    verification_notes: tuple[str, ...] = ()


def _build_verifier_schema(model_input: ModelInputEnvelope) -> dict[str, Any]:
    """Build the JSON schema for the verifier output."""
    capability_ids = sorted({c.capability_id for c in model_input.effective_capabilities})
    intent_ids = sorted(
        {iid for c in model_input.effective_capabilities for iid in c.intent_ids}
    )
    product_refs = sorted({p.product_ref for p in model_input.portfolio})
    ref_enum = product_refs + [None]

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "result_type",
            "actions",
            "clarification_question",
            "non_operational_message",
            "unsupported_segments",
            "verification_notes",
        ],
        "properties": {
            "result_type": {
                "type": "string",
                "enum": ["ACTIONS", "CLARIFICATION", "NON_OPERATIONAL", "UNSUPPORTED"],
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "sequence",
                        "capability_id",
                        "intent_id",
                        "detected_entities",
                        "depends_on",
                        "confidence",
                    ],
                    "properties": {
                        "sequence": {"type": "integer"},
                        "capability_id": {"type": "string", "enum": capability_ids},
                        "intent_id": {"type": "string", "enum": intent_ids},
                        "detected_entities": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "account_ref",
                                "source_account_ref",
                                "destination_account_ref",
                                "amount",
                                "currency",
                                "knowledge_topic",
                            ],
                            "properties": {
                                "account_ref": {"enum": ref_enum},
                                "source_account_ref": {"enum": ref_enum},
                                "destination_account_ref": {"enum": ref_enum},
                                "amount": {"type": ["string", "null"]},
                                "currency": {"type": ["string", "null"]},
                                "knowledge_topic": {"type": ["string", "null"]},
                            },
                        },
                        "depends_on": {"type": "array", "items": {"type": "integer"}},
                        "confidence": {"type": "number"},
                    },
                },
            },
            "clarification_question": {"type": ["string", "null"]},
            "non_operational_message": {"type": ["string", "null"]},
            "unsupported_segments": {"type": "array", "items": {"type": "string"}},
            "verification_notes": {"type": "array", "items": {"type": "string"}},
        },
    }


class SemanticVerifier:
    """Second agent that verifies and refines the initial proposal."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def verify(
        self,
        initial_proposal: ModelSemanticProposal,
        model_input: ModelInputEnvelope,
    ) -> VerifiedSemanticProposal:
        """Verify the initial proposal using the second agent."""
        schema = _build_verifier_schema(model_input)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "VerifiedSemanticProposal",
                "strict": True,
                "schema": schema,
            },
        }

        # Build verification context
        context_data: dict[str, Any] = {
            "raw_text": model_input.raw_text,
            "portfolio": [p.model_dump() for p in model_input.portfolio],
            "effective_capabilities": [
                {"capability_id": c.capability_id, "intent_ids": list(c.intent_ids), "description": c.description}
                for c in model_input.effective_capabilities
            ],
            "initial_proposal": initial_proposal.model_dump(),
        }
        if model_input.pending_action is not None:
            context_data["pending_action"] = model_input.pending_action.model_dump()
        context_msg = json.dumps(context_data, ensure_ascii=False)

        messages: list[Message] = [
            Message(role="user", contents=[context_msg]),
        ]
        from genesis_cognitive.brain.semantic_mode import azure_chat_options, azure_deployment_name

        options = ChatOptions(
            **azure_chat_options(
                response_format=response_format,
                temperature=0,
                deployment=azure_deployment_name(),
            )
        )

        try:
            response = await self._agent.run(messages, options=options)
        except Exception as exc:
            raise InvalidModelOutputError(internal_cause=exc) from exc

        value = response.value
        if value is None:
            raise InvalidModelOutputError()

        # Parse dict to VerifiedSemanticProposal
        if isinstance(value, dict):
            return VerifiedSemanticProposal(
                result_type=value["result_type"],
                actions=tuple(
                    VerifiedActionProposal(
                        sequence=a["sequence"],
                        capability_id=a["capability_id"],
                        intent_id=a["intent_id"],
                        detected_entities=_normalize_null_strings_v(a["detected_entities"]),
                        depends_on=tuple(a.get("depends_on", [])),
                        confidence=a["confidence"],
                    )
                    for a in value.get("actions", [])
                ),
                clarification_question=value.get("clarification_question"),
                non_operational_message=value.get("non_operational_message"),
                unsupported_segments=tuple(value.get("unsupported_segments", [])),
                verification_notes=tuple(value.get("verification_notes", [])),
            )
        raise InvalidModelOutputError()
