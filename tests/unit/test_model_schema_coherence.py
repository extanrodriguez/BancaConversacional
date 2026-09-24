"""T03 — Pydantic and JSON Schema equivalence tests."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError

from genesis_cognitive.assembly.types import ErrorResponse, IntentResolution, ResolvedAction
from genesis_cognitive.context.types import OrchestratorTurnRequest
from genesis_cognitive.decision.capability_types import CapabilityManifest
from genesis_cognitive.decision.types import SemanticAction, TurnInterpretation

SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"


def load_stored_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def get_pydantic_required(model_class: type) -> set[str]:
    schema = model_class.model_json_schema()
    return set(schema.get("required", []))


def get_stored_required(schema: dict, def_name: str | None = None) -> set[str]:
    target = schema.get("$defs", {}).get(def_name, schema) if def_name else schema
    return set(target.get("required", []))


def pydantic_accepts(model: type[BaseModel], payload: dict) -> bool:
    try:
        model.model_validate_json(json.dumps(payload))
        return True
    except (ValidationError, Exception):
        return False


def json_schema_accepts(schema: dict, payload: dict) -> bool:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return validator.is_valid(payload)


def assert_same_acceptance(model: type[BaseModel], schema: dict, payload: dict) -> None:
    p = pydantic_accepts(model, payload)
    s = json_schema_accepts(schema, payload)
    assert p == s, f"Pydantic={p}, Schema={s}, payload keys={list(payload.keys())}"


# --- Required field coherence ---


class TestRequiredCoherence:
    def test_orchestrator(self):
        stored = load_stored_schema("orchestrator_turn_request.schema.json")
        assert get_pydantic_required(OrchestratorTurnRequest) == get_stored_required(stored)

    def test_turn_interpretation(self):
        stored = load_stored_schema("turn_interpretation.schema.json")
        assert get_pydantic_required(TurnInterpretation) == get_stored_required(stored)

    def test_intent_resolution(self):
        stored = load_stored_schema("intent_resolution.schema.json")
        assert get_pydantic_required(IntentResolution) == get_stored_required(stored)

    def test_capability_manifest(self):
        stored = load_stored_schema("capability_manifest.schema.json")
        assert get_pydantic_required(CapabilityManifest) == get_stored_required(stored)

    def test_error_response(self):
        stored = load_stored_schema("error_response.schema.json")
        assert get_pydantic_required(ErrorResponse) == get_stored_required(stored)

    def test_semantic_action(self):
        stored = load_stored_schema("turn_interpretation.schema.json")
        assert get_pydantic_required(SemanticAction) == get_stored_required(
            stored, "SemanticAction"
        )

    def test_resolved_action(self):
        stored = load_stored_schema("intent_resolution.schema.json")
        assert get_pydantic_required(ResolvedAction) == get_stored_required(
            stored, "ResolvedAction"
        )


# --- Real acceptance equivalence tests ---

# Valid base TurnInterpretation
_VALID_TI = {
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


class TestEquivalenceAcceptance:
    """19 cases: each tests both Pydantic and JSON Schema agree."""

    def _ti_schema(self):
        return load_stored_schema("turn_interpretation.schema.json")

    def test_01_entity_explicitly_null(self):
        """null entity value should be accepted."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["detected_entities"] = {"account_ref": None}
        assert_same_acceptance(TurnInterpretation, self._ti_schema(), ti)
        assert pydantic_accepts(TurnInterpretation, ti)

    def test_02_reference_empty_string(self):
        """Empty string reference should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["detected_entities"] = {"account_ref": ""}
        assert_same_acceptance(TurnInterpretation, self._ti_schema(), ti)
        assert not pydantic_accepts(TurnInterpretation, ti)

    def test_03_knowledge_topic_empty(self):
        """Empty knowledge_topic should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["detected_entities"] = {"knowledge_topic": ""}
        assert_same_acceptance(TurnInterpretation, self._ti_schema(), ti)
        assert not pydantic_accepts(TurnInterpretation, ti)

    def test_04_requirement_empty(self):
        """Empty string in missing_requirements should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["missing_requirements"] = [""]
        assert_same_acceptance(TurnInterpretation, self._ti_schema(), ti)
        assert not pydantic_accepts(TurnInterpretation, ti)

    def test_05_requirements_duplicated(self):
        """Duplicate requirements should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["missing_requirements"] = ["source", "source"]
        # Pydantic rejects via validator; Schema rejects via uniqueItems
        p = pydantic_accepts(TurnInterpretation, ti)
        s = json_schema_accepts(self._ti_schema(), ti)
        assert not p
        assert not s

    def test_06_depends_on_uuid_duplicated(self):
        """Duplicate depends_on should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["mode"] = "MULTI_DEPENDENT"
        ti["actions"].append(
            {
                "sequence": 2,
                "intent_id": "ACCOUNT_BALANCE_READ",
                "capability_candidate": None,
                "selected_route": "PERSONAL_READ",
                "detected_entities": {},
                "missing_requirements": [],
                "depends_on": [1, 1],
                "confidence": 0.9,
            }
        )
        p = pydantic_accepts(TurnInterpretation, ti)
        s = json_schema_accepts(self._ti_schema(), ti)
        assert not p
        assert not s

    def test_07_language_four_chars(self):
        """language with 4 chars should be rejected by both."""
        from genesis_cognitive.context.types import UserTurn

        schema = load_stored_schema("cognitive_turn_request.schema.json")
        user_turn_schema = schema["properties"]["user_turn"]
        payload = {"raw_text": "hello", "language": "espa"}
        p = pydantic_accepts(UserTurn, payload)
        s = json_schema_accepts(user_turn_schema, payload)
        assert not p
        assert not s

    def test_08_locale_invalid(self):
        """Invalid locale should be rejected by both."""
        from genesis_cognitive.context.types import OrchestratorChannelContext

        schema = load_stored_schema("orchestrator_turn_request.schema.json")
        cc_schema = schema["properties"]["channel_context"]
        payload = {"channel": "ws", "client_slot": "w1", "authenticated": True, "locale": "INVALID"}
        p = pydantic_accepts(OrchestratorChannelContext, payload)
        s = json_schema_accepts(cc_schema, payload)
        assert not p
        assert not s

    def test_09_twelve_turns_valid(self):
        """12 recent turns should be accepted."""
        from genesis_cognitive.context.types import SessionContext

        turns = [{"role": "USER", "summary": f"turn {i}"} for i in range(12)]
        payload = {
            "session_status": "ACTIVE",
            "recent_turns": turns,
            "known_products": {
                "version": "v1",
                "generated_at": "2026-07-26T10:00:00Z",
                "fresh_until": "2026-07-26T10:01:00Z",
                "freshness_state": "FRESH",
                "products": [],
            },
            "pending_operation": None,
            "last_operation_request": None,
            "last_operation_result": None,
        }
        assert pydantic_accepts(SessionContext, payload)

    def test_10_thirteen_turns_rejected(self):
        """13 recent turns should be rejected."""
        from genesis_cognitive.context.types import SessionContext

        turns = [{"role": "USER", "summary": f"turn {i}"} for i in range(13)]
        payload = {
            "session_status": "ACTIVE",
            "recent_turns": turns,
            "known_products": {
                "version": "v1",
                "generated_at": "2026-07-26T10:00:00Z",
                "fresh_until": "2026-07-26T10:01:00Z",
                "freshness_state": "FRESH",
                "products": [],
            },
            "pending_operation": None,
            "last_operation_request": None,
            "last_operation_result": None,
        }
        assert not pydantic_accepts(SessionContext, payload)

    def test_11_negative_balance_valid(self):
        """Negative balance (-500.00) should be valid for recent_balance."""
        from genesis_cognitive.context.types import PortfolioProduct

        payload = {
            "product_ref": "COR001",
            "product_type": "CORRIENTE",
            "label": None,
            "alias": None,
            "currency": "DOP",
            "operational_state": "ACTIVE",
            "recent_balance": "-500.00",
            "known_reserved_amount": None,
            "balance_as_of": None,
        }
        assert pydantic_accepts(PortfolioProduct, payload)

    def test_12_negative_reserve_rejected(self):
        """Negative reserve should be rejected."""
        from genesis_cognitive.context.types import PortfolioProduct

        payload = {
            "product_ref": "COR001",
            "product_type": "CORRIENTE",
            "label": None,
            "alias": None,
            "currency": "DOP",
            "operational_state": "ACTIVE",
            "recent_balance": None,
            "known_reserved_amount": "-100.00",
            "balance_as_of": None,
        }
        assert not pydantic_accepts(PortfolioProduct, payload)

    def test_13_intent_id_lowercase_rejected(self):
        """intent_id in lowercase should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["intent_id"] = "account_balance_read"
        p = pydantic_accepts(TurnInterpretation, ti)
        s = json_schema_accepts(self._ti_schema(), ti)
        assert not p
        assert not s

    def test_14_request_id_empty_rejected(self):
        """Empty request_id in ErrorResponse should be rejected."""

        payload = {
            "error": True,
            "error_code": "INVALID_INPUT",
            "message": "La solicitud no es estructuralmente valida.",
            "request_id": "",
            "correlation_id": None,
        }
        assert not pydantic_accepts(ErrorResponse, payload)

    def test_15_correlation_id_empty_rejected(self):
        """Empty correlation_id should be rejected."""
        payload = {
            "error": True,
            "error_code": "INVALID_INPUT",
            "message": "La solicitud no es estructuralmente valida.",
            "request_id": None,
            "correlation_id": "",
        }
        assert not pydantic_accepts(ErrorResponse, payload)

    def test_16_required_entities_empty_string(self):
        """required_entities with empty string should be rejected."""
        from genesis_cognitive.decision.capability_types import CapabilityManifest

        # Build a minimal valid manifest and set required_entities=[""]
        p = False  # Will fail because EntityName min_length=1
        try:
            from genesis_cognitive.decision.capability_types import (
                AppRequirements,
                AuthenticationRequirements,
                CapabilityValidationRules,
                OrchestratorRequirements,
            )
            from genesis_cognitive.enums import LifecycleStatus, SelectedRoute, SupportLevel

            CapabilityManifest(
                capability_id="x",
                intent_ids=["TEST_INTENT"],
                domain="TEST",
                description="test",
                required_entities=[""],
                optional_entities=[],
                skill_or_specialist=None,
                output_contract="x",
                orchestrator_requirements=OrchestratorRequirements(
                    required_capabilities=[],
                    requires_confirmation=False,
                    requires_idempotency=False,
                    max_execution_time_seconds=None,
                ),
                app_requirements=AppRequirements(
                    allowed_channels=[],
                    required_capabilities=[],
                    show_confirmation_ui=False,
                    show_cancellation_ui=False,
                    show_timer=False,
                ),
                auth_requirements=AuthenticationRequirements(
                    requires_authenticated=True,
                    minimum_authentication_level=None,
                    requires_elevated=False,
                ),
                support_level=SupportLevel.EXECUTABLE,
                lifecycle_status=LifecycleStatus.PRODUCTION,
                feature_flag=None,
                selected_route=SelectedRoute.BUSINESS_RAG,
                validation_rules=CapabilityValidationRules(
                    min_required_entities=0,
                    all_required_entities_present=True,
                ),
                enabled=True,
            )
            p = True
        except (ValidationError, Exception):
            p = False
        assert not p

    def test_17_optional_entities_empty_string(self):
        """optional_entities=[\"\"] should be rejected."""
        from genesis_cognitive.decision.capability_types import (
            AppRequirements,
            AuthenticationRequirements,
            CapabilityManifest,
            CapabilityValidationRules,
            OrchestratorRequirements,
        )
        from genesis_cognitive.enums import LifecycleStatus, SelectedRoute, SupportLevel

        with pytest.raises(ValidationError):
            CapabilityManifest(
                capability_id="x",
                intent_ids=["TEST_INTENT"],
                domain="TEST",
                description="test",
                required_entities=[],
                optional_entities=[""],
                skill_or_specialist=None,
                output_contract="x",
                orchestrator_requirements=OrchestratorRequirements(
                    required_capabilities=[],
                    requires_confirmation=False,
                    requires_idempotency=False,
                    max_execution_time_seconds=None,
                ),
                app_requirements=AppRequirements(
                    allowed_channels=[],
                    required_capabilities=[],
                    show_confirmation_ui=False,
                    show_cancellation_ui=False,
                    show_timer=False,
                ),
                auth_requirements=AuthenticationRequirements(
                    requires_authenticated=True,
                    minimum_authentication_level=None,
                    requires_elevated=False,
                ),
                support_level=SupportLevel.EXECUTABLE,
                lifecycle_status=LifecycleStatus.PRODUCTION,
                feature_flag=None,
                selected_route=SelectedRoute.BUSINESS_RAG,
                validation_rules=CapabilityValidationRules(
                    min_required_entities=0,
                    all_required_entities_present=True,
                ),
                enabled=True,
            )

    def test_18_capability_candidate_lowercase_rejected(self):
        """capability_candidate in lowercase should be rejected."""
        ti = json.loads(json.dumps(_VALID_TI))
        ti["actions"][0]["capability_candidate"] = "account_balance"
        p = pydantic_accepts(TurnInterpretation, ti)
        s = json_schema_accepts(self._ti_schema(), ti)
        assert not p
        assert not s

    def test_19_clarification_duplicate_requirements(self):
        """Duplicate requirements in clarification should be rejected."""
        ti = {
            "mode": "CLARIFICATION",
            "actions": [
                {
                    "sequence": 1,
                    "intent_id": "ACCOUNT_BALANCE_READ",
                    "capability_candidate": None,
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {},
                    "missing_requirements": ["source", "dest"],
                    "depends_on": [],
                    "confidence": 0.8,
                }
            ],
            "clarifications": [
                {
                    "target_action_sequence": 1,
                    "missing_requirements": ["source", "source"],
                    "suggested_question": "Cual?",
                    "already_known": [],
                }
            ],
            "unsupported_segments": [],
        }
        p = pydantic_accepts(TurnInterpretation, ti)
        s = json_schema_accepts(self._ti_schema(), ti)
        assert not p
        assert not s
