"""Projection types — safe data structures for model input."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from genesis_cognitive.enums import FreshnessState, OperationalState, TurnRole
from genesis_cognitive.types.monetary import NonNegativeDecimalString, SignedDecimalString


class SemanticRecentTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: TurnRole
    summary: str = Field(min_length=1)


class AuthorizedProductReference(BaseModel):
    """Product from authorized portfolio including balance and freshness."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    product_ref: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    label: str | None
    alias: str | None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    operational_state: OperationalState
    recent_balance: SignedDecimalString | None
    known_reserved_amount: NonNegativeDecimalString | None
    balance_as_of: datetime | None
    freshness_state: FreshnessState


class SemanticCapabilityDescription(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent_id: str
    capability_candidate: str | None
    selected_route: str
    allowed_entities: list[str]


class SemanticTurnInput(BaseModel):
    """Safe input for the model. No identity fields, tokens, or credentials."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    raw_text: str = Field(min_length=1)
    language: str = Field(min_length=2)
    recent_turns_summary: list[SemanticRecentTurn]
    known_products: list[AuthorizedProductReference]
    capability_catalog: list[SemanticCapabilityDescription]
    allowed_entities: list[str]
