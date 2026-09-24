"""SemanticContractGate — deterministic post-model validation.

Validates that a TurnInterpretation produced by the model complies with:
1. Catalog coherence (intent_id + capability_candidate + selected_route + entities).
2. Entity reference validity (product_ref values exist in the portfolio).
3. Coherence of missing_requirements vs detected_entities.
4. Sequence uniqueness and depends_on validity (DAG).

Does NOT interpret raw_text, resolve aliases, normalize, or apply keyword routing.
Uses ONLY model_input.effective_capabilities for validation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from genesis_cognitive.decision.types import TurnInterpretation
from genesis_cognitive.enums import InterpretationMode
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputEnvelope,
    ProjectedCapability,
)


class ValidatedTurnInterpretation(BaseModel):
    """Result of the semantic contract gate validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    interpretation: TurnInterpretation
    catalog_valid: bool
    entity_refs_valid: bool
    violations: tuple[str, ...]


class SemanticContractGate:
    """Deterministic validation gate applied AFTER model interpretation.

    Validates:
    - Each action's intent_id + capability_candidate + selected_route against
      the effective capabilities in the ModelInputEnvelope.
    - Entity field names are within the capability's allowed entities.
    - Coherence between detected_entities, missing_requirements, and mode.
    - Sequence uniqueness and DAG validity of depends_on.
    - Each non-null product reference (account_ref, source_account_ref,
      destination_account_ref) is a valid product_ref in the portfolio.

    Does NOT:
    - Read raw_text.
    - Normalize or transform references.
    - Resolve aliases to product_ref.
    - Use keywords, regex, or synonyms.
    """

    def validate(
        self,
        interpretation: TurnInterpretation,
        model_input: ModelInputEnvelope,
    ) -> ValidatedTurnInterpretation:
        """Validate interpretation against model_input context.

        Args:
            interpretation: The TurnInterpretation produced by the model.
            model_input: The ModelInputEnvelope that was sent to the model.

        Returns:
            ValidatedTurnInterpretation with validation results.
        """
        violations: list[str] = []

        # 1. Catalog validation (triple + entities + coherence + sequence + depends_on)
        catalog_valid = self._validate_catalog(interpretation, model_input, violations)

        # 2. Entity reference validation (product refs in portfolio)
        entity_refs_valid = self._validate_entity_refs(interpretation, model_input, violations)

        return ValidatedTurnInterpretation.model_construct(
            interpretation=interpretation,
            catalog_valid=catalog_valid,
            entity_refs_valid=entity_refs_valid,
            violations=tuple(violations),
        )

    def _validate_catalog(
        self,
        interpretation: TurnInterpretation,
        model_input: ModelInputEnvelope,
        violations: list[str],
    ) -> bool:
        """Validate each action against effective_capabilities in model_input."""
        catalog_valid = True

        for action in interpretation.actions:
            # Find EXACTLY ONE matching capability
            matching_cap = self._find_matching_capability(
                action.intent_id,
                action.capability_candidate,
                action.selected_route.value,
                model_input.effective_capabilities,
            )

            if matching_cap is None:
                catalog_valid = False
                violations.append(
                    f"Action seq={action.sequence}: "
                    f"({action.intent_id}, {action.capability_candidate}, "
                    f"{action.selected_route.value}) not in effective_capabilities."
                )
                continue

            # Entity field names validation: non-null fields must be in
            # required_entities + optional_entities
            detected = action.detected_entities
            detected_keys = {k for k, v in detected.model_dump().items() if v is not None}
            allowed_entities = set(matching_cap.required_entities) | set(
                matching_cap.optional_entities
            )

            extra_entities = detected_keys - allowed_entities
            if extra_entities:
                catalog_valid = False
                violations.append(
                    f"Action seq={action.sequence}: entity fields "
                    f"{sorted(extra_entities)} not in capability's "
                    f"required_entities + optional_entities."
                )

            # Coherence validation
            required_set = set(matching_cap.required_entities)

            # missing_requirements only contains fields from cap.required_entities
            # Exception: CLARIFICATION_REQUIRED intent uses the clarification capability
            # which has no required_entities; missing_requirements holds disambiguation keys.
            if action.intent_id != "CLARIFICATION_REQUIRED":
                invalid_missing = set(action.missing_requirements) - required_set
                if invalid_missing:
                    catalog_valid = False
                    violations.append(
                        f"Action seq={action.sequence}: missing_requirements "
                        f"{sorted(invalid_missing)} not in capability required_entities."
                    )

            # A required entity that IS present → NOT in missing_requirements
            for field in required_set:
                if field in detected_keys and field in action.missing_requirements:
                    catalog_valid = False
                    violations.append(
                        f"Action seq={action.sequence}: required entity '{field}' "
                        f"is present but listed in missing_requirements."
                    )

            # A required entity that is ABSENT → IS in missing_requirements
            # (only enforce for CLARIFICATION mode — for complete modes we check no missing)
            if interpretation.mode == InterpretationMode.CLARIFICATION:
                for field in required_set:
                    if field not in detected_keys and field not in action.missing_requirements:
                        catalog_valid = False
                        violations.append(
                            f"Action seq={action.sequence}: required entity '{field}' "
                            f"is absent but not in missing_requirements."
                        )

            # For SINGLE/MULTI_INDEPENDENT/MULTI_DEPENDENT: no missing requirements allowed
            complete_modes = {
                InterpretationMode.SINGLE,
                InterpretationMode.MULTI_INDEPENDENT,
                InterpretationMode.MULTI_DEPENDENT,
            }
            if interpretation.mode in complete_modes and action.missing_requirements:
                catalog_valid = False
                violations.append(
                    f"Action seq={action.sequence}: mode={interpretation.mode.value} "
                    f"does not allow missing_requirements."
                )

        # Sequence validation: positive integers, unique
        sequences = [a.sequence for a in interpretation.actions]
        if any(s < 1 for s in sequences):
            catalog_valid = False
            violations.append("Action sequences must be positive integers.")
        if len(sequences) != len(set(sequences)):
            catalog_valid = False
            violations.append("Action sequences must be unique.")

        # depends_on validation
        valid_seqs = set(sequences)
        for action in interpretation.actions:
            for dep in action.depends_on:
                if dep == action.sequence:
                    catalog_valid = False
                    violations.append(
                        f"Action seq={action.sequence}: depends_on contains self-reference."
                    )
                if dep not in valid_seqs:
                    catalog_valid = False
                    violations.append(
                        f"Action seq={action.sequence}: depends_on references "
                        f"non-existent sequence {dep}."
                    )

        # Cycle detection
        if not self._is_dag(interpretation):
            catalog_valid = False
            violations.append("depends_on graph contains a cycle.")

        return catalog_valid

    def _find_matching_capability(
        self,
        intent_id: str,
        capability_candidate: str | None,
        selected_route: str,
        capabilities: tuple[ProjectedCapability, ...],
    ) -> ProjectedCapability | None:
        """Find exactly one matching capability in effective_capabilities."""
        for cap in capabilities:
            if (
                intent_id in cap.intent_ids
                and cap.capability_candidate == capability_candidate
                and cap.selected_route.value == selected_route
            ):
                return cap
        return None

    def _is_dag(self, interpretation: TurnInterpretation) -> bool:
        """Check that the depends_on graph is acyclic."""
        adj: dict[int, list[int]] = {a.sequence: list(a.depends_on) for a in interpretation.actions}
        visited: set[int] = set()
        in_stack: set[int] = set()

        def dfs(node: int) -> bool:
            if node in in_stack:
                return False
            if node in visited:
                return True
            in_stack.add(node)
            for neighbor in adj.get(node, []):
                if not dfs(neighbor):
                    return False
            in_stack.discard(node)
            visited.add(node)
            return True

        return all(dfs(seq) for seq in adj)

    def _validate_entity_refs(
        self,
        interpretation: TurnInterpretation,
        model_input: ModelInputEnvelope,
        violations: list[str],
    ) -> bool:
        """Validate that product references match portfolio product_ref values."""
        valid_product_refs: set[str] = {product.product_ref for product in model_input.portfolio}

        entity_refs_valid = True
        ref_fields = ("account_ref", "source_account_ref", "destination_account_ref")

        for action in interpretation.actions:
            entities = action.detected_entities
            for field_name in ref_fields:
                value = getattr(entities, field_name, None)
                if value is not None and value not in valid_product_refs:
                    entity_refs_valid = False
                    violations.append(
                        f"Action seq={action.sequence}: "
                        f"{field_name}='{value}' not in portfolio product_refs "
                        f"({', '.join(sorted(valid_product_refs))})."
                    )

        return entity_refs_valid
