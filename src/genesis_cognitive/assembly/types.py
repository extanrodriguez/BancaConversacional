"""Assembly types — external contracts for the orchestrator."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from genesis_cognitive.enums import (
    InteractionFamily,
    InterpretationMode,
    NextAction,
    SelectedRoute,
)
from genesis_cognitive.types.constraints import (
    ENTITY_FIELD_NAMES,
    CapabilityName,
    EntityFieldName,
    NonEmptyId,
    RequirementName,
)
from genesis_cognitive.types.monetary import NonNegativeDecimalString


class ResolvedDetectedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    account_ref: str | None = Field(default=None, min_length=1)
    source_account_ref: str | None = Field(default=None, min_length=1)
    destination_account_ref: str | None = Field(default=None, min_length=1)
    amount: NonNegativeDecimalString | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    knowledge_topic: str | None = Field(default=None, min_length=1)


class ResolvedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    action_id: UUID
    sequence: int = Field(ge=1)
    intent_id: CapabilityName
    capability_candidate: CapabilityName | None = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    interaction_family: InteractionFamily
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    selected_route: SelectedRoute
    next_action: NextAction
    detected_entities: ResolvedDetectedEntities
    missing_requirements: list[RequirementName]
    depends_on_action_ids: list[UUID]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_unique_deps(self) -> "ResolvedAction":
        if len(self.depends_on_action_ids) != len(set(self.depends_on_action_ids)):
            raise ValueError("depends_on_action_ids must not contain duplicates.")
        if len(self.missing_requirements) != len(set(self.missing_requirements)):
            raise ValueError("missing_requirements must not contain duplicates.")
        return self


class ResolvedClarification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    target_action_id: UUID
    missing_requirements: list[RequirementName] = Field(min_length=1)
    suggested_question: str = Field(min_length=1, max_length=1024)
    already_known: list[EntityFieldName]

    @model_validator(mode="after")
    def validate_unique_lists(self) -> "ResolvedClarification":
        if len(self.missing_requirements) != len(set(self.missing_requirements)):
            raise ValueError("missing_requirements must not contain duplicates.")
        if len(self.already_known) != len(set(self.already_known)):
            raise ValueError("already_known must not contain duplicates.")
        for item in self.already_known:
            if item not in ENTITY_FIELD_NAMES:
                raise ValueError(f"already_known item '{item}' is not a valid entity field name.")
        return self


class UnsupportedSegmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    segment_description: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=512)


class IntentResolution(BaseModel):
    """External contract for orchestrator. No customer_id or subject_token."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    contract_version: Literal["1.0"]
    output_type: Literal["intent_resolution"]
    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    resolver_version: str = Field(min_length=1, max_length=64)
    prompt_id: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    mode: InterpretationMode
    actions: list[ResolvedAction]
    clarifications: list[ResolvedClarification]
    unsupported_segments: list[UnsupportedSegmentOutput]

    @model_validator(mode="after")
    def validate_clarification_alignment(self) -> "IntentResolution":
        """Validate clarification already_known against resolved actions."""
        action_map = {a.action_id: a for a in self.actions}

        for clar in self.clarifications:
            # 1. Target action must exist
            target = action_map.get(clar.target_action_id)
            if target is None:
                raise ValueError(
                    f"Clarification targets non-existent action_id {clar.target_action_id}."
                )

            # 2. missing_requirements in clarification must be in action
            for req in clar.missing_requirements:
                if req not in target.missing_requirements:
                    raise ValueError(
                        f"Clarification requests '{req}' not in action "
                        f"{target.action_id} missing_requirements."
                    )

            # 3. Non-null detected entity names
            non_null_entities = {
                k for k, v in target.detected_entities.model_dump().items() if v is not None
            }

            # 4. already_known must match exactly
            if set(clar.already_known) != non_null_entities:
                raise ValueError(
                    f"already_known must match non-null detected_entities "
                    f"for action {target.action_id}."
                )

            # 5. Disjoint check
            if set(clar.already_known) & set(clar.missing_requirements):
                raise ValueError("already_known and missing_requirements must be disjoint.")

        return self


# --- Error Response ---


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    CONTEXT_PROVIDER_ERROR = "CONTEXT_PROVIDER_ERROR"
    MODEL_INVOCATION_ERROR = "MODEL_INVOCATION_ERROR"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"


_ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_INPUT: "La solicitud no es estructuralmente valida.",
    ErrorCode.AUTHENTICATION_REQUIRED: "Se requiere autenticacion.",
    ErrorCode.CONTEXT_PROVIDER_ERROR: "Error al obtener contexto.",
    ErrorCode.MODEL_INVOCATION_ERROR: "Error al invocar el modelo.",
    ErrorCode.INVALID_MODEL_OUTPUT: "La respuesta del modelo no es valida.",
}


class ErrorResponse(BaseModel):
    """Typed error response — static messages only."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    error: Literal[True]
    error_code: ErrorCode
    message: str
    request_id: NonEmptyId | None
    correlation_id: NonEmptyId | None

    @model_validator(mode="after")
    def validate_message_matches_code(self) -> "ErrorResponse":
        expected = _ERROR_MESSAGES.get(self.error_code)
        if expected and self.message != expected:
            raise ValueError(
                f"Message must be '{expected}' for error_code '{self.error_code}', "
                f"got '{self.message}'."
            )
        return self
