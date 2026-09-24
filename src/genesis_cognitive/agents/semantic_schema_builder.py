"""Builds contextual JSON Schema for ModelSemanticProposal from authorized context."""

from __future__ import annotations

from typing import Any

from genesis_cognitive.model_input.model_input_builder import ModelInputEnvelope


def build_semantic_proposal_schema(model_input: ModelInputEnvelope) -> dict[str, Any]:
    """Generate a JSON Schema restricting values to authorized context.

    Derives enums from:
    - model_input.effective_capabilities → capability_id, intent_id
    - model_input.portfolio → product_ref for account fields
    """
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
            "non_operational_message",
            "unsupported_segments",
        ],
        "properties": {
            "result_type": {
                "type": "string",
                "enum": ["ACTIONS", "NON_OPERATIONAL", "UNSUPPORTED"],
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
            "non_operational_message": {"type": ["string", "null"]},
            "unsupported_segments": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def build_response_format(model_input: ModelInputEnvelope) -> dict[str, Any]:
    """Build the complete response_format dict for ChatOptions."""
    schema = build_semantic_proposal_schema(model_input)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ModelSemanticProposal",
            "strict": True,
            "schema": schema,
        },
    }
