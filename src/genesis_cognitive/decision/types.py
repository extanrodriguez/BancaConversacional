"""Decision layer types — model output structures with invariant validation."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from genesis_cognitive.enums import InterpretationMode, SelectedRoute
from genesis_cognitive.types.constraints import (
    ENTITY_FIELD_NAMES,
    CapabilityName,
    EntityFieldName,
    RequirementName,
)
from genesis_cognitive.types.monetary import NonNegativeDecimalString


class DetectedEntities(BaseModel):
    """Closed entity model — only authorized keys, amounts as NonNegativeDecimalString."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    account_ref: str | None = Field(default=None, min_length=1)
    source_account_ref: str | None = Field(default=None, min_length=1)
    destination_account_ref: str | None = Field(default=None, min_length=1)
    amount: NonNegativeDecimalString | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    knowledge_topic: str | None = Field(default=None, min_length=1)


class SemanticAction(BaseModel):
    """Model output action — no action_id, domain, family, or next_action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    sequence: int = Field(ge=1)
    intent_id: CapabilityName
    capability_candidate: CapabilityName | None
    selected_route: SelectedRoute
    detected_entities: DetectedEntities
    missing_requirements: list[RequirementName]
    depends_on: list[int]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_unique_lists(self) -> "SemanticAction":
        if len(self.missing_requirements) != len(set(self.missing_requirements)):
            raise ValueError("missing_requirements must not contain duplicates.")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on must not contain duplicates.")
        return self


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    target_action_sequence: int = Field(ge=1)
    missing_requirements: list[RequirementName] = Field(min_length=1)
    suggested_question: str = Field(min_length=1, max_length=1024)
    already_known: list[EntityFieldName]

    @model_validator(mode="after")
    def validate_unique_lists(self) -> "ClarificationRequest":
        if len(self.missing_requirements) != len(set(self.missing_requirements)):
            raise ValueError("missing_requirements must not contain duplicates.")
        if len(self.already_known) != len(set(self.already_known)):
            raise ValueError("already_known must not contain duplicates.")
        for item in self.already_known:
            if item not in ENTITY_FIELD_NAMES:
                raise ValueError(f"already_known item '{item}' is not a valid entity field name.")
        return self


class UnsupportedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    segment_description: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=512)


class TurnInterpretation(BaseModel):
    """Full model output with invariant validation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: InterpretationMode
    actions: list[SemanticAction]
    clarifications: list[ClarificationRequest]
    unsupported_segments: list[UnsupportedSegment]

    @model_validator(mode="after")
    def validate_invariants(self) -> "TurnInterpretation":
        self._validate_mode_invariants()
        self._validate_sequences_unique()
        self._validate_depends_on_references()
        self._validate_dag_acyclic()
        self._validate_clarification_targets()
        return self

    def _validate_mode_invariants(self) -> None:
        mode = self.mode
        actions = self.actions
        clarifications = self.clarifications
        unsupported = self.unsupported_segments

        if mode == InterpretationMode.SINGLE:
            if len(actions) != 1:
                raise ValueError("SINGLE mode requires exactly one action.")
            if actions[0].depends_on:
                raise ValueError("SINGLE mode action must have empty depends_on.")
            if clarifications:
                raise ValueError("SINGLE mode must have empty clarifications.")
            if unsupported:
                raise ValueError("SINGLE mode must have empty unsupported_segments.")

        elif mode == InterpretationMode.MULTI_INDEPENDENT:
            if len(actions) < 2:
                raise ValueError("MULTI_INDEPENDENT requires two or more actions.")
            if any(a.depends_on for a in actions):
                raise ValueError("MULTI_INDEPENDENT actions must all have empty depends_on.")

        elif mode == InterpretationMode.MULTI_DEPENDENT:
            if len(actions) < 2:
                raise ValueError("MULTI_DEPENDENT requires two or more actions.")
            if not any(a.depends_on for a in actions):
                raise ValueError("MULTI_DEPENDENT requires at least one dependency.")

        elif mode == InterpretationMode.CLARIFICATION:
            if not actions:
                raise ValueError("CLARIFICATION requires at least one partial action.")
            if not clarifications:
                raise ValueError("CLARIFICATION requires non-empty clarifications.")
            # At least one action must have missing_requirements
            if not any(a.missing_requirements for a in actions):
                raise ValueError(
                    "CLARIFICATION: at least one action must have missing_requirements."
                )

        elif mode == InterpretationMode.UNSUPPORTED:
            if actions:
                raise ValueError("UNSUPPORTED mode must have empty actions.")
            if not unsupported:
                raise ValueError("UNSUPPORTED requires non-empty unsupported_segments.")

        elif mode == InterpretationMode.MIXED:
            if not actions:
                raise ValueError("MIXED mode requires non-empty actions.")
            if not unsupported:
                raise ValueError("MIXED requires non-empty unsupported_segments.")

    def _validate_sequences_unique(self) -> None:
        sequences = [a.sequence for a in self.actions]
        if len(sequences) != len(set(sequences)):
            raise ValueError("Action sequences must be unique.")

    def _validate_depends_on_references(self) -> None:
        valid_seqs = {a.sequence for a in self.actions}
        for action in self.actions:
            if action.sequence in action.depends_on:
                raise ValueError(f"Action {action.sequence} cannot depend on itself.")
            if len(action.depends_on) != len(set(action.depends_on)):
                raise ValueError(f"Action {action.sequence} has duplicate depends_on.")
            for dep in action.depends_on:
                if dep not in valid_seqs:
                    raise ValueError(
                        f"Action {action.sequence} depends on non-existent sequence {dep}."
                    )

    def _validate_dag_acyclic(self) -> None:
        adj: dict[int, list[int]] = {a.sequence: list(a.depends_on) for a in self.actions}
        visited: set[int] = set()
        in_stack: set[int] = set()

        def dfs(node: int) -> None:
            if node in in_stack:
                raise ValueError(f"Cyclic dependency detected involving action {node}.")
            if node in visited:
                return
            in_stack.add(node)
            for neighbor in adj.get(node, []):
                dfs(neighbor)
            in_stack.discard(node)
            visited.add(node)

        for seq in adj:
            dfs(seq)

    def _validate_clarification_targets(self) -> None:
        valid_seqs = {a.sequence for a in self.actions}
        action_reqs = {a.sequence: set(a.missing_requirements) for a in self.actions}
        seen: set[tuple[int, str]] = set()

        for clar in self.clarifications:
            if clar.target_action_sequence not in valid_seqs:
                raise ValueError(
                    f"Clarification targets non-existent action {clar.target_action_sequence}."
                )
            # Each requested requirement must exist in the action's missing_requirements
            target_reqs = action_reqs.get(clar.target_action_sequence, set())
            for req in clar.missing_requirements:
                if req not in target_reqs:
                    raise ValueError(
                        f"Clarification requests '{req}' not in action "
                        f"{clar.target_action_sequence} missing_requirements."
                    )
                # Cannot request something in already_known
                if req in clar.already_known:
                    raise ValueError(f"Cannot request '{req}' that is in already_known.")
                key = (clar.target_action_sequence, req)
                if key in seen:
                    raise ValueError(
                        f"Duplicate clarification for action "
                        f"{clar.target_action_sequence} requirement '{req}'."
                    )
                seen.add(key)

            # Validate already_known matches non-null detected_entities (directive 247)
            target_action = None
            for a in self.actions:
                if a.sequence == clar.target_action_sequence:
                    target_action = a
                    break
            if target_action is not None:
                non_null_entities = {
                    k
                    for k, v in target_action.detected_entities.model_dump().items()
                    if v is not None
                }
                if set(clar.already_known) != non_null_entities:
                    raise ValueError(
                        f"already_known must match non-null detected_entities "
                        f"for action {clar.target_action_sequence}."
                    )
                # Disjoint check
                if set(clar.already_known) & set(clar.missing_requirements):
                    raise ValueError("already_known and missing_requirements must be disjoint.")
