"""T03 — Pydantic model tests: strict, required fields, invariants, DAG."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from genesis_cognitive.assembly.types import (
    ErrorCode,
    ErrorResponse,
    IntentResolution,
    ResolvedAction,
    ResolvedDetectedEntities,
)
from genesis_cognitive.context.types import (
    OrchestratorChannelContext,
    PortfolioProduct,
    UserTurn,
)
from genesis_cognitive.decision.capability_types import (
    AppRequirements,
    AuthenticationRequirements,
    CapabilityManifest,
    CapabilityValidationRules,
    OrchestratorRequirements,
)
from genesis_cognitive.decision.types import (
    ClarificationRequest,
    DetectedEntities,
    SemanticAction,
    TurnInterpretation,
    UnsupportedSegment,
)
from genesis_cognitive.enums import (
    FreshnessState,
    InteractionFamily,
    InterpretationMode,
    LifecycleStatus,
    NextAction,
    OperationalState,
    SelectedRoute,
    SupportLevel,
    TurnRole,
)
from genesis_cognitive.errors.cognitive_errors import (
    AuthenticationError,
    ContextProviderError,
    InputValidationError,
    InvalidModelOutputError,
    ModelInvocationError,
)
from genesis_cognitive.locale_utils import language_from_locale
from genesis_cognitive.projection.types import (
    AuthorizedProductReference,
    SemanticRecentTurn,
    SemanticTurnInput,
)
from genesis_cognitive.types.monetary import DecimalString

# --- Factories ---


def _action(seq: int = 1, **kw) -> SemanticAction:
    defaults = {
        "sequence": seq,
        "intent_id": "ACCOUNT_BALANCE_READ",
        "capability_candidate": "ACCOUNT_BALANCE",
        "selected_route": SelectedRoute.PERSONAL_READ,
        "detected_entities": DetectedEntities(),
        "missing_requirements": [],
        "depends_on": [],
        "confidence": 0.95,
    }
    defaults.update(kw)
    return SemanticAction(**defaults)


def _interpretation(mode=InterpretationMode.SINGLE, **kw) -> TurnInterpretation:
    defaults = {
        "mode": mode,
        "actions": [_action()],
        "clarifications": [],
        "unsupported_segments": [],
    }
    defaults.update(kw)
    return TurnInterpretation(**defaults)


# --- Strict behavior ---


class TestStrictBehavior:
    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            UserTurn(raw_text="hi", language="es", extra="x")

    def test_coercion_rejected(self):
        with pytest.raises(ValidationError):
            SemanticAction(
                sequence="1",
                intent_id="TEST_INTENT",
                capability_candidate=None,
                selected_route=SelectedRoute.BUSINESS_RAG,
                detected_entities=DetectedEntities(),
                missing_requirements=[],
                depends_on=[],
                confidence=0.9,
            )

    def test_frozen(self):
        turn = UserTurn(raw_text="x", language="es")
        with pytest.raises(ValidationError):
            turn.raw_text = "y"


# --- DecimalString ---


class TestDecimalString:
    def test_from_decimal(self):
        d = Decimal("500.00")
        e = DetectedEntities(amount=d)
        assert e.amount == Decimal("500.00")

    def test_zero_valid(self):
        e = DetectedEntities(amount=Decimal("0"))
        assert e.amount == Decimal("0")

    def test_negative_amount_rejected(self):
        """NonNegativeDecimalString rejects negative Decimal."""
        with pytest.raises(ValidationError):
            DetectedEntities(amount=Decimal("-1"))

    def test_nan_rejected(self):
        with pytest.raises(ValidationError):
            DetectedEntities(amount=Decimal("NaN"))

    def test_infinity_rejected(self):
        with pytest.raises(ValidationError):
            DetectedEntities(amount=Decimal("Infinity"))

    def test_signed_allows_negative(self):
        """SignedDecimalString allows negative for balances."""
        p = PortfolioProduct(
            product_ref="X",
            product_type="T",
            label=None,
            alias=None,
            currency="DOP",
            operational_state=OperationalState.ACTIVE,
            recent_balance=Decimal("-500.00"),
            known_reserved_amount=None,
            balance_as_of=None,
        )
        assert p.recent_balance == Decimal("-500.00")

    def test_signed_rejects_nan(self):
        with pytest.raises(ValidationError):
            PortfolioProduct(
                product_ref="X",
                product_type="T",
                label=None,
                alias=None,
                currency="DOP",
                operational_state=OperationalState.ACTIVE,
                recent_balance=Decimal("NaN"),
                known_reserved_amount=None,
                balance_as_of=None,
            )

    def test_signed_rejects_infinity(self):
        with pytest.raises(ValidationError):
            PortfolioProduct(
                product_ref="X",
                product_type="T",
                label=None,
                alias=None,
                currency="DOP",
                operational_state=OperationalState.ACTIVE,
                recent_balance=Decimal("Infinity"),
                known_reserved_amount=None,
                balance_as_of=None,
            )

    def test_in_model_from_string(self):
        """When used in a Pydantic model, a JSON string is accepted."""
        e = DetectedEntities.model_validate({"amount": "500.00", "currency": "DOP"})
        assert e.amount is not None
        assert e.amount == Decimal("500.00")

    def test_in_model_integer_rejected(self):
        with pytest.raises(ValidationError):
            DetectedEntities.model_validate({"amount": 500})

    def test_in_model_float_rejected(self):
        with pytest.raises(ValidationError):
            DetectedEntities.model_validate({"amount": 500.0})

    def test_in_model_invalid_pattern_rejected(self):
        with pytest.raises(ValidationError):
            DetectedEntities.model_validate({"amount": "abc"})

    def test_portfolio_product_decimal(self):
        p = PortfolioProduct(
            product_ref="COR001",
            product_type="CORRIENTE",
            label=None,
            alias=None,
            currency="DOP",
            operational_state=OperationalState.ACTIVE,
            recent_balance=DecimalString(Decimal("5000.50")),
            known_reserved_amount=None,
            balance_as_of=datetime(2026, 7, 26, tzinfo=UTC),
        )
        assert p.recent_balance is not None
        assert p.recent_balance == Decimal("5000.50")


# --- Locale ---


class TestLocale:
    def test_es_do(self):
        assert language_from_locale("es-DO") == "es"

    def test_en_us(self):
        assert language_from_locale("en-US") == "en"

    def test_es(self):
        assert language_from_locale("es") == "es"

    def test_invalid(self):
        with pytest.raises(ValueError):
            language_from_locale("123")

    def test_empty(self):
        with pytest.raises(ValueError):
            language_from_locale("")

    def test_orchestrator_locale_invalid(self):
        with pytest.raises(ValidationError):
            OrchestratorChannelContext(
                channel="ws", client_slot="w1", authenticated=True, locale="INVALID"
            )


# --- UUID ---


class TestUUID:
    def test_resolved_action_valid(self):
        uid = uuid4()
        a = ResolvedAction(
            action_id=uid,
            sequence=1,
            intent_id="TEST_INTENT",
            capability_candidate=None,
            interaction_family=InteractionFamily.KNOWLEDGE,
            domain="TEST_DOMAIN",
            selected_route=SelectedRoute.BUSINESS_RAG,
            next_action=NextAction.QUERY_RAG,
            detected_entities=ResolvedDetectedEntities(),
            missing_requirements=[],
            depends_on_action_ids=[],
            confidence=0.9,
        )
        assert a.action_id == uid

    def test_invalid_uuid_rejected(self):
        with pytest.raises(ValidationError):
            ResolvedAction(
                action_id="not-uuid",
                sequence=1,
                intent_id="TEST_INTENT",
                capability_candidate=None,
                interaction_family=InteractionFamily.KNOWLEDGE,
                domain="TEST_DOMAIN",
                selected_route=SelectedRoute.BUSINESS_RAG,
                next_action=NextAction.QUERY_RAG,
                detected_entities=ResolvedDetectedEntities(),
                missing_requirements=[],
                depends_on_action_ids=[],
                confidence=0.9,
            )


# --- SemanticAction vs ResolvedAction boundary ---


class TestActionBoundary:
    def test_semantic_action_no_action_id(self):
        with pytest.raises(ValidationError):
            SemanticAction(
                sequence=1,
                intent_id="TEST_INT",
                capability_candidate=None,
                selected_route=SelectedRoute.BUSINESS_RAG,
                detected_entities=DetectedEntities(),
                missing_requirements=[],
                depends_on=[],
                confidence=0.9,
                action_id=uuid4(),
            )

    def test_resolved_requires_action_id(self):
        with pytest.raises(ValidationError):
            ResolvedAction(
                sequence=1,
                intent_id="TEST_INTENT",
                capability_candidate=None,
                interaction_family=InteractionFamily.KNOWLEDGE,
                domain="TEST_DOMAIN",
                selected_route=SelectedRoute.BUSINESS_RAG,
                next_action=NextAction.QUERY_RAG,
                detected_entities=ResolvedDetectedEntities(),
                missing_requirements=[],
                depends_on_action_ids=[],
                confidence=0.9,
            )


# --- TurnInterpretation modes ---


class TestModes:
    def test_single_valid(self):
        _interpretation(InterpretationMode.SINGLE)

    def test_single_two_actions_fails(self):
        with pytest.raises(ValidationError, match="exactly one"):
            TurnInterpretation(
                mode=InterpretationMode.SINGLE,
                actions=[_action(1), _action(2)],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_multi_independent_valid(self):
        TurnInterpretation(
            mode=InterpretationMode.MULTI_INDEPENDENT,
            actions=[_action(1), _action(2)],
            clarifications=[],
            unsupported_segments=[],
        )

    def test_multi_independent_with_deps_fails(self):
        with pytest.raises(ValidationError, match="empty depends_on"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_INDEPENDENT,
                actions=[_action(1), _action(2, depends_on=[1])],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_multi_dependent_valid(self):
        TurnInterpretation(
            mode=InterpretationMode.MULTI_DEPENDENT,
            actions=[_action(1), _action(2, depends_on=[1])],
            clarifications=[],
            unsupported_segments=[],
        )

    def test_multi_dependent_no_deps_fails(self):
        with pytest.raises(ValidationError, match="at least one dependency"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_DEPENDENT,
                actions=[_action(1), _action(2)],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_clarification_valid(self):
        TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[_action(1, missing_requirements=["source_account_ref"])],
            clarifications=[
                ClarificationRequest(
                    target_action_sequence=1,
                    missing_requirements=["source_account_ref"],
                    suggested_question="Cual cuenta?",
                    already_known=[],
                )
            ],
            unsupported_segments=[],
        )

    def test_clarification_no_clarifications_fails(self):
        with pytest.raises(ValidationError, match="non-empty clarifications"):
            TurnInterpretation(
                mode=InterpretationMode.CLARIFICATION,
                actions=[_action(1, missing_requirements=["x"])],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_unsupported_valid(self):
        TurnInterpretation(
            mode=InterpretationMode.UNSUPPORTED,
            actions=[],
            clarifications=[],
            unsupported_segments=[UnsupportedSegment(segment_description="cancel", reason="no")],
        )

    def test_unsupported_with_actions_fails(self):
        with pytest.raises(ValidationError, match="empty actions"):
            TurnInterpretation(
                mode=InterpretationMode.UNSUPPORTED,
                actions=[_action()],
                clarifications=[],
                unsupported_segments=[UnsupportedSegment(segment_description="x", reason="y")],
            )

    def test_mixed_valid(self):
        TurnInterpretation(
            mode=InterpretationMode.MIXED,
            actions=[_action()],
            clarifications=[],
            unsupported_segments=[UnsupportedSegment(segment_description="x", reason="y")],
        )

    def test_mixed_no_unsupported_fails(self):
        with pytest.raises(ValidationError, match="non-empty unsupported"):
            TurnInterpretation(
                mode=InterpretationMode.MIXED,
                actions=[_action()],
                clarifications=[],
                unsupported_segments=[],
            )


# --- DAG ---


class TestDAG:
    def test_duplicate_sequences(self):
        with pytest.raises(ValidationError, match="unique"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_INDEPENDENT,
                actions=[_action(1), _action(1)],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_nonexistent_dep(self):
        with pytest.raises(ValidationError, match="non-existent"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_DEPENDENT,
                actions=[_action(1), _action(2, depends_on=[99])],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_self_dep(self):
        with pytest.raises(ValidationError, match="itself"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_DEPENDENT,
                actions=[_action(1, depends_on=[1]), _action(2, depends_on=[1])],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_direct_cycle(self):
        with pytest.raises(ValidationError, match="[Cc]ycl"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_DEPENDENT,
                actions=[_action(1, depends_on=[2]), _action(2, depends_on=[1])],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_indirect_cycle(self):
        with pytest.raises(ValidationError, match="[Cc]ycl"):
            TurnInterpretation(
                mode=InterpretationMode.MULTI_DEPENDENT,
                actions=[
                    _action(1, depends_on=[3]),
                    _action(2, depends_on=[1]),
                    _action(3, depends_on=[2]),
                ],
                clarifications=[],
                unsupported_segments=[],
            )

    def test_clarification_to_nonexistent(self):
        with pytest.raises(ValidationError, match="non-existent"):
            TurnInterpretation(
                mode=InterpretationMode.CLARIFICATION,
                actions=[_action(1, missing_requirements=["x"])],
                clarifications=[
                    ClarificationRequest(
                        target_action_sequence=99,
                        missing_requirements=["x"],
                        suggested_question="?",
                        already_known=[],
                    )
                ],
                unsupported_segments=[],
            )

    def test_clarification_req_not_in_action_missing(self):
        with pytest.raises(ValidationError, match="not in action"):
            TurnInterpretation(
                mode=InterpretationMode.CLARIFICATION,
                actions=[_action(1, missing_requirements=["source"])],
                clarifications=[
                    ClarificationRequest(
                        target_action_sequence=1,
                        missing_requirements=["destination"],
                        suggested_question="?",
                        already_known=[],
                    )
                ],
                unsupported_segments=[],
            )

    def test_clarification_req_in_already_known(self):
        with pytest.raises(ValidationError, match="already_known"):
            TurnInterpretation(
                mode=InterpretationMode.CLARIFICATION,
                actions=[_action(1, missing_requirements=["source"])],
                clarifications=[
                    ClarificationRequest(
                        target_action_sequence=1,
                        missing_requirements=["source"],
                        suggested_question="?",
                        already_known=["source"],
                    )
                ],
                unsupported_segments=[],
            )


# --- CapabilityManifest ---


class TestCapabilityManifest:
    def test_valid(self):
        CapabilityManifest(
            capability_id="transfer",
            intent_ids=("TRANSFER_BETWEEN_OWN_ACCOUNTS",),
            capability_candidate="TRANSFER",
            domain="TRANSFERS",
            description="Transfer",
            required_entities=("source_account_ref",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="TransferContract",
            orchestrator_requirements=OrchestratorRequirements(
                required_capabilities=(),
                requires_confirmation=True,
                requires_idempotency=True,
                max_execution_time_seconds=60,
            ),
            app_requirements=AppRequirements(
                allowed_channels=("ws",),
                required_capabilities=(),
                show_confirmation_ui=True,
                show_cancellation_ui=True,
                show_timer=True,
            ),
            auth_requirements=AuthenticationRequirements(
                requires_authenticated=True,
                minimum_authentication_level=None,
                requires_elevated=False,
            ),
            support_level=SupportLevel.EXECUTABLE,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.TRANSFER_CONTRACT_BUILDER,
            validation_rules=CapabilityValidationRules(
                min_required_entities=1,
                all_required_entities_present=True,
            ),
            enabled=True,
        )

    def test_invalid_support_level(self):
        with pytest.raises(ValidationError):
            CapabilityManifest(
                capability_id="x",
                intent_ids=("XXX",),
                capability_candidate=None,
                domain="XX",
                description="x",
                required_entities=(),
                optional_entities=(),
                skill_or_specialist=None,
                output_contract="x",
                orchestrator_requirements=OrchestratorRequirements(
                    required_capabilities=(),
                    requires_confirmation=False,
                    requires_idempotency=False,
                    max_execution_time_seconds=None,
                ),
                app_requirements=AppRequirements(
                    allowed_channels=(),
                    required_capabilities=(),
                    show_confirmation_ui=False,
                    show_cancellation_ui=False,
                    show_timer=False,
                ),
                auth_requirements=AuthenticationRequirements(
                    requires_authenticated=True,
                    minimum_authentication_level=None,
                    requires_elevated=False,
                ),
                support_level="FULL",
                lifecycle_status=LifecycleStatus.PRODUCTION,
                feature_flag=None,
                selected_route=SelectedRoute.BUSINESS_RAG,
                validation_rules=CapabilityValidationRules(
                    min_required_entities=0,
                    all_required_entities_present=True,
                ),
                enabled=True,
            )

    def test_missing_enabled_fails(self):
        """enabled is required by schema — cannot be omitted."""
        with pytest.raises(ValidationError):
            CapabilityManifest(
                capability_id="x",
                intent_ids=("XXX",),
                capability_candidate=None,
                domain="XX",
                description="x",
                required_entities=(),
                optional_entities=(),
                skill_or_specialist=None,
                output_contract="x",
                orchestrator_requirements=OrchestratorRequirements(
                    required_capabilities=(),
                    requires_confirmation=False,
                    requires_idempotency=False,
                    max_execution_time_seconds=None,
                ),
                app_requirements=AppRequirements(
                    allowed_channels=(),
                    required_capabilities=(),
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
                # enabled omitted!
            )


# --- ErrorResponse ---


class TestErrorResponse:
    def test_valid(self):
        ErrorResponse(
            error=True,
            error_code=ErrorCode.INVALID_INPUT,
            message="La solicitud no es estructuralmente valida.",
            request_id="r1",
            correlation_id=None,
        )

    def test_arbitrary_message_fails(self):
        with pytest.raises(ValidationError, match="Message must be"):
            ErrorResponse(
                error=True,
                error_code=ErrorCode.INVALID_INPUT,
                message="arbitrary text",
                request_id=None,
                correlation_id=None,
            )

    def test_error_false_fails(self):
        with pytest.raises(ValidationError):
            ErrorResponse(
                error=False,
                error_code=ErrorCode.INVALID_INPUT,
                message="La solicitud no es estructuralmente valida.",
                request_id=None,
                correlation_id=None,
            )

    def test_missing_request_id_fails(self):
        """request_id is required (nullable but must be present)."""
        with pytest.raises(ValidationError):
            ErrorResponse(
                error=True,
                error_code=ErrorCode.INVALID_INPUT,
                message="La solicitud no es estructuralmente valida.",
                correlation_id=None,
            )

    def test_missing_correlation_id_fails(self):
        with pytest.raises(ValidationError):
            ErrorResponse(
                error=True,
                error_code=ErrorCode.INVALID_INPUT,
                message="La solicitud no es estructuralmente valida.",
                request_id=None,
            )


# --- IntentResolution boundary ---


class TestIntentResolutionBoundary:
    def test_no_customer_id(self):
        with pytest.raises(ValidationError):
            IntentResolution(
                contract_version="1.0",
                output_type="intent_resolution",
                request_id="r",
                correlation_id="c",
                conversation_id="cv",
                resolver_version="0.1.0",
                prompt_id="p",
                prompt_version="1.0.0",
                mode=InterpretationMode.UNSUPPORTED,
                actions=[],
                clarifications=[],
                unsupported_segments=[],
                customer_id="CUST001",
            )

    def test_no_subject_token(self):
        with pytest.raises(ValidationError):
            IntentResolution(
                contract_version="1.0",
                output_type="intent_resolution",
                request_id="r",
                correlation_id="c",
                conversation_id="cv",
                resolver_version="0.1.0",
                prompt_id="p",
                prompt_version="1.0.0",
                mode=InterpretationMode.UNSUPPORTED,
                actions=[],
                clarifications=[],
                unsupported_segments=[],
                subject_token="tok",
            )


# --- Errors with no arbitrary message ---


class TestErrors:
    def test_input_validation_error_fixed_message(self):
        err = InputValidationError()
        assert err.error_code == "INVALID_INPUT"
        assert err.message == "La solicitud no es estructuralmente valida."

    def test_authentication_error(self):
        assert AuthenticationError().error_code == "AUTHENTICATION_REQUIRED"

    def test_context_provider_error(self):
        assert ContextProviderError().error_code == "CONTEXT_PROVIDER_ERROR"

    def test_model_invocation_error(self):
        assert ModelInvocationError().error_code == "MODEL_INVOCATION_ERROR"

    def test_invalid_model_output_error(self):
        assert InvalidModelOutputError().error_code == "INVALID_MODEL_OUTPUT"

    def test_no_arbitrary_message_in_signature(self):
        """The constructor does not accept a public message parameter."""
        # Only internal_cause is accepted
        err = InputValidationError(internal_cause=RuntimeError("details"))
        assert err.internal_cause is not None
        assert err.message == "La solicitud no es estructuralmente valida."


# --- Projection ---


class TestProjection:
    def test_authorized_product_with_balance_and_freshness(self):
        p = AuthorizedProductReference(
            product_ref="COR001",
            product_type="CORRIENTE",
            label="Mi Corriente",
            alias=None,
            currency="DOP",
            operational_state=OperationalState.ACTIVE,
            recent_balance=DecimalString(Decimal("5000.50")),
            known_reserved_amount=None,
            balance_as_of=datetime(2026, 7, 26, tzinfo=UTC),
            freshness_state=FreshnessState.FRESH,
        )
        assert p.freshness_state == FreshnessState.FRESH
        assert p.recent_balance is not None
        assert p.recent_balance == Decimal("5000.50")

    def test_semantic_turn_input(self):
        SemanticTurnInput(
            raw_text="hola",
            language="es",
            recent_turns_summary=[],
            known_products=[],
            capability_catalog=[],
            allowed_entities=[],
        )

    def test_semantic_recent_turn(self):
        SemanticRecentTurn(role=TurnRole.USER, summary="hello")
