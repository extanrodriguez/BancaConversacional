"""Generate all T02 schemas reproducibly.

Rules:
- UTF-8 without BOM
- LF newlines
- Stable indentation (2 spaces)
- Single trailing newline
- All $schema, $id, $defs, $ref correct
"""

import json
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


def write_schema(name: str, schema: dict[str, Any]) -> None:
    path = SCHEMAS_DIR / name
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(schema, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"OK: {name}")


def check_empty_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        assert "" not in value, f"Empty key at {path}"
        for k, v in value.items():
            check_empty_keys(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            check_empty_keys(item, f"{path}[{i}]")


def orchestrator_turn_request() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/schemas/orchestrator_turn_request.schema.json",
        "title": "Orchestrator Turn Request",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "type",
            "conversation_id",
            "customer_id",
            "subject_token",
            "request_id",
            "correlation_id",
            "user_turn",
            "channel_context",
        ],
        "properties": {
            "type": {"const": "USER_MESSAGE"},
            "conversation_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "customer_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "subject_token": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
            },
            "request_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "correlation_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "user_turn": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_text"],
                "properties": {
                    "raw_text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8000,
                    }
                },
            },
            "channel_context": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "channel",
                    "client_slot",
                    "authenticated",
                    "locale",
                ],
                "properties": {
                    "channel": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                    },
                    "client_slot": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                    "authenticated": {"type": "boolean"},
                    "locale": {
                        "type": "string",
                        "minLength": 2,
                        "maxLength": 32,
                        "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$",
                    },
                },
            },
        },
    }


def cognitive_turn_request() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/schemas/cognitive_turn_request.schema.json",
        "title": "Cognitive Turn Request",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "input_type",
            "request_id",
            "correlation_id",
            "conversation_id",
            "session_id",
            "subject_token",
            "customer_id",
            "turn_number",
            "user_turn",
            "session_context",
            "channel_context",
        ],
        "properties": {
            "contract_version": {"const": "1.0"},
            "input_type": {"const": "user_turn"},
            "request_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "correlation_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "conversation_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "session_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "subject_token": {"type": "string", "minLength": 1, "maxLength": 512},
            "customer_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "turn_number": {"type": "integer", "minimum": 1},
            "user_turn": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_text", "language"],
                "properties": {
                    "raw_text": {"type": "string", "minLength": 1, "maxLength": 8000},
                    "language": {
                        "type": "string",
                        "minLength": 2,
                        "maxLength": 3,
                        "pattern": "^[a-z]{2,3}$",
                    },
                },
            },
            "session_context": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "session_status",
                    "recent_turns",
                    "known_products",
                    "pending_operation",
                    "last_operation_request",
                    "last_operation_result",
                ],
                "properties": {
                    "session_status": {"enum": ["ACTIVE", "INACTIVE", "EXPIRED"]},
                    "recent_turns": {
                        "type": "array",
                        "maxItems": 12,
                        "items": {"$ref": "#/$defs/RecentTurn"},
                    },
                    "known_products": {"$ref": "#/$defs/PortfolioSnapshot"},
                    "pending_operation": {"const": None},
                    "last_operation_request": {"const": None},
                    "last_operation_result": {"const": None},
                },
            },
            "channel_context": {
                "type": "object",
                "additionalProperties": False,
                "required": ["channel", "locale", "authenticated", "client_slot"],
                "properties": {
                    "channel": {"type": "string", "minLength": 1, "maxLength": 64},
                    "locale": {"type": "string", "minLength": 2, "maxLength": 32},
                    "authenticated": {"type": "boolean"},
                    "client_slot": {"type": "string", "minLength": 1, "maxLength": 128},
                },
            },
        },
        "$defs": {
            "RecentTurn": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role", "summary"],
                "properties": {
                    "role": {"enum": ["USER", "ASSISTANT"]},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 4000},
                },
            },
            "PortfolioProduct": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "product_ref",
                    "product_type",
                    "label",
                    "alias",
                    "currency",
                    "operational_state",
                    "recent_balance",
                    "known_reserved_amount",
                    "balance_as_of",
                ],
                "properties": {
                    "product_ref": {"type": "string", "minLength": 1},
                    "product_type": {"type": "string", "minLength": 1},
                    "label": {"type": ["string", "null"]},
                    "alias": {"type": ["string", "null"]},
                    "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
                    "operational_state": {"enum": ["ACTIVE", "BLOCKED", "DORMANT"]},
                    "recent_balance": {
                        "type": ["string", "null"],
                        "pattern": "^-?\\d+(\\.\\d+)?$",
                    },
                    "known_reserved_amount": {
                        "type": ["string", "null"],
                        "pattern": "^-?\\d+(\\.\\d+)?$",
                    },
                    "balance_as_of": {
                        "type": ["string", "null"],
                        "format": "date-time",
                    },
                },
            },
            "PortfolioSnapshot": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "version",
                    "generated_at",
                    "fresh_until",
                    "freshness_state",
                    "products",
                ],
                "properties": {
                    "version": {"type": "string", "minLength": 1},
                    "generated_at": {"type": "string", "format": "date-time"},
                    "fresh_until": {"type": "string", "format": "date-time"},
                    "freshness_state": {"enum": ["FRESH", "STALE", "REFRESHING", "UNAVAILABLE"]},
                    "products": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/PortfolioProduct"},
                    },
                },
            },
        },
    }


