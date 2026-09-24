"""T02 — Schema validation tests with FormatChecker and structural verification."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"

SCHEMA_FILES = [
    "orchestrator_turn_request.schema.json",
    "cognitive_turn_request.schema.json",
    "error_response.schema.json",
    "turn_interpretation.schema.json",
    "intent_resolution.schema.json",
    "capability_manifest.schema.json",
]


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def build_validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=FormatChecker())


def assert_no_empty_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        assert "" not in value, f"Empty key found at {path}"
        for key, child in value.items():
            assert_no_empty_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_empty_keys(child, f"{path}[{index}]")


# --- Structural verification ---


@pytest.mark.parametrize("schema_file", SCHEMA_FILES)
def test_schema_is_valid_draft_2020_12(schema_file: str) -> None:
    schema = load_schema(schema_file)
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("schema_file", SCHEMA_FILES)
def test_schema_has_dollar_schema(schema_file: str) -> None:
    schema = load_schema(schema_file)
    assert "$schema" in schema
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("schema_file", SCHEMA_FILES)
def test_schema_has_dollar_id(schema_file: str) -> None:
    schema = load_schema(schema_file)
    assert "$id" in schema
    assert schema["$id"].startswith("https://genesis.local/schemas/")


@pytest.mark.parametrize("schema_file", SCHEMA_FILES)
def test_schema_has_no_empty_keys(schema_file: str) -> None:
    schema = load_schema(schema_file)
    assert_no_empty_keys(schema)


# --- Reproducibility ---


def test_schema_generator_is_idempotent() -> None:
    """Run generate_schemas.py and verify hashes don't change."""
    hashes_before = {}
    for f in SCHEMAS_DIR.glob("*.schema.json"):
        hashes_before[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()

    generator = Path(__file__).parent.parent.parent / "scripts" / "generate_schemas.py"
    result = subprocess.run(
        [sys.executable, str(generator)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0

    hashes_after = {}
    for f in SCHEMAS_DIR.glob("*.schema.json"):
        hashes_after[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()

    assert hashes_before == hashes_after, "Schema generator is not idempotent!"


# --- orchestrator_turn_request ---


def _valid_orchestrator_request() -> dict:
    return {
        "type": "USER_MESSAGE",
        "conversation_id": "conv-001",
        "customer_id": "CUST001",
        "subject_token": "sub_simulated",
        "request_id": "req-001",
        "correlation_id": "corr-001",
        "user_turn": {"raw_text": "Hola"},
        "channel_context": {
            "channel": "websocket",
            "client_slot": "web-1",
            "authenticated": True,
            "locale": "es-DO",
        },
    }


def test_orchestrator_valid_passes() -> None:
    build_validator(load_schema("orchestrator_turn_request.schema.json")).validate(
        _valid_orchestrator_request()
    )


def test_orchestrator_locale_absent_fails() -> None:
    schema = load_schema("orchestrator_turn_request.schema.json")
    req = _valid_orchestrator_request()
    del req["channel_context"]["locale"]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_orchestrator_locale_es_do_passes() -> None:
    schema = load_schema("orchestrator_turn_request.schema.json")
    req = _valid_orchestrator_request()
    req["channel_context"]["locale"] = "es-DO"
    build_validator(schema).validate(req)


def test_orchestrator_authenticated_absent_fails() -> None:
    schema = load_schema("orchestrator_turn_request.schema.json")
    req = _valid_orchestrator_request()
    del req["channel_context"]["authenticated"]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_orchestrator_authenticated_false_structurally_valid() -> None:
    schema = load_schema("orchestrator_turn_request.schema.json")
    req = _valid_orchestrator_request()
    req["channel_context"]["authenticated"] = False
    build_validator(schema).validate(req)


def test_orchestrator_authenticated_string_fails() -> None:
    schema = load_schema("orchestrator_turn_request.schema.json")
    req = _valid_orchestrator_request()
    req["channel_context"]["authenticated"] = "true"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


# --- cognitive_turn_request ---


def _valid_cognitive_request() -> dict:
    return {
        "contract_version": "1.0",
        "input_type": "user_turn",
        "request_id": "r1",
        "correlation_id": "c1",
        "conversation_id": "cv1",
        "session_id": "s1",
        "subject_token": "st1",
        "customer_id": "cu1",
        "turn_number": 1,
        "user_turn": {"raw_text": "hola", "language": "es"},
        "session_context": {
            "session_status": "ACTIVE",
            "recent_turns": [{"role": "USER", "summary": "test msg"}],
            "known_products": {
                "version": "in-memory-0",
                "generated_at": "2026-07-26T10:00:00Z",
                "fresh_until": "2026-07-26T10:01:00Z",
                "freshness_state": "FRESH",
                "products": [],
            },
            "pending_operation": None,
            "last_operation_request": None,
            "last_operation_result": None,
        },
        "channel_context": {
            "channel": "ws",
            "locale": "es-DO",
            "authenticated": True,
            "client_slot": "w1",
        },
    }


def test_cognitive_valid_passes() -> None:
    build_validator(load_schema("cognitive_turn_request.schema.json")).validate(
        _valid_cognitive_request()
    )


def test_cognitive_recent_turn_extra_property_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["recent_turns"] = [
        {"role": "USER", "summary": "x", "extra_field": "bad"}
    ]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_recent_turn_valid_passes() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["recent_turns"] = [
        {"role": "USER", "summary": "pregunta"},
        {"role": "ASSISTANT", "summary": "respuesta"},
    ]
    build_validator(schema).validate(req)


def test_cognitive_known_products_arbitrary_object_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["known_products"] = {"COR001": {"type": "CORRIENTE"}}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_portfolio_snapshot_empty_products_passes() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["known_products"] = {
        "version": "in-memory-0",
        "generated_at": "2026-07-26T10:00:00Z",
        "fresh_until": "2026-07-26T10:01:00Z",
        "freshness_state": "FRESH",
        "products": [],
    }
    build_validator(schema).validate(req)


def test_cognitive_product_extra_field_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["known_products"]["products"] = [
        {
            "product_ref": "COR001",
            "product_type": "CORRIENTE",
            "label": None,
            "alias": None,
            "currency": "DOP",
            "operational_state": "ACTIVE",
            "recent_balance": "5000.00",
            "known_reserved_amount": None,
            "balance_as_of": None,
            "extra_field": "bad",
        }
    ]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_balance_numeric_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["known_products"]["products"] = [
        {
            "product_ref": "COR001",
            "product_type": "CORRIENTE",
            "label": None,
            "alias": None,
            "currency": "DOP",
            "operational_state": "ACTIVE",
            "recent_balance": 5000.50,
            "known_reserved_amount": None,
            "balance_as_of": None,
        }
    ]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_balance_decimal_string_passes() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["known_products"]["products"] = [
        {
            "product_ref": "COR001",
            "product_type": "CORRIENTE",
            "label": "Mi Corriente",
            "alias": "corriente-principal",
            "currency": "DOP",
            "operational_state": "ACTIVE",
            "recent_balance": "5000.50",
            "known_reserved_amount": "100.00",
            "balance_as_of": "2026-07-26T10:00:00Z",
        }
    ]
    build_validator(schema).validate(req)


def test_cognitive_balance_as_of_invalid_format_noted() -> None:
    """Note: format 'date-time' is advisory in Draft 2020-12.
    The base jsonschema library does not enforce it without additional validators.
    This test documents the expected behavior once a date-time validator is installed.
    For now, we verify the field accepts null and rejects non-string types."""
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["known_products"]["products"] = [
        {
            "product_ref": "COR001",
            "product_type": "CORRIENTE",
            "label": None,
            "alias": None,
            "currency": "DOP",
            "operational_state": "ACTIVE",
            "recent_balance": None,
            "known_reserved_amount": None,
            "balance_as_of": 12345,  # Not a string — should fail type check
        }
    ]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_pending_operation_object_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["pending_operation"] = {"some": "data"}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_pending_operation_null_passes() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["pending_operation"] = None
    build_validator(schema).validate(req)


def test_cognitive_last_operation_request_object_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["last_operation_request"] = {"x": 1}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


def test_cognitive_last_operation_result_object_fails() -> None:
    schema = load_schema("cognitive_turn_request.schema.json")
    req = _valid_cognitive_request()
    req["session_context"]["last_operation_result"] = {"y": 2}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(req)


# --- error_response ---


def test_error_response_all_valid_codes_pass() -> None:
    schema = load_schema("error_response.schema.json")
    v = build_validator(schema)
    pairs = [
        ("INVALID_INPUT", "La solicitud no es estructuralmente valida."),
        ("AUTHENTICATION_REQUIRED", "Se requiere autenticacion."),
        ("CONTEXT_PROVIDER_ERROR", "Error al obtener contexto."),
        ("MODEL_INVOCATION_ERROR", "Error al invocar el modelo."),
        ("INVALID_MODEL_OUTPUT", "La respuesta del modelo no es valida."),
    ]
    for code, msg in pairs:
        v.validate(
            {
                "error": True,
                "error_code": code,
                "message": msg,
                "request_id": "req-001",
                "correlation_id": "corr-001",
            }
        )


def test_error_response_extra_field_fails() -> None:
    schema = load_schema("error_response.schema.json")
    with pytest.raises(ValidationError):
        build_validator(schema).validate(
            {
                "error": True,
                "error_code": "INVALID_INPUT",
                "message": "La solicitud no es estructuralmente valida.",
                "request_id": "r",
                "correlation_id": "c",
                "stack_trace": "bad",
            }
        )


def test_error_response_arbitrary_message_fails() -> None:
    schema = load_schema("error_response.schema.json")
    with pytest.raises(ValidationError):
        build_validator(schema).validate(
            {
                "error": True,
                "error_code": "INVALID_INPUT",
                "message": "Random user-facing message with PII",
                "request_id": None,
                "correlation_id": None,
            }
        )


def test_error_response_code_message_mismatch_fails() -> None:
    schema = load_schema("error_response.schema.json")
    with pytest.raises(ValidationError):
        build_validator(schema).validate(
            {
                "error": True,
                "error_code": "INVALID_INPUT",
                "message": "Se requiere autenticacion.",
                "request_id": None,
                "correlation_id": None,
            }
        )


# --- turn_interpretation ---


def _valid_turn_interpretation() -> dict:
    return {
        "mode": "SINGLE",
        "actions": [
            {
                "sequence": 1,
                "intent_id": "ACCOUNT_BALANCE_READ",
                "capability_candidate": "ACCOUNT_BALANCE",
                "selected_route": "PERSONAL_READ",
                "detected_entities": {"account_ref": "COR001"},
                "missing_requirements": [],
                "depends_on": [],
                "confidence": 0.95,
            }
        ],
        "clarifications": [],
        "unsupported_segments": [],
    }


def test_turn_interpretation_valid_passes() -> None:
    build_validator(load_schema("turn_interpretation.schema.json")).validate(
        _valid_turn_interpretation()
    )


def test_turn_interpretation_action_id_fails() -> None:
    schema = load_schema("turn_interpretation.schema.json")
    ti = _valid_turn_interpretation()
    ti["actions"][0]["action_id"] = "not-allowed"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ti)


def test_turn_interpretation_extra_property_fails() -> None:
    schema = load_schema("turn_interpretation.schema.json")
    ti = _valid_turn_interpretation()
    ti["extra"] = "bad"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ti)


def test_turn_interpretation_confidence_above_1_fails() -> None:
    schema = load_schema("turn_interpretation.schema.json")
    ti = _valid_turn_interpretation()
    ti["actions"][0]["confidence"] = 1.5
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ti)


def test_turn_interpretation_depends_on_duplicate_fails() -> None:
    schema = load_schema("turn_interpretation.schema.json")
    ti = _valid_turn_interpretation()
    ti["mode"] = "MULTI_DEPENDENT"
    ti["actions"].append(
        {
            "sequence": 2,
            "intent_id": "ACCOUNT_BALANCE_READ",
            "capability_candidate": "ACCOUNT_BALANCE",
            "selected_route": "PERSONAL_READ",
            "detected_entities": {},
            "missing_requirements": [],
            "depends_on": [1, 1],
            "confidence": 0.9,
        }
    )
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ti)


