"""T12-A — ModelInputBuilder unit tests."""

from __future__ import annotations

import ast
import copy
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from genesis_cognitive.context.context_assembler import AssembledContext
from genesis_cognitive.context.context_types import (
    ConversationContext,
    PendingOperationContext,
    PortfolioContext,
)
from genesis_cognitive.context.types import (
    PortfolioProduct,
    PortfolioSnapshot,
    RecentTurn,
)
from genesis_cognitive.decision.capability_types import (
    AppRequirements,
    AuthenticationRequirements,
    CapabilityManifest,
    CapabilityValidationRules,
    OrchestratorRequirements,
)
from genesis_cognitive.enums import (
    FreshnessState,
    LifecycleStatus,
    OperationalState,
    SelectedRoute,
    SessionStatus,
    SupportLevel,
    TurnRole,
)
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputBuilder,
    ModelInputEnvelope,
)

# --- Fixtures ---

_PROHIBITED_FIELDS = {
    "subject_token",
    "customer_id",
    "conversation_id",
    "request_id",
    "correlation_id",
    "client_slot",
}


def _make_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_id="account-balance",
        intent_ids=("ACCOUNT_BALANCE_READ",),
        capability_candidate="ACCOUNT_BALANCE",
        domain="ACCOUNTS",
        description="Consulta de saldo",
        required_entities=("account_ref",),
        optional_entities=("currency",),
        skill_or_specialist=None,
        output_contract="BalanceReadContract",
        orchestrator_requirements=OrchestratorRequirements(
            required_capabilities=(),
            requires_confirmation=False,
            requires_idempotency=False,
            max_execution_time_seconds=30,
        ),
        app_requirements=AppRequirements(
            allowed_channels=("mobile", "web"),
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
        selected_route=SelectedRoute.PERSONAL_READ,
        validation_rules=CapabilityValidationRules(
            min_required_entities=1,
            all_required_entities_present=True,
        ),
        enabled=True,
    )


def _make_assembled() -> AssembledContext:
    return AssembledContext(
        request_id="req-001",
        correlation_id="cor-001",
        conversation_id="conv-001",
        customer_id="cust-001",
        subject_token="tok-secret-xyz",
        raw_text="  Quiero consultar MI saldo.  ",
        locale="es-DO",
        language="es",
        channel="mobile",
        client_slot="slot-001",
        authenticated=True,
        conversation=ConversationContext(
            session_id="sess-001",
            turn_number=2,
            session_status=SessionStatus.ACTIVE,
            recent_turns=(
                RecentTurn(role=TurnRole.USER, summary="Hola"),
                RecentTurn(role=TurnRole.ASSISTANT, summary="Buenos dias"),
            ),
        ),
        portfolio=PortfolioContext(
            snapshot=PortfolioSnapshot(
                version="v1",
                generated_at=datetime(2026, 7, 27, tzinfo=UTC),
                fresh_until=datetime(2026, 7, 27, 0, 1, tzinfo=UTC),
                freshness_state=FreshnessState.FRESH,
                products=(
                    PortfolioProduct(
                        product_ref="COR001",
                        product_type="CHECKING",
                        label="Cuenta corriente",
                        alias="principal",
                        currency="DOP",
                        operational_state=OperationalState.ACTIVE,
                        recent_balance=Decimal("12500.75"),
                        known_reserved_amount=Decimal("500.00"),
                        balance_as_of=datetime(2026, 7, 27, tzinfo=UTC),
                    ),
                ),
            )
        ),
        pending_operations=PendingOperationContext(),
        effective_capabilities=(_make_manifest(),),
    )


