"""T13-A2B — ContractInspector unit tests.

Uses a FakeResolver (no network) to validate the ContractInspector
orchestration of resolver + gate without real model inference.

Validates:
- inspect calls resolver once
- COR001 valid
- alias invalid and not transformed
- extra entity invalidates catalog
- triple not found invalid
- missing_requirement coherent
- missing_requirement incoherent
- duplicate sequence invalid
- nonexistent depends_on invalid
- cycle invalid
- output_contract from capability
- interpretation not modified
- BUSINESS_KNOWLEDGE returns RAG_PENDING
- no keyword routing
- no financial execution
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
from genesis_cognitive.decision.types import (
    ClarificationRequest,
    DetectedEntities,
    SemanticAction,
    TurnInterpretation,
)
from genesis_cognitive.enums import InterpretationMode, SelectedRoute
from genesis_cognitive.inspection.contract_inspector import (
    ContractInspector,
)
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputEnvelope,
    ProjectedCapability,
    ProjectedPendingOperation,
    ProjectedProduct,
)

# ---------------------------------------------------------------------------
# FakeResolver — no network, returns a pre-configured interpretation
# ---------------------------------------------------------------------------


class FakeResolver:
    """Fake AgentFrameworkTurnResolver that returns pre-set interpretations."""

    def __init__(self, interpretation: TurnInterpretation) -> None:
        self._interpretation = interpretation
        self.call_count = 0
        self.last_input: ModelInputEnvelope | None = None

    async def resolve(self, model_input: ModelInputEnvelope) -> TurnInterpretation:
        self.call_count += 1
        self.last_input = model_input
        return self._interpretation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_portfolio() -> tuple[ProjectedProduct, ...]:
    return (
        ProjectedProduct(
            product_ref="COR001",
            product_type="CHECKING",
            label="Cuenta corriente",
            alias="cuenta principal",
            currency="DOP",
            operational_state="ACTIVE",
        ),
        ProjectedProduct(
            product_ref="AHO001",
            product_type="SAVINGS",
            label="Cuenta de ahorros",
            alias="mis ahorros",
            currency="DOP",
            operational_state="ACTIVE",
        ),
    )


def _make_capabilities() -> tuple[ProjectedCapability, ...]:
    return (
        ProjectedCapability(
            capability_id="account-balance",
            intent_ids=("ACCOUNT_BALANCE_READ",),
            capability_candidate="ACCOUNT_BALANCE",
            domain="ACCOUNTS",
            description="Consulta de saldo disponible",
            selected_route=SelectedRoute.PERSONAL_READ,
            required_entities=("account_ref",),
            optional_entities=(),
            min_required_entities=1,
            output_contract="BalanceResponse",
            support_level="INFORMATION_ONLY",
            requires_confirmation=False,
            requires_idempotency=False,
        ),
        ProjectedCapability(
            capability_id="account-movements",
            intent_ids=("ACCOUNT_MOVEMENTS_READ",),
            capability_candidate="ACCOUNT_MOVEMENTS",
            domain="ACCOUNTS",
            description="Consulta de movimientos",
            selected_route=SelectedRoute.PERSONAL_READ,
            required_entities=("account_ref",),
            optional_entities=(),
            min_required_entities=1,
            output_contract="MovementsResponse",
            support_level="INFORMATION_ONLY",
            requires_confirmation=False,
            requires_idempotency=False,
        ),
        ProjectedCapability(
            capability_id="transfer-own-accounts",
            intent_ids=("TRANSFER_BETWEEN_OWN_ACCOUNTS",),
            capability_candidate="TRANSFER",
            domain="TRANSFERS",
            description="Transferencia entre cuentas propias",
            selected_route=SelectedRoute.TRANSFER_CONTRACT_BUILDER,
            required_entities=(
                "source_account_ref",
                "destination_account_ref",
                "amount",
                "currency",
            ),
            optional_entities=(),
            min_required_entities=4,
            output_contract="TransferContractCandidate",
            support_level="EXECUTABLE",
            requires_confirmation=True,
            requires_idempotency=True,
        ),
        ProjectedCapability(
            capability_id="business-knowledge",
            intent_ids=("BUSINESS_KNOWLEDGE_QUERY",),
            capability_candidate="BUSINESS_KNOWLEDGE",
            domain="BUSINESS_KNOWLEDGE",
            description="Consultas de conocimiento de negocio",
            selected_route=SelectedRoute.BUSINESS_RAG,
            required_entities=(),
            optional_entities=("knowledge_topic",),
            min_required_entities=0,
            output_contract="KnowledgeResponse",
            support_level="INFORMATION_ONLY",
            requires_confirmation=False,
            requires_idempotency=False,
        ),
        ProjectedCapability(
            capability_id="clarification",
            intent_ids=("CLARIFICATION_REQUIRED",),
            capability_candidate=None,
            domain="GENERAL",
            description="Aclaracion de datos faltantes",
            selected_route=SelectedRoute.CLARIFICATION,
            required_entities=(),
            optional_entities=(
                "account_ref",
                "source_account_ref",
                "destination_account_ref",
                "amount",
                "currency",
                "knowledge_topic",
            ),
            min_required_entities=0,
            output_contract="ClarificationResponse",
            support_level="GUIDED",
            requires_confirmation=False,
            requires_idempotency=False,
        ),
    )


def _make_base_input() -> ModelInputEnvelope:
    return ModelInputEnvelope(
        raw_text="base",
        language="es",
        locale="es-DO",
        conversation=(),
        portfolio=_make_portfolio(),
        pending_operation=ProjectedPendingOperation(),
        effective_capabilities=_make_capabilities(),
    )


def _make_valid_single(
    account_ref: str = "COR001",
) -> TurnInterpretation:
    """A valid SINGLE interpretation for ACCOUNT_BALANCE_READ."""
    return TurnInterpretation(
        mode=InterpretationMode.SINGLE,
        actions=[
            SemanticAction(
                sequence=1,
                intent_id="ACCOUNT_BALANCE_READ",
                capability_candidate="ACCOUNT_BALANCE",
                selected_route=SelectedRoute.PERSONAL_READ,
                detected_entities=DetectedEntities(account_ref=account_ref),
                missing_requirements=[],
                depends_on=[],
                confidence=0.95,
            )
        ],
        clarifications=[],
        unsupported_segments=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContractInspector:
    """ContractInspector unit tests with FakeResolver."""

    @pytest.fixture()
    def base_input(self) -> ModelInputEnvelope:
        return _make_base_input()

    async def test_inspect_calls_resolver_once(self, base_input: ModelInputEnvelope) -> None:
        """Inspector calls resolver exactly once per inspect."""
        interp = _make_valid_single()
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        await inspector.inspect("consulta de saldo", base_input)
        assert resolver.call_count == 1

    async def test_cor001_valid(self, base_input: ModelInputEnvelope) -> None:
        """COR001 as account_ref produces VALID result."""
        interp = _make_valid_single("COR001")
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("dame mi saldo", base_input)
        assert result.catalog_valid is True
        assert result.entity_refs_valid is True
        assert result.overall_status == "VALID"
        assert result.violations == ()

    async def test_alias_invalid_not_transformed(self, base_input: ModelInputEnvelope) -> None:
        """Alias 'cuenta principal' is INVALID; not transformed to COR001."""
        interp = _make_valid_single("cuenta principal")
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("saldo de cuenta principal", base_input)
        assert result.entity_refs_valid is False
        assert result.overall_status == "INVALID"
        # Interpretation is not modified
        assert (
            result.raw_interpretation.actions[0].detected_entities.account_ref == "cuenta principal"
        )

    async def test_extra_entity_invalidates_catalog(self, base_input: ModelInputEnvelope) -> None:
        """An entity not in the capability's allowed fields → catalog_valid=False."""
        # currency is NOT in ACCOUNT_BALANCE_READ's required_entities + optional_entities
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(account_ref="COR001", currency="DOP"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("saldo en DOP", base_input)
        assert result.catalog_valid is False
        assert any("currency" in v for v in result.violations)

    async def test_triple_not_found_invalid(self, base_input: ModelInputEnvelope) -> None:
        """A (intent_id, capability_candidate, selected_route) not found → invalid."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="NONEXISTENT_CAP",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(account_ref="COR001"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("saldo", base_input)
        assert result.catalog_valid is False
        assert result.overall_status == "INVALID"

    async def test_missing_requirement_coherent(self, base_input: ModelInputEnvelope) -> None:
        """In CLARIFICATION mode, absent required entity in missing_requirements is coherent."""
        interp = TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(),
                    missing_requirements=["account_ref"],
                    depends_on=[],
                    confidence=0.7,
                )
            ],
            clarifications=[
                ClarificationRequest(
                    target_action_sequence=1,
                    missing_requirements=["account_ref"],
                    suggested_question="¿De cuál cuenta?",
                    already_known=[],
                )
            ],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("dame mi saldo", base_input)
        assert result.catalog_valid is True
        assert result.overall_status == "VALID"

    async def test_missing_requirement_incoherent(self, base_input: ModelInputEnvelope) -> None:
        """Present entity listed in missing_requirements is incoherent."""
        # Use model_construct to bypass TurnInterpretation's own validators,
        # since we want to test the gate's detection of this incoherence.
        action = SemanticAction.model_construct(
            sequence=1,
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="COR001"),
            missing_requirements=["account_ref"],
            depends_on=[],
            confidence=0.7,
        )
        interp = TurnInterpretation.model_construct(
            mode=InterpretationMode.CLARIFICATION,
            actions=[action],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("saldo de COR001", base_input)
        assert result.catalog_valid is False
        assert any("present but listed in missing_requirements" in v for v in result.violations)

    async def test_duplicate_sequence_invalid(self, base_input: ModelInputEnvelope) -> None:
        """Duplicate sequences in actions produce catalog_valid=False."""
        # Use model_construct to bypass TurnInterpretation's uniqueness check
        action1 = SemanticAction.model_construct(
            sequence=1,
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="COR001"),
            missing_requirements=[],
            depends_on=[],
            confidence=0.9,
        )
        action2 = SemanticAction.model_construct(
            sequence=1,  # duplicate!
            intent_id="ACCOUNT_MOVEMENTS_READ",
            capability_candidate="ACCOUNT_MOVEMENTS",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="AHO001"),
            missing_requirements=[],
            depends_on=[],
            confidence=0.9,
        )
        interp = TurnInterpretation.model_construct(
            mode=InterpretationMode.MULTI_INDEPENDENT,
            actions=[action1, action2],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("test", base_input)
        assert result.catalog_valid is False
        assert any("unique" in v for v in result.violations)

    async def test_nonexistent_depends_on_invalid(self, base_input: ModelInputEnvelope) -> None:
        """depends_on referencing a non-existent sequence is invalid."""
        # Use model_construct to bypass TurnInterpretation's own DAG validation
        action1 = SemanticAction.model_construct(
            sequence=1,
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="COR001"),
            missing_requirements=[],
            depends_on=[],
            confidence=0.9,
        )
        action2 = SemanticAction.model_construct(
            sequence=2,
            intent_id="ACCOUNT_MOVEMENTS_READ",
            capability_candidate="ACCOUNT_MOVEMENTS",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="AHO001"),
            missing_requirements=[],
            depends_on=[99],  # non-existent
            confidence=0.9,
        )
        interp = TurnInterpretation.model_construct(
            mode=InterpretationMode.MULTI_DEPENDENT,
            actions=[action1, action2],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("test", base_input)
        assert result.catalog_valid is False
        assert any("non-existent" in v for v in result.violations)

    async def test_cycle_invalid(self, base_input: ModelInputEnvelope) -> None:
        """Cyclic depends_on is invalid."""
        # Build two actions that depend on each other
        # TurnInterpretation.validate_invariants will catch this, so we use model_construct
        action1 = SemanticAction.model_construct(
            sequence=1,
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="COR001"),
            missing_requirements=[],
            depends_on=[2],
            confidence=0.9,
        )
        action2 = SemanticAction.model_construct(
            sequence=2,
            intent_id="ACCOUNT_MOVEMENTS_READ",
            capability_candidate="ACCOUNT_MOVEMENTS",
            selected_route=SelectedRoute.PERSONAL_READ,
            detected_entities=DetectedEntities(account_ref="AHO001"),
            missing_requirements=[],
            depends_on=[1],
            confidence=0.9,
        )
        interp = TurnInterpretation.model_construct(
            mode=InterpretationMode.MULTI_DEPENDENT,
            actions=[action1, action2],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("test", base_input)
        assert result.catalog_valid is False
        assert any("cycle" in v.lower() for v in result.violations)

    async def test_output_contract_from_capability(self, base_input: ModelInputEnvelope) -> None:
        """output_contracts are resolved from matching capability."""
        interp = _make_valid_single()
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("saldo", base_input)
        assert result.output_contracts == ("BalanceResponse",)

    async def test_interpretation_not_modified(self, base_input: ModelInputEnvelope) -> None:
        """raw_interpretation is returned unchanged."""
        interp = _make_valid_single()
        original_dump = interp.model_dump()
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("test", base_input)
        assert result.raw_interpretation.model_dump() == original_dump

    async def test_business_knowledge_returns_rag_pending(
        self, base_input: ModelInputEnvelope
    ) -> None:
        """An action with BUSINESS_KNOWLEDGE in intent_id returns RAG_PENDING."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="BUSINESS_KNOWLEDGE_QUERY",
                    capability_candidate="BUSINESS_KNOWLEDGE",
                    selected_route=SelectedRoute.BUSINESS_RAG,
                    detected_entities=DetectedEntities(knowledge_topic="tasas"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("cuáles son las tasas?", base_input)
        assert result.rag_status == "RAG_PENDING"

    async def test_no_keyword_routing(self) -> None:
        """ContractInspector source does not contain keyword routing patterns."""
        source_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "genesis_cognitive"
            / "inspection"
            / "contract_inspector.py"
        )
        source = source_path.read_text(encoding="utf-8")

        assert "re.compile" not in source
        assert "re.match" not in source
        assert "re.search" not in source
        assert "import re" not in source

        # No keyword-based routing logic in the inspector
        # The only raw_text reference is passing the question to model_copy
        inspect_source = inspect.getsource(ContractInspector.inspect)
        # Should not contain keyword lists or synonym dictionaries
        assert "keywords" not in inspect_source
        assert "synonyms" not in inspect_source

    async def test_no_financial_execution(self) -> None:
        """ContractInspector source does not contain financial execution code."""
        source_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "genesis_cognitive"
            / "inspection"
            / "contract_inspector.py"
        )
        source = source_path.read_text(encoding="utf-8")

        forbidden_patterns = [
            "execute_transfer",
            "execute_operation",
            "execute_transaction",
            "core.transfer",
            "httpx.post",
            "requests.post",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, f"Forbidden pattern '{pattern}' found in source"

    async def test_inference_count_always_one(self, base_input: ModelInputEnvelope) -> None:
        """inference_count is always 1."""
        interp = _make_valid_single()
        resolver = FakeResolver(interp)
        gate = SemanticContractGate()
        inspector = ContractInspector(resolver, gate)  # type: ignore[arg-type]

        result = await inspector.inspect("test", base_input)
        assert result.inference_count == 1