def error_response() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/schemas/error_response.schema.json",
        "title": "Error Response",
        "type": "object",
        "additionalProperties": False,
        "required": ["error", "error_code", "message", "request_id", "correlation_id"],
        "properties": {
            "error": {"const": True},
            "error_code": {
                "enum": [
                    "INVALID_INPUT",
                    "AUTHENTICATION_REQUIRED",
                    "CONTEXT_PROVIDER_ERROR",
                    "MODEL_INVOCATION_ERROR",
                    "INVALID_MODEL_OUTPUT",
                ]
            },
            "message": {"type": "string"},
            "request_id": {"type": ["string", "null"]},
            "correlation_id": {"type": ["string", "null"]},
        },
        "allOf": [
            {
                "if": {"properties": {"request_id": {"type": "string"}}},
                "then": {"properties": {"request_id": {"minLength": 1}}},
            },
            {
                "if": {"properties": {"correlation_id": {"type": "string"}}},
                "then": {"properties": {"correlation_id": {"minLength": 1}}},
            },
        ],
        "oneOf": [
            {
                "properties": {
                    "error_code": {"const": "INVALID_INPUT"},
                    "message": {"const": "La solicitud no es estructuralmente valida."},
                }
            },
            {
                "properties": {
                    "error_code": {"const": "AUTHENTICATION_REQUIRED"},
                    "message": {"const": "Se requiere autenticacion."},
                }
            },
            {
                "properties": {
                    "error_code": {"const": "CONTEXT_PROVIDER_ERROR"},
                    "message": {"const": "Error al obtener contexto."},
                }
            },
            {
                "properties": {
                    "error_code": {"const": "MODEL_INVOCATION_ERROR"},
                    "message": {"const": "Error al invocar el modelo."},
                }
            },
            {
                "properties": {
                    "error_code": {"const": "INVALID_MODEL_OUTPUT"},
                    "message": {"const": "La respuesta del modelo no es valida."},
                }
            },
        ],
    }


