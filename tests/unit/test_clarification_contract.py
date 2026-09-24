"""T08-C7E-D1 - Clarification contract: canonical already_known semantics.

Tests directives 242-248: business intent preservation, ENTITY_FIELD_NAMES
enforcement, already_known/detected_entities alignment, disjointness.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import ValidationError

from genesis_cognitive.assembly.types import (
    IntentResolution,
    ResolvedAction,
    ResolvedClarification,
    ResolvedDetectedEntities,
)
from genesis_cognitive.decision.types import (
    ClarificationRequest,
    DetectedEntities,
    SemanticAction,
    TurnInterpretation,
)
from genesis_cognitive.enums import (
    InteractionFamily,
    InterpretationMode,
    NextAction,
    SelectedRoute,
)
from genesis_cognitive.prompts.prompt_registry import PromptRegistry
from genesis_cognitive.types.constraints import ENTITY_FIELD_NAMES

PROJECT_ROOT = Path(__file__).parent.parent.parent

# --- Helpers ---


def _transfer_action(seq: int = 1, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "sequence": seq,
        "intent_id": "TRANSFER_BETWEEN_OWN_ACCOUNTS",
        "capability_candidate": "TRANSFER",
        "selected_route": SelectedRoute.TRANSFER_CONTRACT_BUILDER,
        "detected_entities": DetectedEntities(
            destination_account_ref="AHO001",
            amount=Decimal("500"),
            currency="DOP",
        ),
        "missing_requirements": ["source_account_ref"],
        "depends_on": [],
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return defaults


def _clarification(target: int = 1, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "target_action_sequence": target,
        "missing_requirements": ["source_account_ref"],
        "suggested_question": "Desde cual cuenta deseas transferir?",
        "already_known": ["destination_account_ref", "amount", "currency"],
    }
    defaults.update(overrides)
    return defaults


def _resolved_action(**overrides: Any) -> ResolvedAction:
    action_id = overrides.pop("action_id", uuid4())
    defaults: dict[str, Any] = {
        "action_id": action_id,
        "sequence": 1,
        "intent_id": "TRANSFER_BETWEEN_OWN_ACCOUNTS",
        "capability_candidate": "TRANSFER",
        "interaction_family": InteractionFamily.TRANSACTION,
        "domain": "TRANSFERS",
        "selected_route": SelectedRoute.TRANSFER_CONTRACT_BUILDER,
        "next_action": NextAction.BUILD_TYPED_CONTRACT,
        "detected_entities": ResolvedDetectedEntities(
            destination_account_ref="AHO001",
            amount=Decimal("500"),
            currency="DOP",
        ),
        "missing_requirements": ["source_account_ref"],
        "depends_on_action_ids": [],
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return ResolvedAction(**defaults)


def _intent_resolution(
    actions: list[ResolvedAction],
    clarifications: list[ResolvedClarification],
) -> IntentResolution:
    return IntentResolution(
        contract_version="1.0",
        output_type="intent_resolution",
        request_id="req-001",
        correlation_id="cor-001",
        conversation_id="conv-001",
        resolver_version="0.1.0",
        prompt_id="genesis.turn-decision",
        prompt_version="1.1.0",
        mode=InterpretationMode.CLARIFICATION,
        actions=actions,
        clarifications=clarifications,
        unsupported_segments=[],
    )


# ===========================================================================
# EXISTING TESTS (1-10): TurnInterpretation contract
# ===========================================================================


class TestCaseAIdentifiedIntentPreservation:
    def test_valid_clarification_preserves_business_intent(self) -> None:
        """Directive 242-243: known intent keeps its intent_id and route."""
        action = SemanticAction(**_transfer_action())
        clar = ClarificationRequest(**_clarification())
        ti = TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[action],
            clarifications=[clar],
            unsupported_segments=[],
        )
        assert ti.actions[0].intent_id == "TRANSFER_BETWEEN_OWN_ACCOUNTS"
        assert ti.actions[0].selected_route == SelectedRoute.TRANSFER_CONTRACT_BUILDER
        assert ti.mode == InterpretationMode.CLARIFICATION


class TestCaseBUnidentifiedIntent:
    def test_clarification_required_with_clarification_route(self) -> None:
        """Directive 244: CLARIFICATION_REQUIRED for unidentifiable intent."""
        action = SemanticAction(
            sequence=1,
            intent_id="CLARIFICATION_REQUIRED",
            capability_candidate=None,
            selected_route=SelectedRoute.CLARIFICATION,
            detected_entities=DetectedEntities(),
            missing_requirements=["source_account_ref"],
            depends_on=[],
            confidence=0.4,
        )
        clar = ClarificationRequest(
            target_action_sequence=1,
            missing_requirements=["source_account_ref"],
            suggested_question="Que deseas hacer?",
            already_known=[],
        )
        ti = TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[action],
            clarifications=[clar],
            unsupported_segments=[],
        )
        assert ti.actions[0].intent_id == "CLARIFICATION_REQUIRED"
        assert ti.actions[0].selected_route == SelectedRoute.CLARIFICATION


class TestAlreadyKnownEntityFieldNames:
    def test_valid_entity_field_names_accepted(self) -> None:
        """Directive 245: only canonical entity names in already_known."""
        clar = ClarificationRequest(**_clarification())
        for item in clar.already_known:
            assert item in ENTITY_FIELD_NAMES

    def test_invalid_entity_field_name_rejected(self) -> None:
        """Directive 245: non-entity-field strings are rejected."""
        with pytest.raises(ValidationError, match="string_pattern_mismatch"):
            ClarificationRequest(
                target_action_sequence=1,
                missing_requirements=["source_account_ref"],
                suggested_question="Desde cual cuenta?",
                already_known=["INVALID_FIELD_NAME"],
            )

    def test_value_string_in_already_known_rejected(self) -> None:
        """Directive 245: 'campo: valor' format is rejected."""
        with pytest.raises(ValidationError):
            ClarificationRequest(
                target_action_sequence=1,
                missing_requirements=["source_account_ref"],
                suggested_question="Desde cual cuenta?",
                already_known=["amount: 500"],
            )


class TestValuesNotDuplicated:
    def test_already_known_contains_names_not_values(self) -> None:
        """Directive 246: values stay in detected_entities only."""
        action = SemanticAction(**_transfer_action())
        clar = ClarificationRequest(**_clarification())
        assert "500" not in clar.already_known
        assert "DOP" not in clar.already_known
        assert "AHO001" not in clar.already_known
        assert action.detected_entities.amount == Decimal("500")
        assert action.detected_entities.currency == "DOP"
        assert action.detected_entities.destination_account_ref == "AHO001"


class TestAlreadyKnownMatchesDetectedEntities:
    def test_valid_alignment(self) -> None:
        """Directive 247: already_known == non-null fields of detected_entities."""
        ti = TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[SemanticAction(**_transfer_action())],
            clarifications=[ClarificationRequest(**_clarification())],
            unsupported_segments=[],
        )
        assert ti is not None

    def test_mismatch_raises_error(self) -> None:
        """Directive 247: mismatch between already_known and detected_entities."""
        with pytest.raises(ValidationError, match="must match non-null detected_entities"):
            TurnInterpretation(
                mode=InterpretationMode.CLARIFICATION,
                actions=[SemanticAction(**_transfer_action())],
                clarifications=[
                    ClarificationRequest(
                        target_action_sequence=1,
                        missing_requirements=["source_account_ref"],
                        suggested_question="Desde cual cuenta?",
                        already_known=["destination_account_ref", "amount"],
                    )
                ],
                unsupported_segments=[],
            )


class TestDisjointness:
    def test_overlap_raises_error(self) -> None:
        """Directive 247: already_known and missing_requirements disjoint."""
        with pytest.raises(ValidationError):
            TurnInterpretation(
                mode=InterpretationMode.CLARIFICATION,
                actions=[
                    SemanticAction(
                        **_transfer_action(
                            detected_entities=DetectedEntities(
                                source_account_ref="COR001",
                                destination_account_ref="AHO001",
                                amount=Decimal("500"),
                                currency="DOP",
                            ),
                            missing_requirements=["source_account_ref"],
                        )
                    )
                ],
                clarifications=[
                    ClarificationRequest(
                        target_action_sequence=1,
                        missing_requirements=["source_account_ref"],
                        suggested_question="Desde cual cuenta?",
                        already_known=[
                            "source_account_ref",
                            "destination_account_ref",
                            "amount",
                            "currency",
                        ],
                    )
                ],
                unsupported_segments=[],
            )


class TestEntityFieldNamesConstant:
    def test_frozenset_contains_all_expected(self) -> None:
        expected = {
            "account_ref",
            "source_account_ref",
            "destination_account_ref",
            "amount",
            "currency",
            "knowledge_topic",
        }
        assert expected == ENTITY_FIELD_NAMES

    def test_frozenset_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            ENTITY_FIELD_NAMES.add("hacked")  # type: ignore[attr-defined]


class TestEntityFieldNameType:
    def test_valid_pattern(self) -> None:
        clar = ClarificationRequest(
            target_action_sequence=1,
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta?",
            already_known=["amount"],
        )
        assert clar.already_known == ["amount"]

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClarificationRequest(
                target_action_sequence=1,
                missing_requirements=["source_account_ref"],
                suggested_question="Desde cual cuenta?",
                already_known=["AMOUNT"],
            )


class TestResolvedClarificationEntityValidation:
    def test_valid_entity_names_pass(self) -> None:
        rc = ResolvedClarification(
            target_action_id=uuid4(),
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta deseas transferir?",
            already_known=["destination_account_ref", "amount", "currency"],
        )
        assert len(rc.already_known) == 3

    def test_invalid_entity_names_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not a valid entity field name"):
            ResolvedClarification(
                target_action_id=uuid4(),
                missing_requirements=["source_account_ref"],
                suggested_question="Desde cual cuenta?",
                already_known=["invalid_field_xyz"],
            )


class TestFullClarificationRoundtrip:
    def test_case_a_transfer_missing_source(self) -> None:
        ti = TurnInterpretation(
            mode=InterpretationMode.CLARIFICATION,
            actions=[SemanticAction(**_transfer_action())],
            clarifications=[ClarificationRequest(**_clarification())],
            unsupported_segments=[],
        )
        assert ti.mode == InterpretationMode.CLARIFICATION
        assert len(ti.actions) == 1
        assert len(ti.clarifications) == 1
        action = ti.actions[0]
        assert action.intent_id == "TRANSFER_BETWEEN_OWN_ACCOUNTS"
        assert action.capability_candidate == "TRANSFER"
        assert action.detected_entities.source_account_ref is None
        assert action.missing_requirements == ["source_account_ref"]
        clar = ti.clarifications[0]
        assert set(clar.already_known) == {"destination_account_ref", "amount", "currency"}


# ===========================================================================
# NEW TESTS (11-17): IntentResolution, Schema, PromptRegistry
# ===========================================================================


class TestIntentResolutionClarificationAlignment:
    """Tests for IntentResolution.validate_clarification_alignment."""

    def test_intent_resolution_accepts_exact_resolved_alignment(self) -> None:
        """Valid alignment passes."""
        action = _resolved_action()
        clar = ResolvedClarification(
            target_action_id=action.action_id,
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta?",
            already_known=["destination_account_ref", "amount", "currency"],
        )
        ir = _intent_resolution([action], [clar])
        assert ir.mode == InterpretationMode.CLARIFICATION

    def test_intent_resolution_rejects_unknown_target_action_id(self) -> None:
        """Unknown target_action_id is rejected."""
        action = _resolved_action()
        clar = ResolvedClarification(
            target_action_id=uuid4(),  # does not match
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta?",
            already_known=["destination_account_ref", "amount", "currency"],
        )
        with pytest.raises(ValidationError, match="non-existent action_id"):
            _intent_resolution([action], [clar])

    def test_intent_resolution_rejects_missing_known_entity(self) -> None:
        """already_known missing a non-null entity is rejected."""
        action = _resolved_action()
        clar = ResolvedClarification(
            target_action_id=action.action_id,
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta?",
            # Missing "currency"
            already_known=["destination_account_ref", "amount"],
        )
        with pytest.raises(ValidationError, match="must match non-null"):
            _intent_resolution([action], [clar])

    def test_intent_resolution_rejects_extra_known_entity(self) -> None:
        """already_known with extra entity not in detected is rejected."""
        action = _resolved_action()
        clar = ResolvedClarification(
            target_action_id=action.action_id,
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta?",
            already_known=[
                "destination_account_ref",
                "amount",
                "currency",
                "knowledge_topic",
            ],
        )
        with pytest.raises(ValidationError, match="must match non-null"):
            _intent_resolution([action], [clar])

    def test_intent_resolution_rejects_known_missing_overlap(self) -> None:
        """Overlap between already_known and missing_requirements rejected."""
        action = _resolved_action(
            detected_entities=ResolvedDetectedEntities(
                source_account_ref="COR001",
                destination_account_ref="AHO001",
                amount=Decimal("500"),
                currency="DOP",
            ),
            missing_requirements=["source_account_ref"],
        )
        clar = ResolvedClarification(
            target_action_id=action.action_id,
            missing_requirements=["source_account_ref"],
            suggested_question="Desde cual cuenta?",
            already_known=[
                "source_account_ref",
                "destination_account_ref",
                "amount",
                "currency",
            ],
        )
        with pytest.raises(ValidationError, match="disjoint"):
            _intent_resolution([action], [clar])


class TestBothSchemasRejectKeyValueStrings:
    """Both JSON schemas reject 'campo: valor' in already_known."""

    def test_both_clarification_schemas_reject_key_value_strings(self) -> None:
        schemas_dir = PROJECT_ROOT / "schemas"

        for schema_file in (
            "turn_interpretation.schema.json",
            "intent_resolution.schema.json",
        ):
            schema = json.loads((schemas_dir / schema_file).read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)

            # Build a minimal valid-ish doc but with bad already_known
            if "turn_interpretation" in schema_file:
                doc = {
                    "mode": "CLARIFICATION",
                    "actions": [
                        {
                            "sequence": 1,
                            "intent_id": "TRANSFER_BETWEEN_OWN_ACCOUNTS",
                            "capability_candidate": "TRANSFER",
                            "selected_route": "TRANSFER_CONTRACT_BUILDER",
                            "detected_entities": {
                                "account_ref": None,
                                "source_account_ref": None,
                                "destination_account_ref": "AHO001",
                                "amount": "500",
                                "currency": "DOP",
                                "knowledge_topic": None,
                            },
                            "missing_requirements": ["source_account_ref"],
                            "depends_on": [],
                            "confidence": 0.9,
                        }
                    ],
                    "clarifications": [
                        {
                            "target_action_sequence": 1,
                            "missing_requirements": ["source_account_ref"],
                            "suggested_question": "Desde cual cuenta?",
                            "already_known": ["amount: 500"],
                        }
                    ],
                    "unsupported_segments": [],
                }
            else:
                doc = {
                    "contract_version": "1.0",
                    "output_type": "intent_resolution",
                    "request_id": "r1",
                    "correlation_id": "c1",
                    "conversation_id": "cv1",
                    "resolver_version": "0.1.0",
                    "prompt_id": "p1",
                    "prompt_version": "1.0.0",
                    "mode": "CLARIFICATION",
                    "actions": [],
                    "clarifications": [
                        {
                            "target_action_id": str(uuid4()),
                            "missing_requirements": ["source_account_ref"],
                            "suggested_question": "Desde cual?",
                            "already_known": ["amount: 500"],
                        }
                    ],
                    "unsupported_segments": [],
                }

            errors = list(validator.iter_errors(doc))
            # Must have at least one error about already_known
            already_known_errors = [e for e in errors if "already_known" in str(e.absolute_path)]
            assert len(already_known_errors) > 0, (
                f"{schema_file} did not reject 'amount: 500' in already_known"
            )


class TestPromptRegistryVersions:
    """PromptRegistry activates 1.2.0 and preserves 1.0.0."""

    def test_prompt_registry_activates_1_2_0_and_preserves_1_0_0(self) -> None:
        registry = PromptRegistry(PROJECT_ROOT / "prompts", PROJECT_ROOT / "schemas")
        current = registry.get_current("turn-decision-agent")
        assert current.prompt_version == "1.2.0"

        v100 = registry.get("turn-decision-agent", "1.0.0")
        assert v100.prompt_version == "1.0.0"
        assert v100.prompt_id == "genesis.turn-decision"
