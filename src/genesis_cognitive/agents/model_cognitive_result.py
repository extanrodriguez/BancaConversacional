"""Transport DTO for Azure OpenAI Chat Completions structured output.

Flat structure — no oneOf, no discriminated unions, no fields that the model
should not produce. The model proposes; the code derives contracts.

The model does NOT produce:
- mode
- capability_candidate
- selected_route
- required_entities / optional_entities
- missing_requirements
- already_known
- output_contract
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelDetectedEntities(BaseModel):
    """Entities detected by the model from natural language."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    account_ref: str | None = None
    source_account_ref: str | None = None
    destination_account_ref: str | None = None
    amount: str | None = None
    currency: str | None = None
    knowledge_topic: str | None = None


class ModelActionProposal(BaseModel):
    """A single action proposed by the model."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    sequence: int = Field(ge=1)
    capability_id: str
    intent_id: str
    detected_entities: ModelDetectedEntities
    depends_on: tuple[int, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


class ModelSemanticProposal(BaseModel):
    """Top-level model output. Flat, no unions, Azure-compatible.

    result_type: ACTIONS | NON_OPERATIONAL | UNSUPPORTED
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    result_type: str  # ACTIONS | NON_OPERATIONAL | UNSUPPORTED
    actions: tuple[ModelActionProposal, ...] = ()
    non_operational_message: str | None = None
    unsupported_segments: tuple[str, ...] = ()