def turn_interpretation() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/schemas/turn_interpretation.schema.json",
        "title": "Turn Interpretation",
        "description": "Structured output from the model (internal). No identity fields.",
        "type": "object",
        "additionalProperties": False,
        "required": ["mode", "actions", "clarifications", "unsupported_segments"],
        "properties": {
            "mode": {
                "enum": [
                    "SINGLE",
                    "MULTI_INDEPENDENT",
                    "MULTI_DEPENDENT",
                    "CLARIFICATION",
                    "UNSUPPORTED",
                    "MIXED",
                ]
            },
            "actions": {"type": "array", "items": {"$ref": "#/$defs/SemanticAction"}},
            "clarifications": {
                "type": "array",
                "items": {"$ref": "#/$defs/ClarificationRequest"},
            },
            "unsupported_segments": {
                "type": "array",
                "items": {"$ref": "#/$defs/UnsupportedSegment"},
            },
        },
        "$defs": {
            "SemanticAction": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "sequence",
                    "intent_id",
                    "capability_candidate",
                    "selected_route",
                    "detected_entities",
                    "missing_requirements",
                    "depends_on",
                    "confidence",
                ],
                "properties": {
                    "sequence": {"type": "integer", "minimum": 1},
                    "intent_id": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 128,
                        "pattern": "^[A-Z][A-Z0-9_]{2,127}$",
                    },
                    "capability_candidate": {
                        "type": ["string", "null"],
                        "pattern": "^[A-Z][A-Z0-9_]{2,127}$",
                    },
                    "selected_route": {
                        "enum": [
                            "BUSINESS_RAG",
                            "PORTFOLIO_QUERY",
                            "PERSONAL_READ",
                            "TRANSFER_CONTRACT_BUILDER",
                            "CLARIFICATION",
                            "UNSUPPORTED",
                        ]
                    },
                    "detected_entities": {"$ref": "#/$defs/DetectedEntities"},
                    "missing_requirements": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                    "depends_on": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "integer", "minimum": 1},
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
            "DetectedEntities": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "account_ref": {"type": ["string", "null"], "minLength": 1},
                    "source_account_ref": {"type": ["string", "null"], "minLength": 1},
                    "destination_account_ref": {"type": ["string", "null"], "minLength": 1},
                    "amount": {
                        "type": ["string", "null"],
                        "pattern": "^\\d+(\\.\\d+)?$",
                    },
                    "currency": {"type": ["string", "null"], "pattern": "^[A-Z]{3}$"},
                    "knowledge_topic": {"type": ["string", "null"], "minLength": 1},
                },
            },
            "ClarificationRequest": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "target_action_sequence",
                    "missing_requirements",
                    "suggested_question",
                    "already_known",
                ],
                "properties": {
                    "target_action_sequence": {"type": "integer", "minimum": 1},
                    "missing_requirements": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                    "suggested_question": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1024,
                    },
                    "already_known": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": [
                                "account_ref",
                                "source_account_ref",
                                "destination_account_ref",
                                "amount",
                                "currency",
                                "knowledge_topic",
                            ],
                        },
                    },
                },
            },
            "UnsupportedSegment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["segment_description", "reason"],
                "properties": {
                    "segment_description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                    },
                    "reason": {"type": "string", "minLength": 1, "maxLength": 512},
                },
            },
        },
    }


def intent_resolution() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/schemas/intent_resolution.schema.json",
        "title": "Intent Resolution",
        "description": "External contract for orchestrator.",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "output_type",
            "request_id",
            "correlation_id",
            "conversation_id",
            "resolver_version",
            "prompt_id",
            "prompt_version",
            "mode",
            "actions",
            "clarifications",
            "unsupported_segments",
        ],
        "properties": {
            "contract_version": {"const": "1.0"},
            "output_type": {"const": "intent_resolution"},
            "request_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "correlation_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "conversation_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "resolver_version": {"type": "string", "minLength": 1, "maxLength": 64},
            "prompt_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "prompt_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
            "mode": {
                "enum": [
                    "SINGLE",
                    "MULTI_INDEPENDENT",
                    "MULTI_DEPENDENT",
                    "CLARIFICATION",
                    "UNSUPPORTED",
                    "MIXED",
                ]
            },
            "actions": {
                "type": "array",
                "items": {"$ref": "#/$defs/ResolvedAction"},
            },
            "clarifications": {
                "type": "array",
                "items": {"$ref": "#/$defs/ResolvedClarification"},
            },
            "unsupported_segments": {
                "type": "array",
                "items": {"$ref": "#/$defs/UnsupportedSegment"},
            },
        },
        "$defs": {
            "ResolvedAction": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "action_id",
                    "sequence",
                    "intent_id",
                    "capability_candidate",
                    "interaction_family",
                    "domain",
                    "selected_route",
                    "next_action",
                    "detected_entities",
                    "missing_requirements",
                    "depends_on_action_ids",
                    "confidence",
                ],
                "properties": {
                    "action_id": {"type": "string", "format": "uuid"},
                    "sequence": {"type": "integer", "minimum": 1},
                    "intent_id": {
                        "type": "string",
                        "pattern": "^[A-Z][A-Z0-9_]{2,127}$",
                    },
                    "capability_candidate": {
                        "type": ["string", "null"],
                        "pattern": "^[A-Z][A-Z0-9_]{2,127}$",
                    },
                    "interaction_family": {
                        "enum": [
                            "KNOWLEDGE",
                            "PORTFOLIO",
                            "PERSONAL_READ",
                            "TRANSACTION",
                            "CLARIFICATION",
                            "UNSUPPORTED",
                        ]
                    },
                    "domain": {
                        "type": "string",
                        "pattern": "^[A-Z][A-Z0-9_]{1,63}$",
                    },
                    "selected_route": {
                        "enum": [
                            "BUSINESS_RAG",
                            "PORTFOLIO_QUERY",
                            "PERSONAL_READ",
                            "TRANSFER_CONTRACT_BUILDER",
                            "CLARIFICATION",
                            "UNSUPPORTED",
                        ]
                    },
                    "next_action": {
                        "enum": [
                            "QUERY_RAG",
                            "QUERY_PORTFOLIO",
                            "BUILD_READ_REQUEST",
                            "BUILD_TYPED_CONTRACT",
                            "ASK_CLARIFICATION",
                            "RETURN_UNSUPPORTED",
                        ]
                    },
                    "detected_entities": {"$ref": "#/$defs/DetectedEntities"},
                    "missing_requirements": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                    "depends_on_action_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "format": "uuid"},
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
            "DetectedEntities": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "account_ref": {"type": ["string", "null"], "minLength": 1},
                    "source_account_ref": {"type": ["string", "null"], "minLength": 1},
                    "destination_account_ref": {"type": ["string", "null"], "minLength": 1},
                    "amount": {
                        "type": ["string", "null"],
                        "pattern": "^\\d+(\\.\\d+)?$",
                    },
                    "currency": {"type": ["string", "null"], "pattern": "^[A-Z]{3}$"},
                    "knowledge_topic": {"type": ["string", "null"], "minLength": 1},
                },
            },
            "ResolvedClarification": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "target_action_id",
                    "missing_requirements",
                    "suggested_question",
                    "already_known",
                ],
                "properties": {
                    "target_action_id": {"type": "string", "format": "uuid"},
                    "missing_requirements": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                    "suggested_question": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1024,
                    },
                    "already_known": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": [
                                "account_ref",
                                "source_account_ref",
                                "destination_account_ref",
                                "amount",
                                "currency",
                                "knowledge_topic",
                            ],
                        },
                    },
                },
            },
            "UnsupportedSegment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["segment_description", "reason"],
                "properties": {
                    "segment_description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                    },
                    "reason": {"type": "string", "minLength": 1, "maxLength": 512},
                },
            },
        },
    }