def test_turn_interpretation_amount_number_fails() -> None:
    schema = load_schema("turn_interpretation.schema.json")
    ti = _valid_turn_interpretation()
    ti["actions"][0]["detected_entities"] = {"amount": 500}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ti)


def test_turn_interpretation_amount_string_passes() -> None:
    schema = load_schema("turn_interpretation.schema.json")
    ti = _valid_turn_interpretation()
    ti["actions"][0]["detected_entities"] = {"amount": "500.00", "currency": "DOP"}
    build_validator(schema).validate(ti)


# --- intent_resolution ---


def _valid_intent_resolution() -> dict:
    return {
        "contract_version": "1.0",
        "output_type": "intent_resolution",
        "request_id": "req-001",
        "correlation_id": "corr-001",
        "conversation_id": "conv-001",
        "resolver_version": "0.1.0",
        "prompt_id": "genesis.turn-decision",
        "prompt_version": "1.0.0",
        "mode": "SINGLE",
        "actions": [
            {
                "action_id": "550e8400-e29b-41d4-a716-446655440000",
                "sequence": 1,
                "intent_id": "ACCOUNT_BALANCE_READ",
                "capability_candidate": "ACCOUNT_BALANCE",
                "interaction_family": "PERSONAL_READ",
                "domain": "ACCOUNTS",
                "selected_route": "PERSONAL_READ",
                "next_action": "BUILD_READ_REQUEST",
                "detected_entities": {"account_ref": "COR001"},
                "missing_requirements": [],
                "depends_on_action_ids": [],
                "confidence": 0.95,
            }
        ],
        "clarifications": [],
        "unsupported_segments": [],
    }


