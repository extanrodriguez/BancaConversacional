"""T13-A2A — SemanticContractGate unit tests.

Validates:
- Prompt 1.2.0 is current.
- Prompt does not contain test product refs.
- Gate validates product_ref correctly.
- Gate rejects aliases, nonexistent refs.
- Gate does not transform, normalize, or read raw_text.
- Gate does not use keywords/regex/synonyms.
- TurnInterpretation is not modified by the gate.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from genesis_cognitive.decision.semantic_contract_gate import (
    SemanticContractGate,
)
from genesis_cognitive.decision.types import (
    DetectedEntities,
    SemanticAction,
    TurnInterpretation,
)
from genesis_cognitive.enums import InterpretationMode, SelectedRoute
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputEnvelope,
    ProjectedCapability,
    ProjectedPendingOperation,
    ProjectedProduct,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROMPTS_ROOT = PROJECT_ROOT / "prompts"


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
    )


def _make_envelope(raw_text: str = "test") -> ModelInputEnvelope:
    return ModelInputEnvelope(
        raw_text=raw_text,
        language="es",
        locale="es-DO",
        conversation=(),
        portfolio=_make_portfolio(),
        pending_operation=ProjectedPendingOperation(),
        effective_capabilities=_make_capabilities(),
    )


def _make_valid_interpretation() -> TurnInterpretation:
    """A valid SINGLE interpretation with COR001 as account_ref."""
    return TurnInterpretation(
        mode=InterpretationMode.SINGLE,
        actions=[
            SemanticAction(
                sequence=1,
                intent_id="ACCOUNT_BALANCE_READ",
                capability_candidate="ACCOUNT_BALANCE",
                selected_route=SelectedRoute.PERSONAL_READ,
                detected_entities=DetectedEntities(account_ref="COR001"),
                missing_requirements=[],
                depends_on=[],
                confidence=0.95,
            )
        ],
        clarifications=[],
        unsupported_segments=[],
    )


@pytest.fixture()
def gate() -> SemanticContractGate:
    return SemanticContractGate()


@pytest.fixture()
def envelope() -> ModelInputEnvelope:
    return _make_envelope()


# ---------------------------------------------------------------------------
# Prompt version tests
# ---------------------------------------------------------------------------


class TestPromptVersion:
    def test_current_is_1_2_0(self) -> None:
        """Prompt current.json points to 1.2.0."""
        current_path = PROMPTS_ROOT / "turn-decision-agent" / "current.json"
        data = json.loads(current_path.read_text(encoding="utf-8"))
        assert data["active_version"] == "1.2.0"

    def test_prompt_does_not_contain_test_refs(self) -> None:
        """Prompt 1.2.0 does not contain COR001, AHO001 or test phrases."""
        prompt_path = PROMPTS_ROOT / "turn-decision-agent" / "1.2.0" / "prompt.json"
        content = prompt_path.read_text(encoding="utf-8")
        assert "COR001" not in content
        assert "AHO001" not in content
        assert "cuenta principal" not in content
        assert "mis ahorros" not in content


# ---------------------------------------------------------------------------
# Entity reference validation tests
# ---------------------------------------------------------------------------


class TestEntityRefs:
    def test_valid_product_ref_cor001(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """account_ref=COR001 is valid when COR001 is in portfolio."""
        interp = _make_valid_interpretation()
        result = gate.validate(interp, envelope)
        assert result.entity_refs_valid is True
        assert result.catalog_valid is True
        assert result.violations == ()

    def test_alias_cuenta_principal_is_invalid(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """account_ref='cuenta principal' is INVALID (not a product_ref)."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(account_ref="cuenta principal"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        result = gate.validate(interp, envelope)
        assert result.entity_refs_valid is False
        assert any("cuenta principal" in v for v in result.violations)

    def test_nonexistent_ref_is_invalid(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """A product_ref that does not exist in portfolio is invalid."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(account_ref="NOEXISTE999"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        result = gate.validate(interp, envelope)
        assert result.entity_refs_valid is False
        assert any("NOEXISTE999" in v for v in result.violations)

    def test_no_alias_to_product_ref_transformation(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """Gate does NOT transform 'cuenta principal' → 'COR001'."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(account_ref="cuenta principal"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        result = gate.validate(interp, envelope)
        # Gate MUST reject, not silently fix
        assert result.entity_refs_valid is False
        # The interpretation is returned unchanged
        assert result.interpretation.actions[0].detected_entities.account_ref == "cuenta principal"


# ---------------------------------------------------------------------------
# Catalog validation tests
# ---------------------------------------------------------------------------


class TestCatalogValidation:
    def test_invalid_capability_rejected(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """A capability_candidate not in effective_capabilities is rejected."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="NONEXISTENT_CAPABILITY",
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
        result = gate.validate(interp, envelope)
        assert result.catalog_valid is False

    def test_incoherent_intent_candidate_route(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """Mismatched intent/candidate/route triple is rejected."""
        interp = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.TRANSFER_CONTRACT_BUILDER,  # wrong route
                    detected_entities=DetectedEntities(account_ref="COR001"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        result = gate.validate(interp, envelope)
        assert result.catalog_valid is False


# ---------------------------------------------------------------------------
# Gate behavior tests
# ---------------------------------------------------------------------------


class TestGateBehavior:
    def test_gate_does_not_read_raw_text(
        self,
        gate: SemanticContractGate,
    ) -> None:
        """Gate produces same result regardless of raw_text content."""
        interp = _make_valid_interpretation()
        envelope_a = _make_envelope(raw_text="dame mi saldo")
        envelope_b = _make_envelope(raw_text="transferir a la de ahorros")

        result_a = gate.validate(interp, envelope_a)
        result_b = gate.validate(interp, envelope_b)

        assert result_a.entity_refs_valid == result_b.entity_refs_valid
        assert result_a.catalog_valid == result_b.catalog_valid

    def test_no_keywords_regex_synonyms_in_gate_source(self) -> None:
        """Gate source code does not contain keyword routing patterns."""
        source_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "genesis_cognitive"
            / "decision"
            / "semantic_contract_gate.py"
        )
        source = source_path.read_text(encoding="utf-8")

        # No regex patterns for intent detection
        assert "re.compile" not in source
        assert "re.match" not in source
        assert "re.search" not in source
        assert "import re" not in source

        # No keyword/synonym routing data structures in code (exclude comments/docstrings)
        # Extract only non-comment, non-docstring lines
        code_lines = []
        in_docstring = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(stripped.lower())
        code_only = "\n".join(code_lines)

        assert "keywords" not in code_only
        assert "synonyms" not in code_only

        # Validate via inspection that validate method does not access raw_text
        gate_source = inspect.getsource(SemanticContractGate.validate)
        assert "raw_text" not in gate_source

    def test_turn_interpretation_not_modified(
        self, gate: SemanticContractGate, envelope: ModelInputEnvelope
    ) -> None:
        """TurnInterpretation is returned unchanged — immutable."""
        interp = _make_valid_interpretation()
        original_dump = interp.model_dump()

        result = gate.validate(interp, envelope)

        # The returned interpretation is the same object (frozen model)
        assert result.interpretation is interp
        # Content is identical
        assert result.interpretation.model_dump() == original_dump