def capability_manifest() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/schemas/capability_manifest.schema.json",
        "title": "Capability Manifest",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "capability_id",
            "intent_ids",
            "capability_candidate",
            "domain",
            "description",
            "required_entities",
            "optional_entities",
            "skill_or_specialist",
            "output_contract",
            "orchestrator_requirements",
            "app_requirements",
            "auth_requirements",
            "support_level",
            "lifecycle_status",
            "feature_flag",
            "selected_route",
            "validation_rules",
            "enabled",
        ],
        "properties": {
            "capability_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "intent_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,127}$"},
            },
            "capability_candidate": {
                "type": ["string", "null"],
                "pattern": "^[A-Z][A-Z0-9_]{2,127}$",
            },
            "domain": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{1,63}$"},
            "description": {"type": "string", "minLength": 1, "maxLength": 1024},
            "required_entities": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "optional_entities": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "skill_or_specialist": {"type": ["string", "null"]},
            "output_contract": {"type": "string", "minLength": 1},
            "orchestrator_requirements": {"$ref": "#/$defs/OrchestratorRequirements"},
            "app_requirements": {"$ref": "#/$defs/AppRequirements"},
            "auth_requirements": {"$ref": "#/$defs/AuthenticationRequirements"},
            "support_level": {
                "enum": ["INFORMATION_ONLY", "GUIDED", "ASSISTED", "VALIDATABLE", "EXECUTABLE"]
            },
            "lifecycle_status": {"enum": ["EXPERIMENTAL", "PILOT", "PRODUCTION"]},
            "feature_flag": {"type": ["string", "null"]},
            "selected_route": {
                "enum": [
                    "BUSINESS_RAG",
                    "PORTFOLIO_QUERY",
                    "PERSONAL_READ",
                    "TRANSFER_CONTRACT_BUILDER",
                    "CLARIFICATION",
                    "UNSUPPORTED",
                ]
            },
            "validation_rules": {"$ref": "#/$defs/CapabilityValidationRules"},
            "enabled": {"type": "boolean"},
        },
        "$defs": {
            "OrchestratorRequirements": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "required_capabilities",
                    "requires_confirmation",
                    "requires_idempotency",
                    "max_execution_time_seconds",
                ],
                "properties": {
                    "required_capabilities": {"type": "array", "items": {"type": "string"}},
                    "requires_confirmation": {"type": "boolean"},
                    "requires_idempotency": {"type": "boolean"},
                    "max_execution_time_seconds": {"type": ["integer", "null"], "minimum": 1},
                },
            },
            "AppRequirements": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "allowed_channels",
                    "required_capabilities",
                    "show_confirmation_ui",
                    "show_cancellation_ui",
                    "show_timer",
                ],
                "properties": {
                    "allowed_channels": {"type": "array", "items": {"type": "string"}},
                    "required_capabilities": {"type": "array", "items": {"type": "string"}},
                    "show_confirmation_ui": {"type": "boolean"},
                    "show_cancellation_ui": {"type": "boolean"},
                    "show_timer": {"type": "boolean"},
                },
            },
            "AuthenticationRequirements": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "requires_authenticated",
                    "minimum_authentication_level",
                    "requires_elevated",
                ],
                "properties": {
                    "requires_authenticated": {"type": "boolean"},
                    "minimum_authentication_level": {"type": ["string", "null"]},
                    "requires_elevated": {"type": "boolean"},
                },
            },
            "CapabilityValidationRules": {
                "type": "object",
                "additionalProperties": False,
                "required": ["min_required_entities", "all_required_entities_present"],
                "properties": {
                    "min_required_entities": {"type": "integer", "minimum": 0},
                    "all_required_entities_present": {"type": "boolean"},
                },
            },
        },
    }