class TestBasicProjection:
    def test_receives_assembled_context(self) -> None:
        builder = ModelInputBuilder()
        result = builder.build(_make_assembled())
        assert isinstance(result, ModelInputEnvelope)

    def test_conserves_raw_text_exactly(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert result.raw_text == "  Quiero consultar MI saldo.  "

    def test_conserves_language_and_locale(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert result.language == "es"
        assert result.locale == "es-DO"


class TestConversationProjection:
    def test_projects_turns_in_order(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert len(result.conversation) == 2
        assert result.conversation[0].role == "USER"
        assert result.conversation[0].summary == "Hola"
        assert result.conversation[1].role == "ASSISTANT"
        assert result.conversation[1].summary == "Buenos dias"


class TestPortfolioProjection:
    def test_projects_product_whitelist_fields(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert len(result.portfolio) == 1
        p = result.portfolio[0]
        assert p.product_ref == "COR001"
        assert p.product_type == "CHECKING"
        assert p.label == "Cuenta corriente"
        assert p.alias == "principal"
        assert p.currency == "DOP"
        assert p.operational_state == "ACTIVE"

    def test_excludes_balances_and_reserved(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        json_str = result.model_dump_json()
        assert "12500.75" not in json_str
        assert "500.00" not in json_str
        assert "recent_balance" not in json_str
        assert "known_reserved_amount" not in json_str
        assert "balance_as_of" not in json_str


class TestPendingOperationProjection:
    def test_projects_pending_via_whitelist(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert result.pending_operation.pending_operation is None
        assert result.pending_operation.last_operation_request is None
        assert result.pending_operation.last_operation_result is None


class TestCapabilityProjection:
    def test_projects_all_effective_manifests(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert len(result.effective_capabilities) == 1
        cap = result.effective_capabilities[0]
        assert cap.capability_id == "account-balance"
        assert cap.domain == "ACCOUNTS"
        assert cap.selected_route == SelectedRoute.PERSONAL_READ
        assert cap.required_entities == ("account_ref",)
        assert cap.optional_entities == ("currency",)
        assert cap.min_required_entities == 1

    def test_intent_ids_projected_exactly(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        cap = result.effective_capabilities[0]
        assert cap.intent_ids == ("ACCOUNT_BALANCE_READ",)

    def test_capability_candidate_projected(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        cap = result.effective_capabilities[0]
        assert cap.capability_candidate == "ACCOUNT_BALANCE"

    def test_capability_candidate_none_is_valid(self) -> None:
        """clarification and unsupported have candidate=None."""
        assembled = _make_assembled()
        # Replace with a manifest that has candidate=None
        from genesis_cognitive.decision.capability_types import (
            AppRequirements,
            AuthenticationRequirements,
            CapabilityManifest,
            CapabilityValidationRules,
            OrchestratorRequirements,
        )

        null_cap = CapabilityManifest(
            capability_id="clarification",
            intent_ids=("CLARIFICATION_REQUIRED",),
            capability_candidate=None,
            domain="GENERAL",
            description="Aclaracion",
            required_entities=(),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="ClarificationContract",
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
                requires_authenticated=False,
                minimum_authentication_level=None,
                requires_elevated=False,
            ),
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.CLARIFICATION,
            validation_rules=CapabilityValidationRules(
                min_required_entities=0,
                all_required_entities_present=False,
            ),
            enabled=True,
        )
        # Use model_construct to swap capabilities without validation
        patched = assembled.model_copy(update={"effective_capabilities": (null_cap,)})
        result = ModelInputBuilder().build(patched)
        assert result.effective_capabilities[0].capability_candidate is None

    def test_description_conserved(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert result.effective_capabilities[0].description == "Consulta de saldo"

    def test_output_contract_conserved(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert result.effective_capabilities[0].output_contract == "BalanceReadContract"

    def test_support_level_conserved(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        assert result.effective_capabilities[0].support_level == "EXECUTABLE"

    def test_confirmation_and_idempotency_conserved(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        cap = result.effective_capabilities[0]
        assert cap.requires_confirmation is False
        assert cap.requires_idempotency is False

    def test_multiple_capabilities_preserve_order(self) -> None:
        assembled = _make_assembled()
        m1 = assembled.effective_capabilities[0]

        m2 = m1.model_copy(
            update={
                "capability_id": "transfer",
                "intent_ids": ("TRANSFER_BETWEEN_OWN_ACCOUNTS",),
                "capability_candidate": "TRANSFER",
                "domain": "TRANSFERS",
                "selected_route": SelectedRoute.TRANSFER_CONTRACT_BUILDER,
            }
        )
        patched = assembled.model_copy(update={"effective_capabilities": (m1, m2)})
        result = ModelInputBuilder().build(patched)
        assert result.effective_capabilities[0].capability_id == "account-balance"
        assert result.effective_capabilities[1].capability_id == "transfer"

    def test_json_contains_contractual_identifiers(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        json_str = result.model_dump_json()
        assert "ACCOUNT_BALANCE_READ" in json_str
        assert "ACCOUNT_BALANCE" in json_str
        assert "BalanceReadContract" in json_str
        assert "EXECUTABLE" in json_str


class TestProhibitedData:
    def test_no_subject_token_in_output(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        json_str = result.model_dump_json()
        assert "tok-secret-xyz" not in json_str
        assert "subject_token" not in json_str

    def test_no_identity_ids_in_output(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        json_str = result.model_dump_json()
        for field in _PROHIBITED_FIELDS:
            assert field not in json_str

    def test_no_customer_id_value_in_output(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        json_str = result.model_dump_json()
        assert "cust-001" not in json_str

    def test_no_request_correlation_values(self) -> None:
        result = ModelInputBuilder().build(_make_assembled())
        json_str = result.model_dump_json()
        assert "req-001" not in json_str
        assert "cor-001" not in json_str
        assert "conv-001" not in json_str


class TestDeterminism:
    def test_serialization_is_deterministic(self) -> None:
        assembled = _make_assembled()
        builder = ModelInputBuilder()
        j1 = builder.build(assembled).model_dump_json()
        j2 = builder.build(assembled).model_dump_json()
        assert j1 == j2


class TestImmutability:
    def test_input_not_modified(self) -> None:
        assembled = _make_assembled()
        before = copy.deepcopy(assembled.model_dump())
        ModelInputBuilder().build(assembled)
        after = assembled.model_dump()
        assert before == after


class TestNoExternalDependencies:
    def test_no_openai_or_keyword_routing(self) -> None:
        source = Path(inspect.getfile(ModelInputBuilder))
        text = source.read_text(encoding="utf-8").lower()
        assert "openai" not in text
        assert "re.match" not in text
        assert "re.search" not in text
        # Check no keyword-based routing logic (import of re, lists of phrases)
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "re"

    def test_no_provider_calls(self) -> None:
        source = Path(inspect.getfile(ModelInputBuilder))
        text = source.read_text(encoding="utf-8")
        assert "ContextProvider" not in text
        assert "async def" not in text

    def test_no_financial_execution(self) -> None:
        """AST inspection: no imports of httpx, requests, execution ports."""
        source = Path(inspect.getfile(ModelInputBuilder))
        tree = ast.parse(source.read_text(encoding="utf-8"))
        prohibited_modules = {"httpx", "requests", "aiohttp"}
        prohibited_calls = {"execute", "transfer", "send", "post", "invoke_core"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in prohibited_modules, f"Prohibited import: {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in prohibited_modules
            # Check function/method calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in prohibited_calls, (
                        f"Prohibited call: {node.func.attr}"
                    )
                elif isinstance(node.func, ast.Name):
                    assert node.func.id not in prohibited_calls, f"Prohibited call: {node.func.id}"