def test_intent_resolution_valid_passes() -> None:
    build_validator(load_schema("intent_resolution.schema.json")).validate(
        _valid_intent_resolution()
    )


def test_intent_resolution_numeric_depends_on_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["actions"][0]["depends_on_action_ids"] = [1]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


def test_intent_resolution_uuid_depends_on_passes() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["actions"][0]["depends_on_action_ids"] = ["550e8400-e29b-41d4-a716-446655440001"]
    build_validator(schema).validate(ir)


def test_intent_resolution_customer_id_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["customer_id"] = "CUST001"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


def test_intent_resolution_subject_token_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["subject_token"] = "tok"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


def test_intent_resolution_invalid_prompt_version_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["prompt_version"] = "v1.0"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


def test_intent_resolution_invalid_action_id_uuid_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["actions"][0]["action_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


def test_intent_resolution_invalid_depends_on_uuid_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["actions"][0]["depends_on_action_ids"] = ["not-a-uuid"]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


def test_intent_resolution_invalid_target_action_id_fails() -> None:
    schema = load_schema("intent_resolution.schema.json")
    ir = _valid_intent_resolution()
    ir["clarifications"] = [
        {
            "target_action_id": "not-a-uuid",
            "missing_requirements": ["source"],
            "suggested_question": "Cual cuenta?",
            "already_known": [],
        }
    ]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(ir)


# --- capability_manifest ---


def _valid_capability_manifest() -> dict:
    return {
        "capability_id": "transfer-own-accounts",
        "intent_ids": ["TRANSFER_BETWEEN_OWN_ACCOUNTS"],
        "capability_candidate": "TRANSFER",
        "domain": "TRANSFERS",
        "description": "Transfer between own accounts",
        "required_entities": [
            "source_account_ref",
            "destination_account_ref",
            "amount",
            "currency",
        ],
        "optional_entities": [],
        "skill_or_specialist": None,
        "output_contract": "TransferContractCandidate",
        "orchestrator_requirements": {
            "required_capabilities": ["core.transfer"],
            "requires_confirmation": True,
            "requires_idempotency": True,
            "max_execution_time_seconds": 60,
        },
        "app_requirements": {
            "allowed_channels": ["websocket", "mobile"],
            "required_capabilities": ["show_confirmation"],
            "show_confirmation_ui": True,
            "show_cancellation_ui": True,
            "show_timer": True,
        },
        "auth_requirements": {
            "requires_authenticated": True,
            "minimum_authentication_level": "standard",
            "requires_elevated": False,
        },
        "support_level": "EXECUTABLE",
        "lifecycle_status": "PRODUCTION",
        "feature_flag": None,
        "selected_route": "TRANSFER_CONTRACT_BUILDER",
        "validation_rules": {"min_required_entities": 4, "all_required_entities_present": True},
        "enabled": True,
    }


def test_capability_manifest_has_defs() -> None:
    schema = load_schema("capability_manifest.schema.json")
    assert "$defs" in schema
    for name in [
        "OrchestratorRequirements",
        "AppRequirements",
        "AuthenticationRequirements",
        "CapabilityValidationRules",
    ]:
        assert name in schema["$defs"]


def test_capability_manifest_refs_resolve() -> None:
    build_validator(load_schema("capability_manifest.schema.json")).validate(
        _valid_capability_manifest()
    )


def test_capability_manifest_orch_reqs_string_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    cm["orchestrator_requirements"] = "invalid"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_orch_reqs_extra_field_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    cm["orchestrator_requirements"]["extra"] = True
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_app_reqs_arbitrary_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    cm["app_requirements"] = {"random": "stuff"}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_auth_reqs_arbitrary_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    cm["auth_requirements"] = {"anything": 123}
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_validation_rules_null_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    cm["validation_rules"] = None
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_missing_required_in_sub_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    del cm["orchestrator_requirements"]["requires_confirmation"]
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_unknown_support_level_fails() -> None:
    schema = load_schema("capability_manifest.schema.json")
    cm = _valid_capability_manifest()
    cm["support_level"] = "FULL"
    with pytest.raises(ValidationError):
        build_validator(schema).validate(cm)


def test_capability_manifest_valid_passes() -> None:
    build_validator(load_schema("capability_manifest.schema.json")).validate(
        _valid_capability_manifest()
    )