def main() -> None:
    write_schema("orchestrator_turn_request.schema.json", orchestrator_turn_request())
    write_schema("cognitive_turn_request.schema.json", cognitive_turn_request())
    write_schema("error_response.schema.json", error_response())
    write_schema("turn_interpretation.schema.json", turn_interpretation())
    write_schema("intent_resolution.schema.json", intent_resolution())
    write_schema("capability_manifest.schema.json", capability_manifest())

    # Apply post-generation refinements inline
    _apply_uniqueitems_and_patterns()

    # Verify no empty keys
    for name in SCHEMAS_DIR.glob("*.schema.json"):
        data = json.loads(name.read_text(encoding="utf-8"))
        check_empty_keys(data, name.name)
    print("All schemas verified: no empty keys.")


def _apply_uniqueitems_and_patterns() -> None:
    """Apply uniqueItems, balance patterns, and locale fixes post-generation."""
    import json as _json

    # --- turn_interpretation ---
    ti_path = SCHEMAS_DIR / "turn_interpretation.schema.json"
    ti = _json.loads(ti_path.read_text(encoding="utf-8"))
    defs = ti["$defs"]
    defs["ClarificationRequest"]["properties"]["already_known"]["uniqueItems"] = True
    defs["ClarificationRequest"]["properties"]["missing_requirements"]["uniqueItems"] = True
    defs["SemanticAction"]["properties"]["missing_requirements"]["uniqueItems"] = True
    with ti_path.open("w", encoding="utf-8", newline="\n") as f:
        _json.dump(ti, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # --- intent_resolution ---
    ir_path = SCHEMAS_DIR / "intent_resolution.schema.json"
    ir = _json.loads(ir_path.read_text(encoding="utf-8"))
    defs = ir["$defs"]
    defs["ResolvedClarification"]["properties"]["already_known"]["uniqueItems"] = True
    defs["ResolvedClarification"]["properties"]["missing_requirements"]["uniqueItems"] = True
    defs["ResolvedAction"]["properties"]["missing_requirements"]["uniqueItems"] = True
    with ir_path.open("w", encoding="utf-8", newline="\n") as f:
        _json.dump(ir, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # --- cognitive_turn_request ---
    ct_path = SCHEMAS_DIR / "cognitive_turn_request.schema.json"
    ct = _json.loads(ct_path.read_text(encoding="utf-8"))
    ct["properties"]["user_turn"]["properties"]["language"] = {
        "type": "string",
        "minLength": 2,
        "maxLength": 3,
        "pattern": "^[a-z]{2,3}$",
    }
    ct["properties"]["channel_context"]["properties"]["locale"] = {
        "type": "string",
        "minLength": 2,
        "maxLength": 32,
        "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$",
    }
    pp = ct["$defs"]["PortfolioProduct"]["properties"]
    pp["recent_balance"] = {"type": ["string", "null"], "pattern": "^-?\\d+(\\.\\d+)?$"}
    pp["known_reserved_amount"] = {"type": ["string", "null"], "pattern": "^\\d+(\\.\\d+)?$"}
    with ct_path.open("w", encoding="utf-8", newline="\n") as f:
        _json.dump(ct, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
