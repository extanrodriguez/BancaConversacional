"""Context layer types — input models and context structures."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from genesis_cognitive.enums import (
    FreshnessState,
    OperationalState,
    SessionStatus,
    TurnRole,
)
from genesis_cognitive.types.monetary import NonNegativeDecimalString, SignedDecimalString

# --- Orchestrator input ---


class OrchestratorUserTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    raw_text: str = Field(min_length=1, max_length=8000)


class OrchestratorChannelContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    channel: str = Field(min_length=1, max_length=64)
    client_slot: str = Field(min_length=1, max_length=128)
    authenticated: bool
    locale: str = Field(min_length=2, max_length=32, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")


class OrchestratorTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    type: Literal["USER_MESSAGE"]
    conversation_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(min_length=1, max_length=128)
    subject_token: str = Field(min_length=1, max_length=512)
    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    user_turn: OrchestratorUserTurn
    channel_context: OrchestratorChannelContext


# --- Cognitive internal ---


class UserTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    raw_text: str = Field(min_length=1, max_length=8000)
    language: str = Field(min_length=2, max_length=3, pattern=r"^[a-z]{2,3}$")


class ChannelContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    channel: str = Field(min_length=1, max_length=64)
    locale: str = Field(min_length=2, max_length=32, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")
    authenticated: bool
    client_slot: str = Field(min_length=1, max_length=128)


class RecentTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: TurnRole
    summary: str = Field(min_length=1, max_length=4000)


class PortfolioProduct(BaseModel):
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


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: str = Field(min_length=1)
    generated_at: datetime
    fresh_until: datetime
    freshness_state: FreshnessState
    products: tuple[PortfolioProduct, ...]


class SessionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    session_status: SessionStatus
    recent_turns: tuple[RecentTurn, ...] = Field(max_length=12)
    known_products: PortfolioSnapshot
    pending_operation: None
    last_operation_request: None
    last_operation_result: None


class CognitiveTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    contract_version: Literal["1.0"]
    input_type: Literal["user_turn"]
    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    subject_token: str = Field(min_length=1, max_length=512)
    customer_id: str = Field(min_length=1, max_length=128)
    turn_number: int = Field(ge=1)
    user_turn: UserTurn
    session_context: SessionContext
    channel_context: ChannelContext


class ValidatedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: str
    correlation_id: str
    conversation_id: str
    customer_id: str
    subject_token: str
    raw_text: str
    locale: str
    authenticated: bool
    channel: str
    client_slot: str
